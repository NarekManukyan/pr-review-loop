#!/usr/bin/env python3
"""pr-review-loop stats — real token usage + review activity.

Everything here is READ FROM DISK, never estimated by a model:
  - token usage  <- ~/.claude/projects/<project>/*.jsonl (Claude Code's own logs)
  - review activity <- <repo>/.review-memory/decisions.jsonl

Honest scope (read this before trusting a number):
  * Claude Code logs ONLY main-thread turns. Subagent (reviewer) turns are not
    written to any log — verified: 0 sidechain turns across every project log.
    So per-reviewer cost CANNOT be reported. These totals are main-thread only,
    and a review's real cost is HIGHER than what this shows.
  * "effective input" applies the published cache ratios (read x0.10,
    write x1.25). It is a ratio, not a bill. Use it to compare, not to budget.

Usage:
  stats.py [repo_root] [--project <name>] [--sessions N] [--json]
"""
import argparse, glob, json, os, sys, collections
from datetime import datetime

CACHE_READ_RATIO = 0.10   # cache hit billed at ~10% of base input
CACHE_WRITE_RATIO = 1.25  # cache write billed at ~125% of base input

# Measured constants from the v1.10.0 probes (controlled, identical work).
TOOLSET = {
    "general_purpose_per_turn": 6451,
    "review_panel_per_turn": 1078,
    "probe_gp": 71479, "probe_rp": 12379,
    "real_review_before": 154347, "real_review_after": 102782,
}


def project_dir_for(repo_root):
    """Claude Code slugifies the cwd path into ~/.claude/projects/<slug>.

    Verified against real dirs: BOTH "/" and "_" become "-"
    (/Users/x/M-One_Projects -> -Users-x-M-One-Projects). Fall back to a prefix
    match so we still find the logs if the rule ever changes.
    """
    root = os.path.abspath(repo_root)
    base = os.path.expanduser("~/.claude/projects")
    slug = root.replace("/", "-").replace("_", "-")
    exact = os.path.join(base, slug)
    if os.path.isdir(exact):
        return exact
    # tolerate rule drift: prefer the longest dir name that prefixes ours
    if os.path.isdir(base):
        cands = [d for d in os.listdir(base)
                 if os.path.isdir(os.path.join(base, d)) and slug.startswith(d)]
        if cands:
            return os.path.join(base, max(cands, key=len))
    return None


def read_usage(logs, limit=None):
    per_session = []
    for p in sorted(logs, key=os.path.getmtime, reverse=True)[:limit]:
        t = collections.Counter(); turns = 0; models = collections.Counter()
        for line in open(p, errors="ignore"):
            if '"usage"' not in line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            m = d.get("message") or {}
            u = m.get("usage") or d.get("usage") or {}
            if not u:
                continue
            turns += 1
            models[m.get("model", "?")] += 1
            for k in ("input_tokens", "output_tokens",
                      "cache_read_input_tokens", "cache_creation_input_tokens"):
                t[k] += u.get(k, 0) or 0
        if turns:
            per_session.append({
                "file": os.path.basename(p), "turns": turns,
                "mtime": datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M"),
                "model": (models.most_common(1) or [("?", 0)])[0][0],
                **t,
            })
    return per_session


def effective_input(s):
    return (s["cache_read_input_tokens"] * CACHE_READ_RATIO
            + s["cache_creation_input_tokens"] * CACHE_WRITE_RATIO
            + s["input_tokens"])


def _verdict_bucket(v):
    """Normalise a verdict string to approve / minor / changes."""
    t = (v or "").lower()
    if "request" in t or "changes" in t or "blocked" in t:
        return "request_changes"
    if "minor" in t:
        return "approve_minor"
    if "approve" in t:
        return "approve"
    return "other"


def review_activity(repo_root):
    p = os.path.join(repo_root, ".review-memory", "decisions.jsonl")
    if not os.path.exists(p):
        return None
    sev = collections.Counter(); res = collections.Counter()
    rounds = set(); mrs = set(); sigs = collections.Counter()
    findings = 0
    verdicts = collections.Counter(); rollups = 0
    pairs = set()          # (mr, round) — a "review" even without a roll-up
    for line in open(p, errors="ignore"):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        kind = d.get("kind", "finding")
        if d.get("mr") is not None:
            mrs.add(str(d["mr"]))
            if d.get("round") is not None:
                pairs.add((str(d["mr"]), d["round"]))
        if d.get("round") is not None:
            rounds.add(d["round"])
        if kind == "review":
            rollups += 1
            verdicts[_verdict_bucket(d.get("verdict"))] += 1
            continue
        if kind == "watch":
            continue
        findings += 1
        sev[d.get("severity", "?")] += 1
        res[d.get("dev_resolution", "open")] += 1
        if d.get("signature"):
            sigs[d["signature"]] += 1
    return {"findings": findings, "rounds": len(rounds), "mrs": len(mrs),
            "reviews": len(pairs), "rollups": rollups, "verdicts": dict(verdicts),
            "severity": dict(sev), "resolutions": dict(res),
            "repeat": [(s, c) for s, c in sigs.most_common(5) if c > 1]}


# ---- presentation (rtk-gain style) ------------------------------------------
USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
_C = {"g": "\033[92m", "y": "\033[93m", "c": "\033[96m", "r": "\033[91m",
      "d": "\033[2m", "b": "\033[1m", "m": "\033[95m", "x": "\033[0m"}


def c(txt, col):
    return f"{_C[col]}{txt}{_C['x']}" if USE_COLOR else str(txt)


def short(n):
    """1234 -> 1.2K · 155100 -> 155.1K · 2_500_000 -> 2.5M (rtk-style)."""
    n = float(n or 0)
    sign = "-" if n < 0 else ""
    n = abs(n)
    for div, unit in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if n >= div * 0.9995:   # 999_999 rolls up to 1.0M, not 1000K
            v = n / div
            return f"{sign}{v:.1f}{unit}" if v < 99.95 else f"{sign}{v:.0f}{unit}"
    return f"{sign}{int(n)}"


def bar(pct, width=22, col="g"):
    fill = max(0, min(width, round(pct / 100 * width)))
    return c("█" * fill, col) + c("░" * (width - fill), "d")


def rule(width=64):
    return c("═" * width, "d")


def kv(label, value, note=""):
    line = f"  {label:<16}{value:>14}"
    if note:
        line += "   " + c(note, "d")
    print(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo_root", nargs="?", default=".")
    ap.add_argument("--sessions", type=int, default=0,
                    help="limit to the N most recent sessions (default: all)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    global USE_COLOR
    if a.json:
        USE_COLOR = False

    d = project_dir_for(a.repo_root)
    logs = glob.glob(os.path.join(d, "*.jsonl")) if d else []
    sessions = read_usage(logs, a.sessions or None)   # 0 -> all
    activity = review_activity(a.repo_root)

    if a.json:
        print(json.dumps({"sessions": sessions, "review_activity": activity,
                          "toolset_constants": TOOLSET}, indent=2))
        return

    print()
    print(c("[ pr-review-loop stats ]", "b"))
    print(rule())
    print()

    # ---- token usage ----
    if not sessions:
        print(c("  no Claude Code logs found for this directory", "y"))
        print(c(f"  looked in: {d or '~/.claude/projects/<slug-of-cwd>'}", "d"))
        print()
    else:
        tot = collections.Counter()
        for s in sessions:
            for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                      "cache_creation_input_tokens", "turns"):
                tot[k] += s[k]
        eff = effective_input(tot)
        reads = tot["cache_read_input_tokens"]
        writes = tot["cache_creation_input_tokens"]
        hit = 100 * reads / (reads + writes) if (reads + writes) else 0
        hcol = "g" if hit >= 90 else ("y" if hit >= 70 else "r")

        print(c(f"Token usage — {len(sessions)} session(s), main thread only", "c"))
        print()
        kv("Sessions", str(len(sessions)))
        kv("Turns", short(tot["turns"]))
        kv("Output", short(tot["output_tokens"]))
        kv("Cache read", short(reads), f"x{CACHE_READ_RATIO}")
        kv("Cache write", short(writes), f"x{CACHE_WRITE_RATIO}")
        kv("Uncached input", short(tot["input_tokens"]))
        kv("Effective input", short(eff), "ratio, not a bill")
        print(f"  {'Cache hit rate':<16}{bar(hit)} {c(f'{hit:.1f}%', hcol)}")
        print()

        # per-session table, rtk "By Command" style, with an Impact mini-bar
        mx = max(effective_input(s) for s in sessions) or 1
        print(c("By session", "g"))
        print(c(f"  {'#':>2}  {'when':<16}{'turns':>6}{'eff.in':>9}{'output':>9}  impact", "d"))
        rows = sessions if a.sessions else sessions
        shown = rows[:20]
        for i, s in enumerate(shown, 1):
            e = effective_input(s)
            imp = bar(100 * e / mx, width=10, col="c")
            print(f"  {i:>2}. {s['mtime']:<16}{s['turns']:>6}"
                  f"{short(e):>9}{short(s['output_tokens']):>9}  {imp}")
        if len(rows) > len(shown):
            print(c(f"      … +{len(rows)-len(shown)} older session(s) (in the totals above)", "d"))
        print()

    # ---- review scoreboard ----
    print(c("Review scoreboard — .review-memory/decisions.jsonl", "c"))
    print()
    if not activity:
        print(c("  none yet — created on the first review (memory.py record)", "d"))
        print()
    else:
        a_ = activity
        sev = a_["severity"]; p0 = sev.get("P0", 0); p1 = sev.get("P1", 0)
        kv("Reviews (MR×rnd)", str(a_["reviews"]), f"{a_['mrs']} MRs · {a_['rounds']} rounds")
        blk = c(f"{p0+p1} blockers", "r" if p0 else "y") if (p0 + p1) else "0 blockers"
        kv("Findings", str(a_["findings"]),
           f"P0 {p0} · P1 {p1} · P2 {sev.get('P2',0)}  ({blk})")
        v = a_["verdicts"]
        if a_["rollups"]:
            appr = v.get("approve", 0) + v.get("approve_minor", 0)
            chg = v.get("request_changes", 0)
            t_ = appr + chg
            pct = f"{100*appr/t_:.0f}% approved" if t_ else ""
            print(f"  {'Verdicts':<16}{bar(100*appr/t_ if t_ else 0)} "
                  f"{c(f'{appr} approved', 'g')} · {c(f'{chg} changes', 'y')}  {c(pct,'d')}")
        else:
            kv("Verdicts", "—", "roll-ups start on the next recorded review")
        r = a_["resolutions"]
        acted = r.get("resolved", 0); disp = r.get("disputed", 0)
        known = sum(r.values()) - r.get("open", 0)
        if known:
            dcol = "r" if 100 * disp / known >= 25 else "d"
            kv("Dev response", f"{100*acted/known:.0f}% fixed",
               c(f"{100*disp/known:.0f}% disputed", dcol) + c("  (high = reviewers wrong here)", "d"))
        else:
            kv("Dev response", "—", "no developer replies recorded yet")
        if a_["repeat"]:
            print()
            print(c("  Ripe to distill (raised >1×) — promote into CLAUDE.md / an ADR:", "g"))
            for s, cnt in a_["repeat"]:
                print(f"    {c('×'+str(cnt),'y')}  {s}")
        print()

    # ---- engine efficiency (measured constants) ----
    t = TOOLSET
    print(c("Engine efficiency — measured constants (v1.10.0 probes)", "c"))
    print()
    kv("Reviewer/turn", f"~{short(t['review_panel_per_turn'])}", "minimal toolset (Read/Grep/Glob/Bash)")
    kv("general-purpose", f"~{short(t['general_purpose_per_turn'])}", "~100 unused MCP schemas")
    before = t["real_review_before"]
    after = t["real_review_after"]
    save = 100 * (1 - after / before)
    detail = f"({short(before)} → {short(after)}, quality held)"
    print(f"  {'Real-review cut':<16}{bar(save)} {c(f'{save:.0f}%', 'g')} {c(detail, 'd')}")
    print()

    print(c("Caveats", "d"))
    for line in (
        "subagent (reviewer) turns are NOT logged — token figures are main-thread",
        "  only; a review's true cost is higher and can't be attributed per reviewer.",
        "'effective input' applies cache ratios: it compares, it does not bill.",
        "engine constants are from the v1.10.0 probes, not your runs — nothing here",
        "  estimates your savings; those are not measurable from disk.",
    ):
        print(c("  " + line, "d"))


if __name__ == "__main__":
    main()
