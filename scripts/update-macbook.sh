#!/usr/bin/env bash
# update-macbook.sh - Update development tools and restart the Multica daemon (macOS)
# The macOS counterpart of /home/peter/update.sh on multica-01 and multica-02.
# Installed to ~/update.sh on peters-macbook-pro.java-moth.ts.net.

export PATH="/opt/homebrew/bin:$HOME/.npm-global/bin:$HOME/.local/bin:$PATH"
export SHELL=/bin/bash

echo "=== Updating codex ==="
codex update || echo "[codex] update failed"

echo ""
echo "=== Updating claude ==="
claude update || echo "[claude] update failed"

echo ""
echo "=== Updating opencode ==="
npm install -g opencode-ai@latest || echo "[opencode] update failed"

echo ""
echo "=== Updating multica ==="
sudo multica update || echo "[multica] update failed"

echo ""
echo "=== Restarting multica daemon ==="
multica daemon restart || echo "[multica] daemon restart failed"
