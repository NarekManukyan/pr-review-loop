#!/usr/bin/env bash
# Best-effort install of graphify (the `graphifyy` pip package) so review-memory's
# semantic recall layer is available. Idempotent, never fatal: if graphify can't be
# installed, review-memory still works via deterministic JSONL recall.
# A marker file stops repeat attempts. Pass --force to retry.
set -u

MARKER="$HOME/.claude/.mone-review-graphify-checked"
[ "${1:-}" = "--force" ] && rm -f "$MARKER"

# already present, or already tried → nothing to do
if command -v graphify >/dev/null 2>&1; then
  touch "$MARKER" 2>/dev/null || true
  exit 0
fi
[ -f "$MARKER" ] && exit 0
mkdir -p "$(dirname "$MARKER")" 2>/dev/null || true
touch "$MARKER" 2>/dev/null || true

echo "[mone-review] installing graphify (optional semantic recall)…" >&2

# 1. uv tool (modern, isolated) — preferred
if command -v uv >/dev/null 2>&1; then
  uv tool install graphifyy >/dev/null 2>&1 && command -v graphify >/dev/null 2>&1 && {
    echo "[mone-review] graphify installed via uv" >&2; exit 0; }
fi
# 2. pipx (isolated)
if command -v pipx >/dev/null 2>&1; then
  pipx install graphifyy >/dev/null 2>&1 && command -v graphify >/dev/null 2>&1 && {
    echo "[mone-review] graphify installed via pipx" >&2; exit 0; }
fi
# 3. pip (user site), then PEP-668 override as last resort
PY="$(command -v python3 || command -v python || echo python3)"
"$PY" -m pip install --user graphifyy >/dev/null 2>&1 && command -v graphify >/dev/null 2>&1 && {
  echo "[mone-review] graphify installed via pip --user" >&2; exit 0; }
"$PY" -m pip install --user --break-system-packages graphifyy >/dev/null 2>&1 && command -v graphify >/dev/null 2>&1 && {
  echo "[mone-review] graphify installed via pip --break-system-packages" >&2; exit 0; }

echo "[mone-review] could not auto-install graphify — that's fine, JSONL recall still works." >&2
echo "[mone-review] to add semantic recall later: pipx install graphifyy  (or uv tool install graphifyy)" >&2
exit 0
