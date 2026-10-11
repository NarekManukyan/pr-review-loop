#!/usr/bin/env python3
"""Re-locate review findings to the line their snippet actually sits on.

Reviewer agents report `file:line` plus a verbatim `snippet`. The line number is
the weak half: it drifts (counted from a hunk header, off by the context lines,
taken from the base side, or simply guessed). The snippet is the strong half —
it is copied from the file. This script trusts the snippet and corrects the line,
deterministically, before anything is posted.

For every finding it:
  1. reads the file at --ref (`git show <ref>:<path>`),
  2. searches for the snippet — consecutive multi-line match first, then a
     substring match on its most distinctive line, then a fuzzy match —
     and picks the candidate nearest the reported line,
  3. rewrites `line` and records how it got there in `relocation`,
  4. when --base is given, classifies the corrected line against the diff hunks
     (`anchor`: added | context | outside | no_diff) so the front-end knows up
     front whether it can post an inline comment or must fall back to an
     MR-level note.

A finding whose snippet is not in the file at all (`relocation: not_found`) is a
strong hint the finding describes code that is not there. It is NOT dropped here
— the fact-check pass (review-filter agent) gets that signal and decides.

Usage:
  relocate-findings.py --repo <dir> --ref <head-sha> [--base <merge-base-sha>] \
      [--in findings.json] [--out relocated.json]

Input: a JSON list of findings, or an object with a "findings" list (other keys
are passed through). Each finding needs `file`; `line` and `snippet` are optional.
Output: the same structure, each finding gaining
  line              corrected line (unchanged when nothing better was found)
  original_line     what the reviewer reported
  relocation        exact | moved | fuzzy | not_found | no_snippet | no_file
  relocation_delta  line - original_line (only when the line changed)
  candidates        number of equally good matches (only when > 1)
  anchor            added | context | outside | no_diff   (only with --base)
  old_line          base-side line for a `context` anchor (post both sides)
A one-line summary goes to stderr. Exit 0 on success, 2 on bad invocation.

Stdlib only.
"""
import argparse
import difflib
import json
import re
import subprocess
import sys

FUZZY_MIN_RATIO = 0.82
# A snippet line shorter than this is too generic to locate on its own
# (`}`, `return;`, `),`) — it can only confirm a multi-line match.
MIN_DISTINCTIVE_LEN = 8
DIFF_CONTEXT = 3  # GitHub and GitLab both render 3 context lines per hunk

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def norm(s):
    """Collapse whitespace so indentation and formatter reflow do not matter."""
    return " ".join(s.split())


def git(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return r.returncode, r.stdout


class Repo:
    def __init__(self, path, ref, base):
        self.path, self.ref, self.base = path, ref, base
        self._files, self._anchors = {}, {}

    def lines(self, file):
        if file not in self._files:
            rc, out = git(self.path, "show", f"{self.ref}:{file}")
            self._files[file] = out.splitlines() if rc == 0 else None
        return self._files[file]

    def anchors(self, file):
        """new-side line -> ('added', None) | ('context', old_line) for every line
        inside a hunk. Context lines need both sides to anchor on GitHub/GitLab."""
        if file not in self._anchors:
            rc, out = git(self.path, "diff", "--no-ext-diff", "--no-color",
                          f"--unified={DIFF_CONTEXT}", self.base, self.ref, "--", file)
            table = {}
            old_line = new_line = None
            for row in out.splitlines() if rc == 0 else []:
                m = _HUNK_RE.match(row)
                if m:
                    old_line, new_line = int(m.group(1)), int(m.group(2))
                    continue
                if new_line is None or row.startswith(("---", "+++", "\\")):
                    continue
                if row.startswith("+"):
                    table[new_line] = ("added", None)
                    new_line += 1
                elif row.startswith("-"):
                    old_line += 1
                elif row.startswith(" "):
                    table[new_line] = ("context", old_line)
                    old_line += 1
                    new_line += 1
            self._anchors[file] = table
        return self._anchors[file]


def snippet_lines(snippet):
    if not snippet or not isinstance(snippet, str):
        return []
    return [norm(s) for s in snippet.splitlines() if norm(s)]


def nearest(cands, target):
    """Candidates are 1-based line numbers; prefer the one closest to target."""
    if target is None:
        return min(cands)
    return min(cands, key=lambda c: (abs(c - target), c))


def find_block(file_norm, snip):
    """1-based start lines where every snippet line appears consecutively
    (blank file lines are skipped, matching how snippets drop them)."""
    idx = [i for i, s in enumerate(file_norm) if s]
    dense = [file_norm[i] for i in idx]
    n = len(snip)
    starts = []
    for k in range(len(dense) - n + 1):
        if dense[k:k + n] == snip:
            starts.append((idx[k] + 1, idx[k + n - 1] + 1))
    return starts


def locate(file_lines, snip, claimed):
    """Return (line, relocation, n_candidates)."""
    file_norm = [norm(s) for s in file_lines]
    key = max(snip, key=len)

    # 0. a generic snippet (`}`, `return;`) can confirm the reported line but is
    #    never evidence for moving it — it matches dozens of lines
    if len(snip) == 1 and len(key) < MIN_DISTINCTIVE_LEN:
        if claimed is not None and 1 <= claimed <= len(file_norm) \
                and key in file_norm[claimed - 1]:
            return claimed, "exact", 1
        return claimed, "not_found", 0

    # 1. a multi-line snippet, consecutive
    blocks = find_block(file_norm, snip) if len(snip) > 1 else []
    if blocks:
        # a claimed line anywhere inside a matching block is already correct
        for start, end in blocks:
            if claimed is not None and start <= claimed <= end:
                return claimed, "exact", len(blocks)
        best = nearest([s for s, _ in blocks], claimed)
        return best, ("exact" if best == claimed else "moved"), len(blocks)

    # 2. the most distinctive line, as a substring — a whole-line match and a
    #    fragment of a longer line are equal evidence, so the nearest one wins
    if len(key) >= MIN_DISTINCTIVE_LEN:
        hits = [i + 1 for i, s in enumerate(file_norm) if key in s]
        if hits:
            best = nearest(hits, claimed)
            return best, ("exact" if best == claimed else "moved"), len(hits)

        # 3. fuzzy — the reviewer paraphrased or the formatter reflowed the line
        scored = []
        for i, s in enumerate(file_norm):
            if not s:
                continue
            r = difflib.SequenceMatcher(None, key, s).ratio()
            if r >= FUZZY_MIN_RATIO:
                scored.append((r, i + 1))
        if scored:
            top = max(r for r, _ in scored)
            hits = [ln for r, ln in scored if r == top]
            return nearest(hits, claimed), "fuzzy", len(hits)

    return claimed, "not_found", 0


def relocate(finding, repo):
    f = dict(finding)
    path = f.get("file")
    claimed = f.get("line")
    try:
        claimed = int(claimed) if claimed is not None else None
    except (TypeError, ValueError):
        claimed = None
    f["original_line"] = claimed

    lines = repo.lines(path) if path else None
    if lines is None:
        f["relocation"] = "no_file"
    else:
        snip = snippet_lines(f.get("snippet"))
        if not snip:
            f["relocation"] = "no_snippet"
        else:
            line, how, n = locate(lines, snip, claimed)
            f["line"], f["relocation"] = line, how
            if n > 1:
                f["candidates"] = n
            if claimed is not None and line is not None and line != claimed:
                f["relocation_delta"] = line - claimed

    if repo.base and path:
        table = repo.anchors(path)
        line = f.get("line")
        if not table:
            f["anchor"] = "no_diff"
        else:
            kind, old = table.get(line, ("outside", None)) if isinstance(line, int) \
                else ("outside", None)
            f["anchor"] = kind
            if old is not None:
                f["old_line"] = old
    return f


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--ref", required=True, help="head commit the findings describe")
    ap.add_argument("--base", help="merge-base; enables the `anchor` classification")
    ap.add_argument("--in", dest="inp", help="findings JSON (default stdin)")
    ap.add_argument("--out", help="output path (default stdout)")
    a = ap.parse_args(argv)

    rc, _ = git(a.repo, "rev-parse", "--verify", "--quiet", f"{a.ref}^{{commit}}")
    if rc != 0:
        print(f"relocate-findings: unknown ref {a.ref!r} in {a.repo}", file=sys.stderr)
        return 2

    if a.inp:
        with open(a.inp) as fh:
            doc = json.load(fh)
    else:
        doc = json.load(sys.stdin)
    findings = doc if isinstance(doc, list) else doc.get("findings", [])
    repo = Repo(a.repo, a.ref, a.base)
    out = [relocate(x, repo) for x in findings]

    result = out if isinstance(doc, list) else {**doc, "findings": out}
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if a.out:
        with open(a.out, "w") as fh:
            fh.write(text + "\n")
    else:
        print(text)

    counts = {}
    for x in out:
        counts[x["relocation"]] = counts.get(x["relocation"], 0) + 1
    moved = sum(1 for x in out if "relocation_delta" in x)
    summary = " · ".join(f"{k} {v}" for k, v in sorted(counts.items()))
    tail = ""
    if a.base:
        inline = sum(1 for x in out if x.get("anchor") in ("added", "context"))
        tail = f" · inline-anchorable {inline}/{len(out)}"
    print(f"relocate-findings: {len(out)} findings · {summary} · lines corrected {moved}{tail}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
