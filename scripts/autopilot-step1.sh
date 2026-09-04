#!/usr/bin/env bash
# Autopilot step 1, end to end: bring the persistent checkout to origin/main with
# plain git, then verify it with update-checkout.sh.
#
# Why this exists as a separate file, when update-checkout.sh already pulls:
#
# On 2026-09-03 both hosts' checkouts predated `scripts/update-checkout.sh` itself
# (multica-02 sat at eb50a85, multica-01 at 066e7aa; the script arrived in #128/#130).
# Step 1 called a file that was not there, exited 127, and reported FAILED — and the
# job could not recover on its own, because **the thing that pulls was the thing that
# was missing**. A chicken-and-egg that no amount of correctness inside
# update-checkout.sh can fix, since it is never reached.
#
# So step 1 is two stages with different requirements:
#
#   1. ADVANCE, using nothing but `git`. This must work on a checkout at any commit,
#      including one that contains none of these scripts, and on a host with no
#      checkout at all. It is the only part the autopilot description has to inline,
#      because it is the part that makes the repo's own files appear.
#   2. VERIFY, using update-checkout.sh — the remote-truth assertion, the timeout,
#      the no-prompt settings, and the reporting. All of that lives in the repo where
#      it can be reviewed and tested.
#
# The description inlines stage 1 and then calls THIS file, so a future rename of
# update-checkout.sh is absorbed in-repo rather than breaking two descriptions that
# only a Multica write can fix. Stage 1 is duplicated between here and the
# description on purpose: the inline copy exists solely so that this file exists, and
# it is idempotent, so running it twice costs one no-op fetch.
#
# Contract: exit 0 means the checkout is at origin/main, verified against the remote,
# and safe to sync from. Exit 6 means it is not — stop, report the run as FAILED, and
# never fall through to a sync.
#
# Usage: scripts/autopilot-step1.sh [--repo <dir>] [--remote <url>]
set -uo pipefail

REPO="/home/peter/multica-agents"
REMOTE="git@github.com:tyrion70/multica-agents.git"
BRANCH="main"
E_STALE=6

# Same reasoning as update-checkout.sh: an unattended job must never wait for a human,
# and that has to be this script's property rather than the host's (CHA-1211 item 27).
export GIT_TERMINAL_PROMPT=0
export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh} -o BatchMode=yes"
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

# --- stage 1: advance, with plain git only ----------------------------------
if [ -d "$REPO/.git" ]; then
  echo "  → advancing $REPO to origin/$BRANCH"
  if ! fetch_out="$(git_net -C "$REPO" fetch origin "$BRANCH" 2>&1)"; then
    echo "$fetch_out" | sed 's/^/      /' >&2
    fail "'git fetch origin $BRANCH' failed in $REPO"
  fi
  # merge --ff-only FETCH_HEAD rather than `pull`: it needs no upstream tracking
  # config, so it works on a checkout in whatever state a host left it in. Still
  # fast-forward only — a checkout that cannot fast-forward is a state a human reads,
  # never something to force with reset/checkout -f/stash.
  #
  # What this catches: a genuinely divergent history, and a dirty tree whose changes
  # the merge would overwrite. What it does NOT catch, and the reason stage 2 is not
  # optional: a checkout whose branch is strictly AHEAD of the remote reports
  # "Already up to date" and exits 0 here — the same `--ff-only` trap that let a
  # three-week-stale checkout look current in the first place. Stage 2's
  # HEAD == origin/$BRANCH assertion is what actually rules that out.
  if ! ff_out="$(git -C "$REPO" merge --ff-only FETCH_HEAD 2>&1)"; then
    echo "$ff_out" | sed 's/^/      /' >&2
    fail "cannot fast-forward $REPO to origin/$BRANCH (diverged history, or local changes in the way)"
  fi
  echo "$ff_out" | sed 's/^/      /'
elif [ -e "$REPO" ]; then
  if ! entries="$(ls -A "$REPO" 2>&1)"; then
    echo "$entries" | sed 's/^/      /' >&2
    fail "$REPO exists but cannot be read — cannot tell whether cloning into it is safe"
  fi
  if [ -n "$entries" ]; then
    fail "$REPO exists, is not a git repository, and is not empty — refusing to clone into it"
  fi
  if ! clone_out="$(git_net clone "$REMOTE" "$REPO" 2>&1)"; then
    echo "$clone_out" | sed 's/^/      /' >&2
    fail "'git clone' failed"
  fi
  echo "$clone_out" | sed 's/^/      /'
else
  echo "  → cloning $REMOTE into $REPO"
  if ! clone_out="$(git_net clone "$REMOTE" "$REPO" 2>&1)"; then
    echo "$clone_out" | sed 's/^/      /' >&2
    fail "'git clone' failed"
  fi
  echo "$clone_out" | sed 's/^/      /'
fi

# --- stage 2: verify, with the checkout's OWN script -------------------------
# Deliberately only the copy inside the checkout we just advanced. There is no
# fallback to the copy next to this file: that would verify one tree while the sync
# reads another, which is a worse failure than not verifying at all. (I wrote that
# fallback first, then removed it — the comment claiming "prefer the checkout's copy"
# sat directly above code that silently accepted a different one, which is the exact
# shape of self-contradicting comment this issue has now caught three times.)
verifier="$REPO/scripts/update-checkout.sh"
if [ ! -f "$verifier" ]; then
  # Stage 1 succeeded and the verifier still is not there: the branch this checkout
  # tracks does not carry it. That is a real misconfiguration, not a stale checkout,
  # and it is the one shape stage 1 cannot repair.
  fail "$verifier is missing even after fast-forwarding to origin/$BRANCH — is this the right repository and branch?"
fi

bash "$verifier" --repo "$REPO" --remote "$REMOTE" || exit $E_STALE
