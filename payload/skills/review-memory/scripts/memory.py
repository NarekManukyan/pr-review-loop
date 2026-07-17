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
CONFIG = 'config.json'

# Per-repo config defaults. Override in .review-memory/config.json (committed).
CONFIG_DEFAULTS = {
    'stack': '',                       # e.g. flutter-bloc; '' -> auto-detect
    'cycle_cap': 3,                    # max PRs a watch cycle handles
    'watch_channel': '',               # default Slack channel for the watcher
    'reactions': {                     # Slack state emojis (short names, no colons)
        'in_review': 'eyes',
        'approved': 'white_check_mark',
        'changes': 'wrench',
    },
    'generated_globs': [],             # extra generated-file globs to skip (beyond CLAUDE.md)
    'review_pr_command': '/review-pr', # command the PR watcher drives
}

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
    return shutil.which('graphify') is not None


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
def cmd_note(root, args):
    """Add a sticky human WATCH ITEM — a carry-forward directive for reviewers.

    Unlike a bot finding, a watch item is authored by a human ("this complex
    logic wasn't verified — check it in future PRs"), tagged to a file/area, and
    surfaces in EVERY future review touching that area until someone closes it
    (record/note the same signature with a non-open resolution). It never
    auto-closes just because the bot didn't re-raise it.
    """
    d = mem_dir(root)
    if not os.path.isdir(d):
        cmd_init(root, args)
    file_ = args.file or (args.area.split()[0] if args.area else '')
    rec = {
        'kind': 'watch',
        'by': args.by,
        'date': args.date or '',
        'area': args.area,
        'file': file_,
        'line': args.line,
        'severity': args.severity,
        'title': args.title or (args.text[:60] if args.text else 'watch item'),
        'text': args.text,
        'dev_resolution': 'open',
        'reviewer': 'human',
    }
    if not rec.get('signature'):
        rec['signature'] = 'watch/' + slug(rec['title'], 8) + '|' + slug(os.path.basename(file_), 3)
    with open(os.path.join(d, DEC), 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    print(f"watch item added ({rec['signature']}). It will surface in every future "
          f"review whose --area matches, until closed.")


def cmd_close(root, args):
    """Mark a watch item (or finding) checked — record a closing entry."""
    d = mem_dir(root)
    rec = {'kind': 'watch', 'signature': args.signature, 'date': args.date or '',
           'by': args.by, 'dev_resolution': args.resolution,
           'rationale': args.note or 'checked', 'reviewer': 'human',
           'title': args.signature}
    with open(os.path.join(d, DEC), 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    print(f"closed {args.signature} as {args.resolution}")


# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Relevance for `recall`.
#
# These records are keyed by FILE and carry developer state (disputed/deferred/…),
# so recall is a lookup — "what did we already decide about these files" — not a
# similarity search. A wrong match here can SUPPRESS a real finding, so matching
# is deliberately strict and path-anchored.
#
# The old filter was `any(token in haystack)` over every field, which made any
# area string containing a common word select the whole corpus (on a real repo:
# 'dart' matched 54/54 decisions, 'lib' 52/54) — i.e. no filter at all.

# A token matching more than this share of the corpus carries no signal — let the
# corpus decide what's generic instead of hardcoding a stoplist that rots. This
# applies to path segments too: 'lib', 'view', 'mobx' are structural in one repo
# and discriminating in another, so measure rather than assume.
GENERIC_DF = 0.5


def _hay(e):
    return (f"{e.get('file','')} {e.get('area','')} {e.get('signature','')} "
            f"{e.get('title','')} {e.get('text','')}").lower()


def _segments(p):
    return [s for s in re.split(r'[/\\]', (p or '').lower()) if s]


def make_relevant(decisions, area, loose=False):
    """-> predicate(decision) -> bool, for an `--area` string.

    Strict mode (suppress/verify): a decision matches when its file shares a
    NON-generic path segment with the area, or when an informative (low document
    frequency) keyword hits. Loose mode (watch items): the old any-token match.
    """
    tokens = [t.lower() for t in re.split(r'[\s,]+', area or '') if t]
    if not tokens:
        return lambda e: True
    if loose:
        return lambda e: any(t in _hay(e) for t in tokens)

    paths = [t for t in tokens if '/' in t or re.search(r'\.\w{1,5}$', t)]
    words = [t for t in tokens if t not in paths]

    n = len(decisions) or 1
    cutoff = GENERIC_DF * n

    # Drop keywords that select most of the corpus — they discriminate nothing.
    hays = [_hay(e) for e in decisions]
    words = [w for w in words if sum(1 for h in hays if w in h) <= cutoff]

    # Same treatment for path segments, measured against the files on record:
    # a segment like 'view' or 'lib' that appears in most files selects nothing.
    file_segs = [set(_segments(e.get('file'))) for e in decisions]
    qsegs = {s for p in paths for s in _segments(p)}
    qsegs = {s for s in qsegs if sum(1 for fs in file_segs if s in fs) <= cutoff}

    # Nothing discriminating survived — fall back to showing everything rather
    # than silently hiding memory the reviewer needs.
    if not qsegs and not words:
        return lambda e: True

    def relevant(e):
        if qsegs and (set(_segments(e.get('file'))) & qsegs):
            return True
        return bool(words) and any(w in _hay(e) for w in words)

    return relevant


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
    relevant = make_relevant(list(latest.values()), args.area)
    loose = make_relevant(list(latest.values()), args.area, loose=True)

    # Sticky human watch items — surface FIRST, always, until explicitly closed.
    # Deliberately LOOSE: a human flagged these, so a stray extra line costs far
    # less than silently dropping one the reviewer was told to inspect.
    watch = [e for e in latest.values()
             if e.get('kind') == 'watch' and e.get('dev_resolution') == 'open' and loose(e)]
    suppress = [e for e in latest.values()
                if e.get('kind') != 'watch' and e.get('dev_resolution') in SUPPRESS and relevant(e)]
    verify = [e for e in latest.values()
              if e.get('kind') != 'watch' and e.get('dev_resolution') in VERIFY and relevant(e)]

    if watch:
        print("=== ⚠ CARRY-FORWARD WATCH ITEMS — a human flagged these; inspect this round ===")
        for e in watch:
            loc = e.get('file', '') + (f":{e['line']}" if e.get('line') else '')
            by = e.get('by') or 'reviewer'
            print(f"- [{e.get('severity','')}] {e.get('title','')} ({loc}) — flagged by {by}")
            if e.get('text'):
                print(f"    {e['text']}")
            print(f"    (still open; close with: memory.py close . --signature '{e.get('signature')}' --resolution clarified)")
        print()

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
    if not watch and not suppress and not verify:
        print("=== No relevant prior decisions or watch items for this area. ===")

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
        print("graphify not found — JSONL recall still works, semantic recall disabled")


# --------------------------------------------------------------------------- #
def cmd_mark_reviewed(root, args):
    """Record that a PR was reviewed at a given commit (watcher dedup state)."""
    d = mem_dir(root)
    if not os.path.isdir(d):
        cmd_init(root, args)
    rec = {'kind': 'review-run', 'pr': str(args.pr), 'commit': args.commit,
           'round': args.round, 'date': args.date or ''}
    with open(os.path.join(d, DEC), 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    print(f"marked PR {args.pr} reviewed at {args.commit[:10]}")


def cmd_was_reviewed(root, args):
    """Exit 0 if PR was already reviewed at this commit, else exit 1.

    Lets a watcher skip PRs it has already handled — so it only re-reviews when
    the head advances (new commits) or a re-request produces a fresh commit.
    """
    want_pr, want_commit = str(args.pr), args.commit
    for e in load_decisions(root):
        if (e.get('kind') == 'review-run' and str(e.get('pr')) == want_pr
                and e.get('commit') == want_commit):
            print("yes")
            return
    print("no")
    sys.exit(1)


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
def load_config(root):
    """Config defaults deep-merged with .review-memory/config.json (if present)."""
    import copy
    cfg = copy.deepcopy(CONFIG_DEFAULTS)
    p = os.path.join(mem_dir(root), CONFIG)
    if os.path.exists(p):
        try:
            user = json.load(open(p, encoding='utf-8'))
            for k, v in user.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
        except Exception as e:
            print(f"config.json ignored ({e})", file=sys.stderr)
    return cfg


def cmd_config(root, args):
    cfg = load_config(root)
    if args.init:
        d = mem_dir(root)
        if not os.path.isdir(d):
            cmd_init(root, args)
        p = os.path.join(d, CONFIG)
        if os.path.exists(p):
            print(f"config already exists: {p}")
        else:
            json.dump(CONFIG_DEFAULTS, open(p, 'w', encoding='utf-8'), indent=2)
            open(p, 'a').write('\n')
            print(f"wrote default config -> {p} (edit + commit it)")
        return
    if args.get:
        v = cfg
        for k in args.get.split('.'):
            v = v.get(k) if isinstance(v, dict) else None
        print('' if v is None else (json.dumps(v) if isinstance(v, (dict, list)) else v))
        return
    print(json.dumps(cfg, indent=2, ensure_ascii=False))


def cmd_health(root, _args):
    """Review-health report: volume, precision (dispute rate), open debt."""
    from collections import Counter, defaultdict
    decisions = load_decisions(root)
    findings = [d for d in decisions if d.get('kind') not in ('review-run', 'watch')]
    runs = [d for d in decisions if d.get('kind') == 'review-run']
    watches = [d for d in decisions if d.get('kind') == 'watch']

    print("=== Review health ===")
    print(f"review runs recorded: {len(runs)}   findings logged: {len(findings)}")
    if runs:
        per_pr = Counter(str(r.get('pr')) for r in runs)
        print(f"PRs reviewed: {len(per_pr)}   max rounds on one PR: {max(per_pr.values())}")

    latest = latest_by_signature(findings)
    res = Counter(e.get('dev_resolution', 'open') for e in latest.values())
    print("\nfinding outcomes (latest per finding):", dict(res))

    # precision proxy: dispute rate per category (disputed / resolved-in-some-way)
    print("\nprecision by category (lower dispute rate = more trusted):")
    by_cat = defaultdict(lambda: Counter())
    for e in latest.values():
        r = e.get('dev_resolution', 'open')
        if r != 'open':
            by_cat[e.get('category', '?')][r] += 1
    if not by_cat:
        print("  (no developer responses yet)")
    for cat, c in sorted(by_cat.items()):
        total = sum(c.values())
        disputed = c.get('disputed', 0) + c.get('clarified', 0)
        rate = round(100 * disputed / total) if total else 0
        flag = '  <-- often wrong, consider down-weighting' if rate >= 50 and total >= 3 else ''
        print(f"  {cat}: {disputed}/{total} disputed/withdrawn ({rate}%){flag}")

    # open debt
    watch_open = sum(1 for w in latest_by_signature(watches).values()
                     if w.get('dev_resolution') == 'open')
    deferred_open = sum(1 for e in latest.values() if e.get('dev_resolution') == 'deferred')
    print(f"\nopen watch items: {watch_open}   deferred-not-closed: {deferred_open}")
    print("graphify available:", has_graphify())


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
    for name in ('init', 'recall', 'record', 'note', 'close',
                 'mark-reviewed', 'was-reviewed', 'config', 'health',
                 'distill', 'ripe', 'stats'):
        p = sub.add_parser(name)
        p.add_argument('root')
        if name == 'config':
            p.add_argument('--init', action='store_true', help='write a default config.json')
            p.add_argument('--get', default='', help='print one key (dot-path, e.g. reactions.approved)')
        if name in ('mark-reviewed', 'was-reviewed'):
            p.add_argument('--pr', required=True)
            p.add_argument('--commit', required=True)
            if name == 'mark-reviewed':
                p.add_argument('--round', type=int, default=1)
                p.add_argument('--date', default='')
        if name == 'recall':
            p.add_argument('--area', default='')
            p.add_argument('--max', type=int, default=12)
        if name == 'record':
            p.add_argument('--input', required=True)
        if name == 'note':
            p.add_argument('--text', required=True, help='what to watch and why')
            p.add_argument('--area', default='', help='file path(s) / feature keywords it applies to')
            p.add_argument('--file', default='')
            p.add_argument('--line', type=int, default=None)
            p.add_argument('--title', default='')
            p.add_argument('--by', default='')
            p.add_argument('--severity', default='P1')
            p.add_argument('--date', default='')
        if name == 'close':
            p.add_argument('--signature', required=True)
            p.add_argument('--resolution', default='clarified',
                           choices=['resolved', 'clarified', 'disputed', 'deferred'])
            p.add_argument('--note', default='')
            p.add_argument('--by', default='')
            p.add_argument('--date', default='')
        if name == 'distill':
            p.add_argument('--min-count', type=int, default=2)
        if name == 'ripe':
            p.add_argument('--min-count', type=int, default=3)
            p.add_argument('--agree', type=int, default=2)
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    {'init': cmd_init, 'recall': cmd_recall, 'record': cmd_record,
     'note': cmd_note, 'close': cmd_close,
     'mark-reviewed': cmd_mark_reviewed, 'was-reviewed': cmd_was_reviewed,
     'config': cmd_config, 'health': cmd_health,
     'distill': cmd_distill, 'ripe': cmd_ripe, 'stats': cmd_stats}[args.cmd](root, args)


if __name__ == '__main__':
    main()
