#!/usr/bin/env python3
"""Reuse catalog for a Flutter repo: what already exists, so a reviewer can tell
a new private widget, helper or use case that copies it.

Usage: reuse-catalog.py <repo> [ref]   (ref defaults to origin/develop, then HEAD)

Reads the ref with `git grep`, so it never depends on the checked-out tree.
Prints markdown. Prints nothing for a repo with no Dart code.
"""
import re
import subprocess
import sys

repo = sys.argv[1] if len(sys.argv) > 1 else "."
ref = sys.argv[2] if len(sys.argv) > 2 else None


def git(*args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True).stdout


if not ref:
    ref = "origin/develop" if git("rev-parse", "-q", "--verify", "origin/develop").strip() else "HEAD"

WIDGET = r"^class [A-Z][A-Za-z0-9]* extends (StatelessWidget|StatefulWidget|HookWidget|HookConsumerWidget|ConsumerWidget)"


def grep(pattern, *paths):
    out = git("grep", "-n", "-E", pattern, ref, "--", *paths)
    rows = []
    for line in out.splitlines():
        # <ref>:<path>:<line>:<text>
        _, path, num, text = line.split(":", 3)
        if path.endswith((".g.dart", ".freezed.dart", ".gr.dart", ".config.dart", ".mocks.dart")):
            continue
        rows.append((path, int(num), text))
    return rows


def doc_of(path, num):
    """First line of the /// comment right above line `num`, if any."""
    src = git("show", f"{ref}:{path}").splitlines()
    i = num - 2
    while i >= 0 and src[i].strip().startswith("@"):
        i -= 1
    lines = []
    while i >= 0 and src[i].strip().startswith("///"):
        lines.insert(0, src[i].strip()[3:].strip())
        i -= 1
    text = " ".join(lines)
    return (text[:110] + "…") if len(text) > 110 else text


def name_of(text):
    m = re.match(r"^\s*(?:abstract\s+|final\s+|base\s+|sealed\s+)*class ([A-Za-z0-9_]+)", text)
    return m.group(1) if m else text.strip()


def section(title, rows, with_doc=True):
    if not rows:
        return
    print(f"\n## {title} ({len(rows)})")
    for path, num, text in sorted(rows, key=lambda r: name_of(r[2])):
        doc = doc_of(path, num) if with_doc else ""
        print(f"- `{name_of(text)}` — {path}" + (f" — {doc}" if doc else ""))


if not git("ls-tree", "-r", "--name-only", ref, "--", "pubspec.yaml").strip():
    sys.exit(0)

print(f"# Reuse catalog @ {ref} ({git('rev-parse', '--short', ref).strip()})")
print("Before accepting a new private widget, helper or use case, check this list and grep "
      "the features for the same job. A copy of something listed here is a P1.")

section("Design-system widgets (packages/*/lib)", grep(WIDGET, "packages/*/lib/**/*.dart"))
section("App-wide widgets (lib/core)", grep(WIDGET, "lib/core/**/*.dart"))
section("Core use cases (lib/core/use_cases)",
        grep(r"^(final |abstract |base )?class [A-Z][A-Za-z0-9]*UseCase([^A-Za-z0-9_]|$)", "lib/core/use_cases/*.dart"))

fns = [r for r in grep(r"^[A-Z][A-Za-z0-9<>?, ]* [a-z][A-Za-z0-9]*\(", "lib/core/utils/*.dart", "lib/core/ui/*.dart")
       if not r[2].startswith(("class ", "enum ", "typedef ", "extension "))]
if fns:
    print(f"\n## Core helpers (lib/core/utils, lib/core/ui) ({len(fns)})")
    for path, num, text in fns:
        sig = text.split("(")[0].split()[-1]
        doc = doc_of(path, num)
        print(f"- `{sig}()` — {path}" + (f" — {doc}" if doc else ""))

exts = grep(r"^extension [A-Z][A-Za-z0-9]* on ", "lib/core/**/*.dart")
if exts:
    print(f"\n## Core extensions ({len(exts)})")
    for path, num, text in exts:
        print(f"- `{text.split('{')[0].strip()}` — {path}")

feature_ucs = grep(r"^(final |abstract |base )?class [A-Z][A-Za-z0-9]*UseCase([^A-Za-z0-9_]|$)", "lib/features/**/use_cases/*.dart")
if feature_ucs:
    print(f"\n## Feature use cases ({len(feature_ucs)}) — names only; a new one doing the same job is a copy")
    by = {}
    for path, _, text in feature_ucs:
        feat = path.split("/")[2]
        by.setdefault(feat, []).append(name_of(text))
    for feat in sorted(by):
        print(f"- **{feat}**: " + ", ".join(sorted(by[feat])))
