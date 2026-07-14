#!/usr/bin/env bash
# Install the nb NetBox CLI into ~/.local/bin
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BIN="${HOME}/.local/bin"
mkdir -p "$BIN"
cp "$REPO_ROOT/scripts/nb" "$BIN/nb"
chmod +x "$BIN/nb"
echo "  → installed ${BIN}/nb"
