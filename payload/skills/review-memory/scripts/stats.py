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


def fmt(n):
    return f"{n:,.0f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo_root", nargs="?", default=".")
    ap.add_argument("--sessions", type=int, default=10)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    d = project_dir_for(a.repo_root)
    logs = glob.glob(os.path.join(d, "*.jsonl")) if d else []
    sessions = read_usage(logs, a.sessions)
    activity = review_activity(a.repo_root)

    if a.json:
        print(json.dumps({"sessions": sessions, "review_activity": activity,
                          "toolset_constants": TOOLSET}, indent=2))
        return

    print("pr-review-loop stats\n")

    if not sessions:
        print("token usage: no Claude Code logs found for this directory")
        print(f"  looked in: {d or '~/.claude/projects/<slug-of-cwd>'}\n")
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

        print(f"token usage — last {len(sessions)} session(s), MAIN THREAD ONLY")
        print(f"  turns                  {fmt(tot['turns']):>16}")
        print(f"  output                 {fmt(tot['output_tokens']):>16}")
        print(f"  cache read   (x{CACHE_READ_RATIO})   {fmt(reads):>16}")
        print(f"  cache write  (x{CACHE_WRITE_RATIO})  {fmt(writes):>16}")
        print(f"  uncached input         {fmt(tot['input_tokens']):>16}")
        print(f"  ---------------------- {'-'*16}")
        print(f"  effective input        {fmt(eff):>16}   (ratio-based, not a bill)")
        print(f"  cache hit rate         {hit:>15.1f}%   (low => caches keep re-warming)")
        print()
        print(f"  {'session':<26}{'turns':>7}{'eff.input':>12}{'output':>10}")
        for s in sessions[:5]:
            print(f"  {s['mtime']:<26}{s['turns']:>7}{fmt(effective_input(s)):>12}{fmt(s['output_tokens']):>10}")
        print()

    print("review activity — this repo (.review-memory/decisions.jsonl)")
    if not activity:
        print("  none yet — created on the first review (memory.py record)\n")
    else:
        a_ = activity
        sev = a_["severity"]; p0 = sev.get("P0", 0); p1 = sev.get("P1", 0)
        print(f"  reviews (MR x round) {a_['reviews']:>5}      MRs {a_['mrs']:>4}      rounds {a_['rounds']:>3}")
        print(f"  findings             {a_['findings']:>5}      P0 {p0:>5}      P1 {p1:>5}   (blockers: {p0+p1})")
        print(f"  severity split       {sev}")
        v = a_["verdicts"]
        if a_["rollups"]:
            appr = v.get("approve", 0) + v.get("approve_minor", 0)
            chg = v.get("request_changes", 0)
            tot = appr + chg
            print(f"  verdicts             approved {appr:>4}   request-changes {chg:>4}"
                  + (f"   ({100*appr/tot:.0f}% approved)" if tot else ""))
            print(f"                       {v}")
        else:
            print("  verdicts             not recorded yet — roll-ups start on the next")
            print("                       review (see 'reviews' in the record contract).")
        r = a_["resolutions"]
        acted = r.get("resolved", 0); disp = r.get("disputed", 0)
        known = sum(r.values()) - r.get("open", 0)
        print(f"  dev verdicts         {r}")
        if known:
            print(f"                       {100*acted/known:.0f}% of answered findings were fixed"
                  f" · {100*disp/known:.0f}% disputed (high => reviewers wrong here)")
        if a_["repeat"]:
            print("  recurring (ripe to distill into CLAUDE.md / an ADR):")
            for s, c in a_["repeat"]:
                print(f"    x{c}  {s}")
        print()

    print("engine efficiency — measured constants (v1.10.0 probes, not this run)")
    t = TOOLSET
    print(f"  reviewer agents run on a minimal toolset (Read/Grep/Glob/Bash):")
    print(f"    review-panel      ~{fmt(t['review_panel_per_turn'])} tok/turn")
    print(f"    general-purpose   ~{fmt(t['general_purpose_per_turn'])} tok/turn  (~100 unused MCP schemas)")
    print(f"    probe:  {fmt(t['probe_gp'])} -> {fmt(t['probe_rp'])} on identical work "
          f"({100*(1-t['probe_rp']/t['probe_gp']):.0f}%)")
    print(f"    real review: {fmt(t['real_review_before'])} -> {fmt(t['real_review_after'])} "
          f"({100*(1-t['real_review_after']/t['real_review_before']):.0f}%), quality held")
    print()
    print("caveats")
    print("  * Subagent (reviewer) turns are NOT logged by Claude Code — verified, 0 of")
    print("    49k+ logged turns are sidechain. The token figures above are MAIN THREAD")
    print("    ONLY; a review's true cost is higher and cannot be attributed per reviewer.")
    print("  * 'effective input' applies published cache ratios; it compares, it does not bill.")
    print("  * The engine constants are measured, but from the v1.10.0 probes — not from")
    print("    your runs. Nothing here estimates your savings; we cannot measure them.")


if __name__ == "__main__":
    main()
