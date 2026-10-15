#!/usr/bin/env python3
"""Build one context packet per reviewer seat before the panel starts.

Measured on a real panel: every seat spent 17-51 turns fetching the diff, the
changed files and the engine docs one tool call at a time, re-sending its whole
growing context (12k -> 80-130k) on every turn. Cost is turns x context, so the
reads, not the reasoning, were the bill. This script does those reads once, in
code, and writes them to files a seat can load in a single turn.

  build-packets.py --repo <dir> --base <sha> --head <sha> --out <dir> \
      [--pack lenses/_base-flutter.md --pack lenses/flutter-mobx.md] \
      [--seats A,B,C,E] [--budget-kb 240]

Writes into --out:
  common-01.md … common-NN.md   identical for every seat: snapshot, repo rules,
                                ADR index, likely reads, diff, full changed
                                files with line numbers (each file <= ~60 KB so
                                one Read call takes it whole)
  seat-<X>.md                   that seat's persona + the universal lenses it
                                owns + the stack-pack sections tagged for it
  manifest.json                 file list, sizes, what was not inlined and why
A one-line summary goes to stderr. Stdlib only.
"""
import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys


def read(path, **kw):
    with open(path, **kw) as fh:
        return fh.read()

HERE = os.path.dirname(os.path.abspath(__file__))
REFS = os.path.join(HERE, "..", "references")
CHUNK_BYTES = 60_000          # keep each file under the Read tool's per-call cap
MAX_FILE_LINES = 800          # longer files only ever get their changed regions
DEFAULT_GENERATED = [
    "*.g.dart", "*.freezed.dart", "*.gen.dart", "*.tailor.dart", "*.config.dart",
    "*.gr.dart", "*.chopper.dart", "*.mocks.dart", "lib/gen/*", "*.pb.dart",
    "*.pb.go", "*_gen.go", "wire_gen.go", "vendor/*", "node_modules/*", "dist/*",
    "*.lock", "pubspec.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "go.sum", "*.min.js", "*.svg", "*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp",
    "*.ttf", "*.otf", "*.riv", "*.lottie",
]
# lenses each persona owns (personas.md); a pack section tagged with a seat letter
# or with one of these lens ids goes to that seat
OWNED = {
    "A": {"U2", "U6", "U8"},
    "B": {"U1", "U3", "U4", "U7", "U9", "U12"},
    "C": {"U8", "U11"},
    "E": {"U3", "U5", "U13", "U14"},
}
SYMBOL_RE = [
    re.compile(r"^\+\s*(?:abstract\s+|sealed\s+|final\s+|base\s+)*(?:class|mixin|enum|extension|typedef)\s+([A-Z]\w+)"),
    re.compile(r"^\+\s*(?:export\s+)?(?:default\s+)?(?:class|interface|type|enum|function|const)\s+([A-Za-z_]\w{3,})"),
    re.compile(r"^\+func\s+(?:\([^)]*\)\s+)?([A-Z]\w+)"),
    re.compile(r"^\+type\s+([A-Z]\w+)"),
    re.compile(r"^\+\s*(?:async\s+)?def\s+([a-zA-Z_]\w{3,})|^\+\s*class\s+([A-Z]\w+)"),
]
ROOT_PATTERNS = ["configureDependencies", "GetIt.instance", "registerLazySingleton",
                 "@InjectableInit", "@Module(", "NestFactory.create", "func main()",
                 "wire.Build(", "runApp("]


def git(repo, *args, check=False):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f"build-packets: git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def generated_globs(packs):
    globs = list(DEFAULT_GENERATED)
    for p in packs:
        text = read(p)
        m = re.search(r"## Generated / skip\n(.*?)(?:\n## |\Z)", text, re.S)
        if m:
            globs += re.findall(r"`([^`]+)`", m.group(1))
    return globs


def is_generated(path, globs):
    base = os.path.basename(path)
    return any(fnmatch.fnmatch(path, g) or fnmatch.fnmatch(base, g) for g in globs)


def annotated(repo, base, head, path, context):
    """One view per file: head-side line numbers, `+` added, `-` removed (no number).
    context=None renders the whole file; otherwise that many lines around each hunk."""
    unified = "--unified=100000" if context is None else f"--unified={context}"
    out = git(repo, "diff", "--no-color", "--no-ext-diff", unified, base, head, "--", path)
    rows, new = [], 0
    for line in out.splitlines():
        m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
        if m:
            if rows and context is not None:
                rows.append("     ⋮")
            new = int(m.group(1))
            continue
        if new == 0 or line.startswith(("diff --git", "index ", "--- ", "+++ ", "new file", "deleted file", "\\")):
            continue
        if line.startswith("+"):
            rows.append(f"{new:>5} + {line[1:]}")
            new += 1
        elif line.startswith("-"):
            rows.append(f"      - {line[1:]}")
        else:
            rows.append(f"{new:>5}   {line[1:]}")
            new += 1
    return "\n".join(rows)


def file_block(repo, base, head, path, status, whole):
    lang = os.path.splitext(path)[1].lstrip(".") or "text"
    if status == "D":
        return f"### `{path}` — deleted\n```{lang}\n{annotated(repo, base, head, path, 3)}\n```\n"
    label = "whole file" if whole else "changed regions ±5 lines — Read the file for more"
    body = annotated(repo, base, head, path, None if whole else 5)
    return f"### `{path}` ({label})\n```{lang}\n{body}\n```\n"


def repo_rules(repo):
    out = []
    for name in ("AGENTS.md", "CLAUDE.md"):
        p = os.path.join(repo, name)
        if os.path.isfile(p):
            body = read(p, errors="replace")
            if name == "CLAUDE.md" and out:
                # a generated adapter that mirrors AGENTS.md adds nothing but tokens
                agents = set(l.strip() for l in out[0].splitlines() if len(l.strip()) > 20)
                mine = [l.strip() for l in body.splitlines() if len(l.strip()) > 20]
                if mine and sum(l in agents for l in mine) / len(mine) > 0.6:
                    out.append("_`CLAUDE.md` mirrors `AGENTS.md` — not repeated._\n")
                    continue
            out.append(f"### `{name}`\n{body[:40_000]}\n")
    adrs = []
    for d in ("docs/adr", "docs/adrs", "docs/decisions", "adr"):
        full = os.path.join(repo, d)
        if not os.path.isdir(full):
            continue
        for f in sorted(os.listdir(full)):
            if not f.endswith(".md"):
                continue
            first = ""
            with open(os.path.join(full, f), errors="replace") as fh:
                for line in fh:
                    if line.strip():
                        first = line.strip().lstrip("# ").strip()
                        break
            adrs.append(f"- `{d}/{f}` — {first}")
    if adrs:
        out.append("### ADR index — open the ones a finding depends on and cite them\n"
                   + "\n".join(adrs) + "\n")
    return "\n".join(out) or "_No AGENTS.md / CLAUDE.md / ADRs found._\n"


def likely_reads(repo, head, changed, diff_text):
    """Pointers, not content: where the seams probably are."""
    changed_set = set(changed)
    symbols = []
    for line in diff_text.splitlines():
        for rx in SYMBOL_RE:
            m = rx.match(line)
            if m:
                name = next(g for g in m.groups() if g)
                if name not in symbols:
                    symbols.append(name)
                break
    out = []
    for name in symbols[:25]:
        hits = git(repo, "grep", "-l", "-w", "-I", name, head, "--").splitlines()
        hits = [h.split(":", 1)[1] for h in hits if ":" in h]
        users = [h for h in hits if h not in changed_set]
        if users:
            shown = ", ".join(f"`{u}`" for u in users[:5])
            more = f" (+{len(users) - 5} more)" if len(users) > 5 else ""
            out.append(f"- `{name}` is also used in {shown}{more}")
        else:
            out.append(f"- `{name}` — no use outside this diff (check it is wired: U5)")
    sib = []
    tree = git(repo, "ls-tree", "-r", "--name-only", head).splitlines()
    by_dir = {}
    for p in tree:
        by_dir.setdefault(os.path.dirname(p), []).append(p)
    for path in changed:
        stem = os.path.basename(path)
        m = re.search(r"(_[a-z]+(?:_[a-z]+)?\.\w+)$", stem)
        if not m:
            continue
        suffix = m.group(1)
        peers = [p for p in by_dir.get(os.path.dirname(path), [])
                 if p.endswith(suffix) and p != path and p not in changed_set][:3]
        if peers:
            sib.append(f"- `{path}` — siblings: " + ", ".join(f"`{p}`" for p in peers))
    roots = []
    for pat in ROOT_PATTERNS:
        for h in git(repo, "grep", "-l", "-F", "-I", pat, head, "--").splitlines()[:3]:
            p = h.split(":", 1)[1]
            if p not in roots and "test" not in p:
                roots.append(p)
    text = "### New or changed symbols and where else they are used\n" + ("\n".join(out) or "_none detected_")
    text += "\n\n### Siblings of changed files (same folder, same kind — U13)\n" + ("\n".join(sib) or "_none_")
    text += "\n\n### Composition roots / DI registration (U5/U14)\n" + (
        "\n".join(f"- `{r}`" for r in roots[:8]) or "_none detected_")
    return text + "\n"


def sections(text, level="## "):
    """Split markdown into (heading, body) at the given heading level."""
    out, cur, buf = [], None, []
    for line in text.splitlines(keepends=True):
        if line.startswith(level) and not line.startswith(level + "#"):
            out.append((cur, "".join(buf)))
            cur, buf = line.strip(), [line]
        else:
            buf.append(line)
    out.append((cur, "".join(buf)))
    return out


REUSE_MARK = "[reuse]"   # a pack section tagged with this is dropped when --reuse off


def seat_text(seat, packs, reuse=True):
    personas = read(os.path.join(REFS, "personas.md"))
    parts = [f"# Your seat: Reviewer {seat}\n"]
    for head, body in sections(personas):
        if head and head.startswith(f"## Reviewer {seat} "):
            parts.append(body)
    owned = OWNED.get(seat, set())
    uni = read(os.path.join(REFS, "universal-lenses.md"))
    parts.append("\n## Universal lenses you own\n")
    for head, body in sections(uni):
        m = re.match(r"## (U\d+) ", head or "")
        if m and m.group(1) in owned:
            parts.append(body)
    for p in packs:
        text = read(p)
        title = os.path.basename(p)
        picked = []
        for head, body in sections(text, "### "):
            m = re.search(r"\(maps ([^)]*)\)", head or "")
            if not m:
                continue
            tags = set(re.findall(r"U\d+|\b[A-F]\b", m.group(1)))
            if not reuse and REUSE_MARK in (head or ""):
                continue
            if seat in tags or tags & owned:
                picked.append(body)
        if picked:
            parts.append(f"\n## From the `{title}` stack pack\n" + "".join(picked))
    return "".join(parts)


REUSE_CATALOG = "reuse-catalog.md"
# a new class (private ones too), mixin, extension or top-level function
NEW_SYMBOL_RE = re.compile(
    r"^\+(?:\s*(?:abstract|sealed|final|base)\s+)*(?:class|mixin|extension)\s+_?[A-Za-z]"
    r"|^\+[A-Za-z_][\w<>?, ]*\s+_?[a-z]\w*\([^;]*\)\s*(?:\{|=>|async)")


def reuse_catalog(a, diff):
    """Write the catalog of existing code (at the merge-base) for seat C.

    Returns "on", "off" (flag) or "skipped" (the diff adds no class or function, so
    there is nothing to compare — a merge-only re-check costs nothing)."""
    if a.reuse == "off":
        return "off"
    adds = [l for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
    if not any(NEW_SYMBOL_RE.search(l) for l in adds):
        return "skipped"
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reuse-catalog.py")
    out = subprocess.run(["python3", script, a.repo, a.base], capture_output=True, text=True).stdout
    if not out.strip():
        return "skipped"   # no catalog for this stack
    with open(os.path.join(a.out, REUSE_CATALOG), "w") as f:
        f.write(out)
    return "on"


def common_rules():
    personas = read(os.path.join(REFS, "personas.md"))
    keep = []
    for head, body in sections(personas):
        if head is None or head.startswith("## Reading the code") or head.startswith("## House conventions"):
            keep.append(body)
    return "".join(keep)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pack", action="append", default=[], help="stack lens file (repeatable)")
    ap.add_argument("--seats", default="A,B,C,E")
    ap.add_argument("--reuse", choices=["on", "off"], default="on",
                    help="reuse-before-build check: catalog of existing code for seat C")
    ap.add_argument("--budget-kb", type=int, default=160,
                    help="budget for upgrading files from changed regions to whole-file views")
    a = ap.parse_args(argv)
    packs = [p if os.path.isabs(p) else os.path.join(REFS, p) for p in a.pack]
    git(a.repo, "rev-parse", "--verify", f"{a.head}^{{commit}}", check=True)
    os.makedirs(a.out, exist_ok=True)
    for f in os.listdir(a.out):
        if f.startswith(("common-", "seat-")) or f in ("manifest.json", REUSE_CATALOG):
            os.remove(os.path.join(a.out, f))

    globs = generated_globs(packs)
    rows = [l.split("\t") for l in git(a.repo, "diff", "--name-status", "--no-renames",
                                         a.base, a.head).splitlines() if l]
    changed = [(r[0][0], r[-1]) for r in rows]
    reviewable = [(s, p) for s, p in changed if not is_generated(p, globs)]
    skipped = [{"path": p, "reason": "generated / binary (pack skip list)"}
               for s, p in changed if is_generated(p, globs)]
    paths = [p for _, p in reviewable]
    diff = git(a.repo, "diff", "--no-color", "--unified=0", a.base, a.head, "--", *paths) if paths else ""

    head_blocks = [
        f"# Review packet — read every common-*.md file and your seat-*.md file in ONE turn\n\n"
        f"Snapshot: head `{a.head}`, merge-base `{a.base}`. Line numbers below are head-side "
        f"and exact — cite them as shown.\n\n"
        f"Changed files: {len(changed)} · reviewable: {len(reviewable)} · "
        f"generated/binary skipped: {len(skipped)}\n",
        "## How to work (cost rule)\n"
        "Everything you need for the changed code is in this packet. A turn re-sends your whole "
        "context, so: after reading the packet, do **at most two more turns of reads, and put "
        "every read for a turn in that one turn** (parallel tool calls). Use the likely-reads "
        "list below for seams. Stop at 15 tool calls in total and return what you have.\n",
        "## Engine rules shared by every seat\n" + common_rules(),
        "## Repo rules\n" + repo_rules(a.repo),
        "## Likely reads outside the diff\n" + likely_reads(a.repo, a.head, paths, diff),
    ]
    # Every file gets its changed regions. Then, source before tests and smallest
    # first, upgrade files to the whole-file view while the budget lasts — the
    # design-system / dead-code sweeps and complexity checks need the whole file.
    budget = a.budget_kb * 1024
    blocks = {p: file_block(a.repo, a.base, a.head, p, st, whole=False) for st, p in reviewable}
    used = sum(len(b) for b in blocks.values())
    status = dict((p, st) for st, p in reviewable)
    is_test = lambda p: bool(re.search(r"(^|/)(test|tests|__tests__|spec)/|_test\.|\.test\.|\.spec\.", p))
    order = sorted(paths, key=lambda p: (is_test(p), len(git(a.repo, "show", f"{a.head}:{p}")) if status[p] != "D" else 0))
    whole_files = []
    for p in order:
        if status[p] == "D":
            continue
        lines = git(a.repo, "show", f"{a.head}:{p}").count("\n")
        if lines > MAX_FILE_LINES:
            continue
        full = file_block(a.repo, a.base, a.head, p, status[p], whole=True)
        if used - len(blocks[p]) + len(full) <= budget:
            used += len(full) - len(blocks[p])
            blocks[p] = full
            whole_files.append(p)
    not_inlined = [{"path": p, "reason": "only changed regions inlined (budget or size)"}
                   for p in paths if p not in whole_files and status[p] != "D"]
    file_blocks = [blocks[p] for p in paths]
    if skipped:
        file_blocks.append("### Skipped as generated / binary\n"
                           + "\n".join(f"- `{x['path']}`" for x in skipped) + "\n")

    # chunk: whole blocks, never split a file across chunks unless it alone is too big
    chunks, cur = [], ""
    legend = ("## Changed files\n`  123 + code` added at head line 123 · `  124   code` unchanged · "
              "`      - code` removed (base only) · `⋮` lines omitted\n")
    for block in head_blocks + [legend] + file_blocks:
        while len(block) > CHUNK_BYTES:
            cut = block.rfind("\n", 0, CHUNK_BYTES)
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(block[:cut] + "\n")
            block = block[cut + 1:]
        if len(cur) + len(block) > CHUNK_BYTES and cur:
            chunks.append(cur)
            cur = ""
        cur += block + "\n"
    if cur:
        chunks.append(cur)
    names = []
    for i, c in enumerate(chunks, 1):
        name = f"common-{i:02d}.md"
        with open(os.path.join(a.out, name), "w") as f:
            f.write(c)
        names.append(name)
    seats = [s.strip() for s in a.seats.split(",") if s.strip()]
    reuse = reuse_catalog(a, diff) if "C" in seats else "off"
    for s in seats:
        with open(os.path.join(a.out, f"seat-{s}.md"), "w") as f:
            f.write(seat_text(s, packs, reuse=reuse == "on"))
            if s == "C" and reuse == "on":
                f.write(f"\n## Reuse catalog\nRead `{REUSE_CATALOG}` (next to this file) in your "
                        "first turn, with the packet. Check every class and function the diff adds "
                        "against it — see the pack's reuse lens.\n")
    total = sum(os.path.getsize(os.path.join(a.out, n)) for n in names)
    manifest = {"head": a.head, "base": a.base, "common": names,
                "seats": {s: f"seat-{s}.md" for s in seats},
                "common_kb": round(total / 1024), "approx_tokens": round(total / 3.6),
                "reuse": reuse,
                "reviewable": paths, "whole_files": len(whole_files),
                "regions_only": not_inlined, "skipped": skipped}
    with open(os.path.join(a.out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    print(f"build-packets: {len(paths)} files · {len(names)} common parts · "
          f"~{manifest['approx_tokens'] // 1000}k tokens shared · seats {','.join(seats)} · "
          f"whole files {len(whole_files)}/{len(paths)} · skipped {len(skipped)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
