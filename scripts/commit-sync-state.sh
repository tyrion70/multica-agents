#!/usr/bin/env bash
# Commit .sync-state.json to main — and NOTHING else.
#
# .sync-state.json is the one path CLAUDE.md licenses to go straight to main: it is
# generated bookkeeping (what the last run pushed to each workspace), it changes on every
# run, and a PR round-trip per sync gets it skipped, which leaves the baseline behind the
# live workspaces and surfaces later as a false conflict (CHA-1087).
#
# That licence is written in terms of the COMMIT MESSAGE, not the paths — so on
# 2026-09-03 02:38 a sync run whose skill reads came back empty rewrote 24 skill files,
# the autopilot swept them into `chore: sync state`, and 4,139 deletions reached main
# with no review (CHA-1211). This script is the sanctioned commit path so the scope is
# enforced by a check rather than by whoever is typing `git add`.
#
# Usage: scripts/commit-sync-state.sh [--push]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STATE_FILE=".sync-state.json"

push=0
for arg in "$@"; do
  case "$arg" in
    --push) push=1 ;;
    *) echo "usage: $(basename "$0") [--push]" >&2; exit 64 ;;
  esac
done

cd "$REPO_ROOT"

# Everything dirty or staged, other than the state file. Renames report as
# "R  old -> new"; keep the destination. Paths with odd characters come back quoted.
out_of_scope="$(
  git status --porcelain --untracked-files=all \
    | sed -e 's/^...//' -e 's/^.* -> //' -e 's/^"\(.*\)"$/\1/' \
    | grep -v "^${STATE_FILE//./\\.}$" || true
)"
if [ -n "$out_of_scope" ]; then
  echo "ERROR: refusing to commit — the tree holds changes outside $STATE_FILE:" >&2
  echo "$out_of_scope" | sed 's/^/         /' >&2
  echo "       A 'chore: sync state' commit may touch $STATE_FILE and nothing else." >&2
  echo "       Those paths are reviewable content: open a PR for the ones that are" >&2
  echo "       genuine, or 'git checkout --' them, then re-run this script." >&2
  exit 5
fi

if [ -z "$(git status --porcelain -- "$STATE_FILE")" ]; then
  echo "  → $STATE_FILE is unchanged; nothing to commit."
  exit 0
fi

git add -- "$STATE_FILE"

# Belt and braces: assert what is actually staged, in case a concurrent process or a
# pre-existing index entry slipped something in between the check above and the commit.
staged="$(git diff --cached --name-only)"
if [ "$staged" != "$STATE_FILE" ]; then
  echo "ERROR: staged set is not exactly $STATE_FILE — aborting:" >&2
  echo "$staged" | sed 's/^/         /' >&2
  git reset -q
  exit 5
fi

git commit -m 'chore: sync state'
echo "  → committed $STATE_FILE"

if [ "$push" -eq 1 ]; then
  git push origin HEAD:main
  echo "  → pushed to main"
else
  echo "  → not pushed (re-run with --push, or: git push origin HEAD:main)"
fi
