#!/usr/bin/env python3
"""Per-repo review memory — recall / record / distill.

A `.review-memory/` corpus lives inside each repo (committed) and accumulates
review outcomes + developer responses. It is a LEARNED EXTENSION of the repo's
CLAUDE.md / ADRs, never a replacement — CLAUDE.md and ADRs always win.

Layout (created by `init`):
  .review-memory/
    README.md         team-facing explanation
    rules.md          human-curated distilled rules (loaded as reviewer context)
    decisions.jsonl   append-only outcome log (source of truth)
    .gitignore        ignores graphify-out/
    graphify-out/     graphify corpus (gitignored, rebuilt from decisions.jsonl)

graphify (optional) adds semantic query + community-detection distill on top of
the JSONL. Everything degrades gracefully to plain JSONL + rules.md when graphify
or node is absent.

Usage:
  memory.py init   <repo_root>
  memory.py recall <repo_root> [--area "tokens paths features"] [--max N]
  memory.py record <repo_root> --input decisions.json
  memory.py distill <repo_root> [--min-count 2]
  memory.py stats  <repo_root>

record input JSON:
  {
    "stack": "flutter-bloc",           # optional, tags every entry
    "commit": "abc123",                # optional
    "date": "2026-07-07",              # optional (ISO); omitted -> left blank
    "entries": [
      {"mr": 58, "signature": "withdrawal/otp-not-validated|correctness",
       "file": "lib/.../withdrawal_email_verification_bloc.dart", "line": 70,
       "category": "Correctness", "severity": "P1", "title": "...",
       "dev_resolution": "deferred",   # open|resolved|deferred|disputed|clarified
       "rationale": "backend handles it in MONE-901", "reviewer": "B", "round": 2}
    ]
  }
signature is optional; if omitted it is derived from file stem + category + title.
"""
import argparse, json, os, re, sys, shutil, subprocess

MEM = '.review-memory'
DEC = 'decisions.jsonl'
RULES = 'rules.md'

# Resolutions that mean "do not re-raise unless the code materially changed".
SUPPRESS = {'disputed', 'clarified', 'resolved'}
# Resolutions that mean "verify the promised guardrail actually landed".
VERIFY = {'deferred'}


def mem_dir(root):
    return os.path.join(root, MEM)


def slug(s, n=6):
    words = re.findall(r'[a-z0-9]+', (s or '').lower())
    return '-'.join(words[:n]) or 'unknown'


def derive_signature(e):
    stem = os.path.splitext(os.path.basename(e.get('file', '') or 'general'))[0]
    cat = slug(e.get('category', ''), 2)
    return f"{stem}/{slug(e.get('title', ''))}|{cat}"


def load_decisions(root):
    path = os.path.join(mem_dir(root), DEC)
    out = []
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return out


def latest_by_signature(decisions):
    """Most recent entry per signature (by (date, round))."""
    best = {}
    for d in decisions:
        sig = d.get('signature')
        if not sig:
            continue
        key = (d.get('date', ''), d.get('round', 0))
        if sig not in best or key >= best[sig][0]:
            best[sig] = (key, d)
    return {sig: v[1] for sig, v in best.items()}


def has_graphify():
    return shutil.which('graphify') is not None and shutil.which('node') is not None


# --------------------------------------------------------------------------- #
def cmd_init(root, _args):
    d = mem_dir(root)
    os.makedirs(os.path.join(d, 'graphify-out'), exist_ok=True)
    created = []
    files = {
        '.gitignore': "graphify-out/\n",
        RULES: (
            "# Review rules for this repo (curated)\n\n"
            "Human-reviewed rules distilled from past review rounds and developer\n"
            "responses. Reviewers load this as extra context. **CLAUDE.md and ADRs\n"
            "outrank this file** — when they conflict, they win.\n\n"
            "Promote a rule here only after the team confirms it (see `memory.py distill`).\n"
            "Once a rule is codified in CLAUDE.md or an ADR, it can be removed here.\n\n"
            "<!-- Add one bullet per confirmed rule, e.g.:\n"
            "- The DI service-locator exception for AppNavigator is intentional (ADR-0009) — do not flag it.\n"
            "-->\n"
        ),
        'README.md': (
            "# .review-memory\n\n"
            "Per-repo memory for the automated review skills (`/review-pr`,\n"
            "`/review-pr-slack`, etc.). Committed to the repo so the whole team\n"
            "shares it and it is reviewed via PR.\n\n"
            "- `decisions.jsonl` — append-only log of past findings + developer\n"
            "  responses (resolved / deferred / disputed / clarified). Source of truth.\n"
            "- `rules.md` — human-curated rules distilled from that log. Loaded as\n"
            "  reviewer context. **CLAUDE.md / ADRs always outrank it.**\n"
            "- `graphify-out/` — queryable graph built from the log (gitignored).\n\n"
            "This memory only *calibrates* reviews (cuts repeat-noise, honors prior\n"
            "deferrals). It never overrides CLAUDE.md or ADRs. Recurring confirmed\n"
            "lessons get promoted by a human into CLAUDE.md / a new ADR.\n"
        ),
    }
    for name, content in files.items():
        p = os.path.join(d, name)
        if not os.path.exists(p):
            with open(p, 'w', encoding='utf-8') as f:
                f.write(content)
            created.append(name)
    dec = os.path.join(d, DEC)
    if not os.path.exists(dec):
        open(dec, 'a', encoding='utf-8').close()
        created.append(DEC)
    print(f"review-memory initialised at {d}")
    print("created:", ', '.join(created) if created else "(nothing new)")


# --------------------------------------------------------------------------- #
def cmd_recall(root, args):
    d = mem_dir(root)
    if not os.path.isdir(d):
        print("NO REVIEW MEMORY YET for this repo — first review round, nothing to recall.")
        print("(A .review-memory/ corpus will be created on `record`.)")
        return
    # 1. curated rules
    rules_path = os.path.join(d, RULES)
    if os.path.exists(rules_path):
        body = open(rules_path, encoding='utf-8').read().strip()
        print("=== CURATED RULES (.review-memory/rules.md) ===")
        print(body if body else "(none yet)")
        print()

    decisions = load_decisions(root)
    if not decisions:
        print("=== No recorded decisions yet. ===")
        return

    latest = latest_by_signature(decisions)
    tokens = [t.lower() for t in re.split(r'[\s,]+', args.area or '') if t]

    def relevant(e):
        if not tokens:
            return True
        hay = f"{e.get('file','')} {e.get('signature','')} {e.get('title','')}".lower()
        return any(t in hay for t in tokens)

    suppress = [e for e in latest.values()
                if e.get('dev_resolution') in SUPPRESS and relevant(e)]
    verify = [e for e in latest.values()
              if e.get('dev_resolution') in VERIFY and relevant(e)]

    def fmt(e):
        loc = e.get('file', '')
        if e.get('line'):
            loc += f":{e['line']}"
        who = e.get('reviewer', '?')
        return (f"- [{e.get('severity','?')}] {e.get('title','(untitled)')} "
                f"({loc}) → {e.get('dev_resolution','?').upper()}"
                + (f" — {e['rationale']}" if e.get('rationale') else ""))

    mx = args.max
    if suppress:
        print("=== DO NOT RE-RAISE unless the code materially changed ===")
        print("(author previously resolved / disputed / clarified these)")
        for e in suppress[:mx]:
            print(fmt(e))
        if len(suppress) > mx:
            print(f"  … {len(suppress)-mx} more")
        print()
    if verify:
        print("=== DEFERRED — verify the promised guardrail landed ===")
        for e in verify[:mx]:
            print(fmt(e))
        if len(verify) > mx:
            print(f"  … {len(verify)-mx} more")
        print()
    if not suppress and not verify:
        print("=== No relevant prior decisions for this area. ===")

    # 3. optional semantic recall via graphify (only if a graph has been built)
    graph = os.path.join(d, 'graphify-out', 'graph.json')
    if args.area and has_graphify() and os.path.exists(graph):
        try:
            r = subprocess.run(
                ['graphify', 'query', args.area, '--graph', graph, '--budget', '800'],
                capture_output=True, text=True, timeout=90)
            if r.returncode == 0 and r.stdout.strip():
                print("=== graphify semantic recall ===")
                print(r.stdout.strip()[:2000])
        except Exception:
            pass


# --------------------------------------------------------------------------- #
def cmd_record(root, args):
    payload = json.load(open(args.input, encoding='utf-8'))
    entries = payload.get('entries', [])
    if not entries:
        print("no entries to record")
        return
    common = {k: payload.get(k) for k in ('stack', 'commit', 'date') if payload.get(k)}
    d = mem_dir(root)
    if not os.path.isdir(d):
        cmd_init(root, args)
    path = os.path.join(d, DEC)
    n = 0
    with open(path, 'a', encoding='utf-8') as f:
        for e in entries:
            rec = dict(common)
            rec.update(e)
            if not rec.get('signature'):
                rec['signature'] = derive_signature(rec)
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            n += 1
    print(f"recorded {n} decision(s) -> {path}")

    # Best-effort fast (no-LLM) graphify update so semantic recall stays fresh.
    # The heavier full/LLM build + community detection is a periodic distill task
    # (run the /graphify skill on the folder), not a per-review cost.
    if has_graphify():
        try:
            r = subprocess.run(['graphify', 'update', d],
                               capture_output=True, text=True, timeout=300)
            print("graphify graph updated" if r.returncode == 0
                  else "graphify update skipped (run `/graphify .review-memory` once to build the graph)")
        except Exception as ex:
            print(f"graphify update skipped: {ex}")
    else:
        print("graphify/node not found — JSONL recall still works, semantic recall disabled")


# --------------------------------------------------------------------------- #
def cmd_distill(root, args):
    """Surface recurring signatures as candidate rules for HUMAN promotion."""
    decisions = load_decisions(root)
    if not decisions:
        print("no decisions to distill")
        return
    from collections import defaultdict, Counter
    by_sig = defaultdict(list)
    for d in decisions:
        if d.get('signature'):
            by_sig[d['signature']].append(d)
    rows = []
    for sig, es in by_sig.items():
        res = Counter(e.get('dev_resolution', 'open') for e in es)
        rows.append((len(es), sig, es[-1].get('title', ''), dict(res)))
    rows.sort(reverse=True)
    print("=== DISTILL — recurring findings (candidates for CLAUDE.md/ADR or rules.md) ===")
    print("Review by hand. Promote confirmed lessons into CLAUDE.md / an ADR (authoritative),")
    print("or add a curated bullet to .review-memory/rules.md. Nothing here is applied automatically.\n")
    shown = 0
    for count, sig, title, res in rows:
        if count < args.min_count:
            continue
        print(f"[{count}x] {sig}")
        print(f"      latest: {title}")
        print(f"      resolutions: {res}")
        shown += 1
    if not shown:
        print(f"(no signature seen >= {args.min_count} times yet)")
    if has_graphify():
        print("\nFor a semantic cluster view of recurring themes, build the graph once with")
        print("the /graphify skill on .review-memory, then: graphify cluster-only .review-memory")


# --------------------------------------------------------------------------- #
def cmd_ripe(root, args):
    """Print findings ripe for promotion into CLAUDE.md/ADR.

    A signature is 'ripe' when it recurred >= min-count times AND the developer
    landed on the SAME non-open verdict at least `agree` times — i.e. the team
    keeps giving the same answer, so it should be codified. Machine-friendly
    output (one line per candidate) for the SessionStart hook.
    """
    from collections import defaultdict, Counter
    decisions = load_decisions(root)
    by_sig = defaultdict(list)
    for d in decisions:
        if d.get('signature'):
            by_sig[d['signature']].append(d)
    ripe = []
    for sig, es in by_sig.items():
        res = Counter(e.get('dev_resolution', 'open') for e in es
                      if e.get('dev_resolution') and e['dev_resolution'] != 'open')
        if len(es) >= args.min_count and res:
            verdict, k = res.most_common(1)[0]
            if k >= args.agree:
                ripe.append((len(es), verdict, es[-1].get('title', sig), sig))
    ripe.sort(reverse=True)
    for count, verdict, title, sig in ripe:
        print(f"{count}x {verdict}\t{title}\t{sig}")
    return len(ripe)


# --------------------------------------------------------------------------- #
def cmd_stats(root, _args):
    decisions = load_decisions(root)
    from collections import Counter
    print(f"decisions: {len(decisions)}")
    if decisions:
        print("by resolution:", dict(Counter(d.get('dev_resolution', 'open') for d in decisions)))
        print("by severity:", dict(Counter(d.get('severity', '?') for d in decisions)))
        print("unique signatures:", len({d.get('signature') for d in decisions if d.get('signature')}))
    print("graphify available:", has_graphify())


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('init', 'recall', 'record', 'distill', 'ripe', 'stats'):
        p = sub.add_parser(name)
        p.add_argument('root')
        if name == 'recall':
            p.add_argument('--area', default='')
            p.add_argument('--max', type=int, default=12)
        if name == 'record':
            p.add_argument('--input', required=True)
        if name == 'distill':
            p.add_argument('--min-count', type=int, default=2)
        if name == 'ripe':
            p.add_argument('--min-count', type=int, default=3)
            p.add_argument('--agree', type=int, default=2)
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    {'init': cmd_init, 'recall': cmd_recall, 'record': cmd_record,
     'distill': cmd_distill, 'ripe': cmd_ripe, 'stats': cmd_stats}[args.cmd](root, args)


if __name__ == '__main__':
    main()
