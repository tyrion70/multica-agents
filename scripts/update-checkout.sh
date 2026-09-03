#!/usr/bin/env bash
# Bring the persistent multica-agents checkout to origin/main — or fail loudly.
#
# This is step 1 of both sync autopilots, moved out of the autopilot description and
# into the repo so it can be reviewed in a PR and tested in CI. The description used
# to say:
#
#     [ -d /home/peter/multica-agents/.git ] \
#       && git -C /home/peter/multica-agents pull --ff-only \
#       || git clone git@github.com:tyrion70/multica-agents.git /home/peter/multica-agents
#
# which cannot work: `||` fires only when the pull FAILS, and `git clone` cannot clone
# into a non-empty existing directory, so it fails too — and the whole line falls
# through with a non-zero status nobody checked. Step 2 then ran `sync.sh` against a
# STALE checkout and step 6 reported a clean run, because it keyed off `sync.sh`'s exit
# code alone. That is what hid the `Private Sync` breakage from 2026-08-09 to 08-31
# (CHA-1211): the fourth instance in this incident of a failed read reported as a
# successful state.
#
# Contract: exit 0 means the checkout is at origin/main and safe to sync from.
# Exit 6 means it is NOT, and the caller must stop and report the run as FAILED —
# never fall through to a sync.
#
# Usage: scripts/update-checkout.sh [--repo <dir>] [--remote <url>]
set -uo pipefail

REPO="/home/peter/multica-agents"
REMOTE="git@github.com:tyrion70/multica-agents.git"
BRANCH="main"
E_STALE=6

while [ $# -gt 0 ]; do
  case "$1" in
    --repo)   REPO="$2"; shift 2 ;;
    --remote) REMOTE="$2"; shift 2 ;;
    *) echo "usage: $(basename "$0") [--repo <dir>] [--remote <url>]" >&2; exit 64 ;;
  esac
done

fail() {
  echo "==> CHECKOUT NOT UPDATED: $1" >&2
  echo "    The run has FAILED. Do NOT run sync.sh — it would sync a stale or unknown" >&2
  echo "    checkout and report success (CHA-1211). Report the failure and file an issue." >&2
  exit $E_STALE
}

if [ -d "$REPO/.git" ]; then
  echo "  → updating $REPO"
  if ! out="$(git -C "$REPO" pull --ff-only 2>&1)"; then
    echo "$out" | sed 's/^/      /' >&2
    # The two causes seen in practice, named so the issue can say which one:
    #   * Permission denied (publickey) — the `ssh` skill, never fall back to HTTPS.
    #   * a dirty .sync-state.json blocking the merge — commit it with
    #     scripts/commit-sync-state.sh --push, then re-run this script.
    # Neither is fixed by forcing: no `git reset --hard`, no `git checkout -f`, no
    # `git stash` here. A pull that cannot fast-forward is a state a human reads.
    fail "'git pull --ff-only' failed in $REPO"
  fi
  echo "$out" | sed 's/^/      /'
elif [ -e "$REPO" ] && [ -n "$(ls -A "$REPO" 2>/dev/null)" ]; then
  # The case the old one-liner silently mishandled: a directory that exists and is
  # not a git repo. Cloning into it cannot succeed, so say so instead of trying.
  fail "$REPO exists, is not a git repository, and is not empty — refusing to clone into it"
else
  echo "  → cloning $REMOTE into $REPO"
  if ! out="$(git clone "$REMOTE" "$REPO" 2>&1)"; then
    echo "$out" | sed 's/^/      /' >&2
    fail "'git clone' failed"
  fi
  echo "$out" | sed 's/^/      /'
fi

# Being on *a* commit is not the same as being current. Assert it, so "the sync ran
# against a stale checkout" cannot be true after a zero exit.
head="$(git -C "$REPO" rev-parse HEAD 2>/dev/null)" || fail "cannot read HEAD in $REPO"
git -C "$REPO" fetch origin "$BRANCH" --quiet 2>/dev/null || true
remote_head="$(git -C "$REPO" rev-parse "origin/$BRANCH" 2>/dev/null || true)"
if [ -z "$remote_head" ]; then
  fail "cannot resolve origin/$BRANCH in $REPO"
fi
if [ "$head" != "$remote_head" ]; then
  fail "HEAD ($head) is not origin/$BRANCH ($remote_head) — detached, diverged, or on another branch"
fi

echo "  ✓ $REPO at origin/$BRANCH ${head:0:8} ($(git -C "$REPO" log -1 --format=%s | cut -c1-60))"
dirty="$(git -C "$REPO" status --porcelain 2>/dev/null)" || fail "'git status' failed in $REPO"
if [ -n "$dirty" ]; then
  echo "  ⚠ working tree is dirty before the sync even starts:"
  echo "$dirty" | sed 's/^/      /'
  echo "    (a dirty .sync-state.json is the usual cause and blocks tomorrow's pull —"
  echo "     commit it with scripts/commit-sync-state.sh --push)"
fi
