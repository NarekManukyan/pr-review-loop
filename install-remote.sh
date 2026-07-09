#!/usr/bin/env bash
# One-line global installer for pr-review-loop. Clones (or updates) the plugin to a
# cache dir and installs it into ~/.claude for the current user — available in every
# project. Re-run any time to update.
#
#   curl -fsSL https://raw.githubusercontent.com/NarekManukyan/pr-review-loop/main/install-remote.sh | bash
#
# Override the checkout location with PR_REVIEW_LOOP_DIR=/path.
set -euo pipefail

REPO="https://github.com/NarekManukyan/pr-review-loop"
DIR="${PR_REVIEW_LOOP_DIR:-$HOME/.pr-review-loop}"

command -v git >/dev/null 2>&1 || { echo "git is required" >&2; exit 1; }

if [ -d "$DIR/.git" ]; then
  echo "Updating pr-review-loop in $DIR …"
  git -C "$DIR" pull --ff-only --depth 1 origin main >/dev/null 2>&1 || git -C "$DIR" pull --ff-only
else
  echo "Cloning pr-review-loop -> $DIR …"
  git clone --depth 1 "$REPO" "$DIR"
fi

bash "$DIR/install.sh"

echo
echo "Installed to ~/.claude (global for this user). Restart Claude Code, then run /review-pr-init."
echo "Update later: re-run this same one-liner, or  git -C \"$DIR\" pull && bash \"$DIR/install.sh\""
