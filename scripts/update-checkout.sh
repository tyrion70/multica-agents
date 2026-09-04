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
# Contract: exit 0 means the checkout is at origin/main — verified against the remote,
# not against a cached tracking ref — and safe to sync from.
# Exit 6 means it is NOT, and the caller must stop and report the run as FAILED —
# never fall through to a sync.
#
# Usage: scripts/update-checkout.sh [--repo <dir>] [--remote <url>]
set -uo pipefail

REPO="/home/peter/multica-agents"
REMOTE="git@github.com:tyrion70/multica-agents.git"
BRANCH="main"
E_STALE=6

# An unattended nightly job must never wait for a human. Make that this script's
# property rather than the host's: 18 git fixtures showed no hang, but only because
# the host's config happened to fail fast, and a job that blocks on a credential
# prompt looks exactly like a job that is still running (CHA-1211 item 27).
# BatchMode is appended rather than assigned, so an operator-supplied
# GIT_SSH_COMMAND (a specific key, say) keeps its flags and still cannot prompt.
export GIT_TERMINAL_PROMPT=0
export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh} -o BatchMode=yes"

# And a wall-clock cap, because the two settings above stop git waiting for a HUMAN
# and this stops it waiting for a HOST. 300s is far beyond any legitimate need — the
# whole nightly chain runs in about a second and a fresh clone of this repo is
# seconds — while still turning a wedged connection into a failed run instead of a
# job that looks like it is still working. `timeout` exits 124, which the callers
# below turn into 6 like any other failure. Unlike the rest of this family, a stall
# produces no commit and no false success, which is why it is a follow-up rather than
# a gate (CHA-1211 item 27 follow-up).
GIT_NET_TIMEOUT="${GIT_NET_TIMEOUT:-300}"
if command -v timeout >/dev/null 2>&1; then
  git_net() { timeout "$GIT_NET_TIMEOUT" git "$@"; }
else
  echo "  ⚠ 'timeout' not found on PATH — network git calls run uncapped" >&2
  git_net() { git "$@"; }
fi

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
  if ! out="$(git_net -C "$REPO" pull --ff-only 2>&1)"; then
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
else
  if [ -e "$REPO" ]; then
    # The case the old one-liner silently mishandled: a path that exists and is not
    # a git repo. Cloning into it cannot succeed, so say so instead of trying — but
    # read it first. `[ -n "$(ls -A … 2>/dev/null)" ]` reported an UNREADABLE
    # directory as an empty one, fell through to the clone, and produced "clone
    # failed" instead of the actual cause (CHA-1211).
    if ! entries="$(ls -A "$REPO" 2>&1)"; then
      echo "$entries" | sed 's/^/      /' >&2
      fail "$REPO exists but cannot be read — cannot tell whether cloning into it is safe"
    fi
    if [ -n "$entries" ]; then
      fail "$REPO exists, is not a git repository, and is not empty — refusing to clone into it"
    fi
  fi
  echo "  → cloning $REMOTE into $REPO"
  if ! out="$(git_net clone "$REMOTE" "$REPO" 2>&1)"; then
    echo "$out" | sed 's/^/      /' >&2
    fail "'git clone' failed"
  fi
  echo "$out" | sed 's/^/      /'
fi

# Being on *a* commit is not the same as being current. Assert it against the REMOTE,
# so "the sync ran against a stale checkout" cannot be true after a zero exit.
head="$(git -C "$REPO" rev-parse HEAD 2>/dev/null)" || fail "cannot read HEAD in $REPO"

# The branch has to exist on the remote, not merely in a local tracking ref.
# `ls-remote --exit-code` returns 2 when no ref matches, so a deleted or renamed
# default branch (or a repo transfer) is caught here instead of being papered over
# by a stale `origin/$BRANCH` that survives on disk.
if ! ls_out="$(git_net -C "$REPO" ls-remote --exit-code origin "refs/heads/$BRANCH" 2>&1)"; then
  echo "$ls_out" | sed 's/^/      /' >&2
  fail "origin has no '$BRANCH' branch, or the remote is unreachable — cannot verify $REPO"
fi

# NOT `2>/dev/null || true`. A swallowed fetch error lets the rev-parse below fall
# back to a stale remote-tracking ref, so the assertion compares HEAD against a
# CACHED value instead of the remote and the script prints its success line for a
# checkout it never verified. That is the same fail-open #129 removed from sync.sh
# and commit-sync-state.sh two commits earlier, and this is the file everything else
# now trusts (CHA-1211 H1).
if ! fetch_out="$(git_net -C "$REPO" fetch origin "$BRANCH" 2>&1)"; then
  echo "$fetch_out" | sed 's/^/      /' >&2
  fail "'git fetch origin $BRANCH' failed — HEAD cannot be verified against the remote"
fi

# `|| true` here left an empty $remote_head standing in for both "no such ref" and
# "rev-parse failed"; the emptiness check below caught it either way, but the shape is
# the one this repo keeps getting wrong, so it checks the status instead (CHA-1211).
#
# Stderr to its own file, not `2>&1` into the value (CHA-1211 I1): git warns on
# SUCCESS when `origin/$BRANCH` matches both a local branch and a remote-tracking ref
# ("warning: refname 'origin/main' is ambiguous."), and folded into $remote_head that
# warning makes the comparison below fail — exit 6 with a garbled message about a
# checkout that was actually fine. It fails CLOSED here, unlike the same shape in
# check-config-freshness.sh, so this is a diagnosis bug rather than a wrong answer —
# but it is the same line, and a diagnosis nobody can read is how an hour goes.
rp_err="$(mktemp)"
if ! remote_head="$(git -C "$REPO" rev-parse "origin/$BRANCH" 2>"$rp_err")"; then
  sed 's/^/      /' "$rp_err" >&2
  rm -f "$rp_err"
  fail "cannot resolve origin/$BRANCH in $REPO"
fi
if [ -s "$rp_err" ]; then
  # Resolved, but git had something to say. Surface it rather than discarding it:
  # an ambiguous origin/$BRANCH means the checkout has refs that will confuse the
  # next person as much as they nearly confused this script.
  echo "  ⚠ git warned while resolving origin/$BRANCH:" >&2
  sed 's/^/      /' "$rp_err" >&2
fi
rm -f "$rp_err"
if ! [[ "$remote_head" =~ ^[0-9a-f]{40}$ ]]; then
  fail "origin/$BRANCH did not resolve to a commit id in $REPO: '$remote_head'"
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
