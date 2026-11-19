#!/usr/bin/env bash
# Installs the copilot-contract-loop skill into GitHub Copilot CLI.
#   ./install.sh              # ${COPILOT_HOME:-~/.copilot}/skills/copilot-contract-loop
#   ./install.sh --dir <path> # custom skills root
set -euo pipefail

SRC="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/skills/copilot-contract-loop"
ROOT="${COPILOT_HOME:-$HOME/.copilot}/skills"
if [ "${1:-}" = "--dir" ]; then
  [ -n "${2:-}" ] || { echo "error: --dir requires a path" >&2; exit 2; }
  ROOT="$2"
fi

DEST="$ROOT/copilot-contract-loop"
mkdir -p "$ROOT"
rm -rf "$DEST"
cp -R "$SRC" "$DEST"
find "$DEST" -name __pycache__ -type d -prune -exec rm -rf {} +
echo "installed: $DEST"
