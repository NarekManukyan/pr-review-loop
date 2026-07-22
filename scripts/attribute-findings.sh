#!/usr/bin/env bash
# Attribute stack-mode findings back to the MR that introduced them.
#
# In stack mode the panel reviews ONE cumulative diff at the stack tip, so every
# finding carries a tip-relative file:line. Authors still need their own comments,
# so map each finding to the lowest branch in the chain whose history contains the
# blamed commit — that is the MR that introduced the line.
#
#   blame file:line at <tip> -> commit SHA -> chain branches containing that SHA
#   -> lowest one in chain order = the introducing MR.
#
# Usage:
#   attribute-findings.sh --repo <dir> --tip <ref> \
#     --chain <br1,br2,...,brN>            # ordered BOTTOM -> TOP, remote names ok
#     [--base <ref>]                       # default origin/main, else main
#     [--file <path> --line <N>]           # single finding, or read stdin:
#   printf 'path/a.dart:36\npath/b.dart:12\n' | attribute-findings.sh --repo . --tip … --chain …
#
# Output: TSV, one row per finding —  file <TAB> line <TAB> branch <TAB> sha
# Unattributable rows get branch `UNKNOWN` and a reason in the sha column
# (`UNKNOWN:no-such-file`, `UNKNOWN:line-out-of-range`, `UNKNOWN:not-in-chain`,
# `UNKNOWN:pre-existing` = the line already exists on the base branch, so no MR in
# this stack introduced it — report it against the tip, never against the bottom MR).
# Exit 0 even with UNKNOWN rows — the caller decides the fallback; exit 2 only on
# bad invocation. Callers MUST treat any UNKNOWN as "post on the tip MR, name the
# originating file" rather than guessing an author.
#
# Gotcha this script exists to avoid: `git branch --contains <sha>` (no `-a`) sees
# only LOCAL branches. A freshly cloned/fetched stack has all its branches under
# refs/remotes/origin/, so that form returns nothing and attribution looks broken.
# This uses `git for-each-ref --contains` over both local and remote refs.
#
# Second gotcha: every chain branch descends from the base, so a commit that is
# ALREADY on the base is "contained" by all of them and would attribute to the
# bottom MR. Findings are explicitly not limited to changed files, so blaming
# pre-existing code happens routinely. The --base ancestor test rejects those.
set -euo pipefail

REPO="."; TIP=""; CHAIN=""; BASE=""; ONE_FILE=""; ONE_LINE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --repo)  REPO="$2";     shift 2 ;;
    --tip)   TIP="$2";      shift 2 ;;
    --chain) CHAIN="$2";    shift 2 ;;
    --base)  BASE="$2";     shift 2 ;;
    --file)  ONE_FILE="$2"; shift 2 ;;
    --line)  ONE_LINE="$2"; shift 2 ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
[ -n "$TIP" ] && [ -n "$CHAIN" ] || { echo "usage: --repo <dir> --tip <ref> --chain <b1,b2,...> [--file F --line N]" >&2; exit 2; }
cd "$REPO" || exit 2

# Base branch the stack merges into. Findings on lines that already exist there
# belong to no MR in this stack.
if [ -z "$BASE" ]; then
  for cand in origin/main main origin/master master; do
    if git rev-parse --verify --quiet "$cand" >/dev/null; then BASE="$cand"; break; fi
  done
fi
[ -n "$BASE" ] || { echo "could not resolve a base branch; pass --base <ref>" >&2; exit 2; }

# Chain branches, bottom -> top. Accept `x`, `origin/x`, `refs/remotes/origin/x`;
# normalise to the bare name so we can match for-each-ref output either way.
IFS=',' read -r -a CHAIN_BR <<< "$CHAIN"
for i in "${!CHAIN_BR[@]}"; do
  b="${CHAIN_BR[$i]}"
  b="${b#refs/remotes/}"; b="${b#refs/heads/}"; b="${b#origin/}"
  CHAIN_BR[$i]="$(printf '%s' "$b" | tr -d '[:space:]')"
done

attribute() {
  local file="$1" line="$2" sha="" refs="" bare="" idx best_idx=-1 best_br=""

  if ! git cat-file -e "$TIP:$file" 2>/dev/null; then
    printf '%s\t%s\t%s\t%s\n' "$file" "$line" "UNKNOWN" "UNKNOWN:no-such-file"; return
  fi
  # -w ignores whitespace-only reindents so a later formatting-only MR does not
  # steal attribution from the MR that wrote the logic.
  sha="$(git blame -w -L "$line,$line" --porcelain "$TIP" -- "$file" 2>/dev/null | head -1 | cut -d' ' -f1 || true)"
  if [ -z "$sha" ] || [ "${#sha}" -ne 40 ]; then
    printf '%s\t%s\t%s\t%s\n' "$file" "$line" "UNKNOWN" "UNKNOWN:line-out-of-range"; return
  fi

  # Already on the base -> pre-existing code, not introduced by this stack.
  if git merge-base --is-ancestor "$sha" "$BASE" 2>/dev/null; then
    printf '%s\t%s\t%s\t%s\n' "$file" "$line" "UNKNOWN" "UNKNOWN:pre-existing"; return
  fi

  # Every chain branch whose history contains this commit. Local AND remote refs.
  refs="$(git for-each-ref --contains "$sha" --format='%(refname)' refs/heads refs/remotes 2>/dev/null || true)"
  while IFS= read -r r; do
    [ -n "$r" ] || continue
    bare="${r#refs/remotes/}"; bare="${bare#refs/heads/}"; bare="${bare#origin/}"
    for idx in "${!CHAIN_BR[@]}"; do
      if [ "$bare" = "${CHAIN_BR[$idx]}" ]; then
        # Lowest position in chain order wins — the first MR to carry the commit.
        if [ "$best_idx" -lt 0 ] || [ "$idx" -lt "$best_idx" ]; then
          best_idx="$idx"; best_br="$bare"
        fi
      fi
    done
  done <<< "$refs"

  if [ "$best_idx" -lt 0 ]; then
    # Commit predates the stack (already on main) or the branch was not fetched.
    printf '%s\t%s\t%s\t%s\n' "$file" "$line" "UNKNOWN" "UNKNOWN:not-in-chain"; return
  fi
  printf '%s\t%s\t%s\t%s\n' "$file" "$line" "$best_br" "${sha:0:12}"
}

if [ -n "$ONE_FILE" ]; then
  attribute "$ONE_FILE" "${ONE_LINE:-1}"
else
  while IFS= read -r entry || [ -n "$entry" ]; do
    entry="$(printf '%s' "$entry" | tr -d '[:space:]')"
    [ -n "$entry" ] || continue
    attribute "${entry%:*}" "${entry##*:}"
  done
fi
