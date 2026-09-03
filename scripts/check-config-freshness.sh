#!/usr/bin/env bash
# check-config-freshness.sh — verify the host's deployed ~/.claude/CLAUDE.md
# matches the maintained copy in multica-agents origin/main, and report the
# age of the last successful sync.
#
# Deliberately independent of scripts/sync.sh and of the multica daemon:
# sync.sh can only report while it runs, so a check that lives inside it can
# never report that sync STOPPED running — the exact failure mode CHA-992
# exposed (a stale copy served for six weeks with no signal). This runs from
# host cron instead.
#
# Also detects a lagging sync baseline (CHA-1087). .sync-state.json is the
# committed record of what was last pushed to each Multica workspace. When a
# skill or agent merges and nobody commits the refreshed state, the baseline
# falls behind: the live workspace has moved past it, so the NEXT unrelated
# change reads as "both sides changed" and sync.sh exits 2 on a conflict that
# is not one. That is exactly how the Private/ssh conflict happened. Same
# reasoning as above for living here rather than in sync.sh: a check inside
# sync can only fire while someone is running sync, and the failure mode is
# nobody running it.
#
# Profile auto-detection (override with --profile):
#   multica-01 -> private     multica-02 -> chainlayer
#
# Exit codes:
#   0  fresh (deployed matches origin/main, sync recent)
#   1  MISMATCH (deployed file != origin/main copy for this profile)
#   2  STALE (deployed file matches main, but last sync is older than
#      CONFIG_FRESHNESS_STALE_HOURS)
#   3  check itself failed (fetch/clone/hash), i.e. could not determine state
#   4  BASELINE_LAG (CLAUDE.md is fine, but .sync-state.json on origin/main is
#      older than the newest skills/ or */agent.json commit, so the committed
#      sync baseline no longer describes what was last pushed to Multica)
#
# Notifier: log-only by default (appends to CONFIG_FRESHNESS_LOG). When the
# 0600 env file ($HOME/.claude/config-freshness.env, sourced at runtime — never
# the crontab line or argv; CHA-987 exported-env rule) sets
# CONFIG_FRESHNESS_SLACK_TOKEN + CONFIG_FRESHNESS_SLACK_USER_ID, a Slack DM is
# posted on any non-zero result via the Web API (conversations.open then
# chat.postMessage). The legacy CONFIG_FRESHNESS_SLACK_WEBHOOK path is kept as
# a fallback. Alerting failures never change the exit code and are written to
# the log file — an unreachable Slack must not silence the detector or fake it
# healthy.
set -euo pipefail

PROFILE=""
REPO="${CONFIG_FRESHNESS_REPO:-$HOME/multica-agents}"
DEPLOYED="${CONFIG_FRESHNESS_DEPLOYED:-$HOME/.claude/CLAUDE.md}"
STALE_HOURS="${CONFIG_FRESHNESS_STALE_HOURS:-30}"
LOG_DIR="${CONFIG_FRESHNESS_LOG_DIR:-$HOME/.claude/logs}"
LOG_FILE="${CONFIG_FRESHNESS_LOG:-$LOG_DIR/config-freshness.log}"
SLACK_WEBHOOK="${CONFIG_FRESHNESS_SLACK_WEBHOOK:-}"
SLACK_TOKEN="${CONFIG_FRESHNESS_SLACK_TOKEN:-}"
SLACK_USER_ID="${CONFIG_FRESHNESS_SLACK_USER_ID:-}"
HOST="$(hostname)"

while [ $# -gt 0 ]; do
  case "$1" in
    --profile)
      PROFILE="$2"; shift 2 ;;
    --repo)
      REPO="$2"; shift 2 ;;
    *)
      echo "unknown arg: $1" >&2; exit 3 ;;
  esac
done

# --- profile detection -------------------------------------------------------
if [ -z "$PROFILE" ]; then
  case "$HOST" in
    multica-01) PROFILE="private" ;;
    multica-02) PROFILE="chainlayer" ;;
    *)
      echo "cannot auto-detect profile on $HOST; pass --profile" >&2
      exit 3 ;;
  esac
fi
SRC="claude-config/$PROFILE/CLAUDE.md"

# --- authoritative copy from origin/main ------------------------------------
if [ -f "$REPO/.git" ]; then
  # A worktree-style checkout: `.git` is a FILE holding a gitdir: pointer, so the
  # `-d` test below reads it as "no repo here" and the clone that follows cannot
  # succeed. That is fail-closed (exit 3, nothing reported), but the message used to
  # be "clone failed" and sent the reader after the wrong hypothesis (CHA-1211 I6).
  echo "$REPO is a worktree-style checkout (.git is a file, not a directory)." >&2
  echo "  This script needs a normal clone. Point it at one:" >&2
  echo "    CONFIG_FRESHNESS_REPO=<path-to-clone> $0 …   (or --repo <path>)" >&2
  exit 3
fi
if [ ! -d "$REPO/.git" ]; then
  git clone git@github.com:tyrion70/multica-agents.git "$REPO" \
    >/dev/null 2>&1 || { echo "clone failed: $REPO" >&2; exit 3; }
fi
if ! git -C "$REPO" fetch origin main >/dev/null 2>&1; then
  echo "fetch failed: $REPO" >&2
  exit 3
fi
MAIN_HASH="$(git -C "$REPO" show "origin/main:$SRC" | sha256sum | cut -d' ' -f1)"

# --- sync-state baseline lag (CHA-1087) -------------------------------------
# Commit timestamps, not content: if a skill or agent definition landed AFTER the
# last .sync-state.json commit, the committed baseline predates it by construction.
#
# Fail closed on the READ, but keep "no such commit yet" as a legitimate answer —
# `git log -1 -- <path>` exits 0 with empty output when nothing has touched that
# path, which is different from git failing. Swallowing both as `|| true` meant a
# broken `git log` reported BASELINE_LAG_SEC=0, i.e. "the baseline is current", from
# the very script whose job is to notice that it is not (CHA-1211, found by the
# scripts/*.sh sweep that the fail-open lint test in test_sync.py now automates).
# The stderr goes to its own file, NOT into the captured value (CHA-1211 I1). The
# first version of this fix used `2>&1`, and git writes warnings to stderr on
# SUCCESS: with both a `refs/heads/origin/main` and a `refs/remotes/origin/main` in
# the checkout, `origin/main` is ambiguous and rc=0 comes back as
#   "warning: refname 'origin/main' is ambiguous.\n1788442689"
# so STATE_TS stops being an integer, `[ … -gt … ]` errors with "integer expression
# expected", the if takes the else branch, and the watchdog reports
# `state=FRESH baseline_lag_sec=0` — the exact wrong answer this whole fix exists to
# remove, reached through a new door the fix itself opened. Same reasoning as
# sync.sh:150: never let a command's diagnostics share a channel with its payload.
git_err="$(mktemp)"
trap 'rm -f "$git_err"' EXIT
# `return 3` and an explicit `|| exit 3` at the call site, not `exit 3` in here: this
# runs inside a command substitution, so `exit` would end the SUBSHELL and the script
# would only stop because `set -e` happens to be on. Depending on that is the kind of
# implicitness this whole issue is about.
_read_ts() { # <label> <path…> → echoes the timestamp, or returns 3
  local label="$1"; shift
  local ts
  if ! ts="$(git -C "$REPO" log -1 --format=%ct origin/main -- "$@" 2>"$git_err")"; then
    echo "git log failed for $label in $REPO:" >&2
    sed 's/^/  /' "$git_err" >&2
    return 3
  fi
  # Empty is legitimate ("no commit touches that path"); anything that is neither
  # empty nor a plain integer means the value has been contaminated, and guessing
  # what it meant is how the else branch got reached in the first place.
  if [ -n "$ts" ] && ! [[ "$ts" =~ ^[0-9]+$ ]]; then
    echo "git log returned a non-numeric timestamp for $label in $REPO:" >&2
    printf '  %s\n' "$ts" >&2
    sed 's/^/  /' "$git_err" >&2
    return 3
  fi
  printf '%s' "$ts"
}
STATE_TS="$(_read_ts '.sync-state.json' .sync-state.json)" || exit 3
DEFS_TS="$(_read_ts 'the skill/agent definitions' skills '*/agent.json')" || exit 3
# Empty means "no commit touches that path", which really is timestamp zero.
STATE_TS="${STATE_TS:-0}"
DEFS_TS="${DEFS_TS:-0}"
if [ "$DEFS_TS" -gt "$STATE_TS" ]; then
  BASELINE_LAG_SEC=$(( DEFS_TS - STATE_TS ))
else
  BASELINE_LAG_SEC=0
fi

# --- deployed state ----------------------------------------------------------
if [ -L "$DEPLOYED" ]; then
  # A symlink here is itself a failure: the deploy contract is a regular file
  # copied by sync.sh (commit 79398ce), not a symlink into any checkout.
  IS_SYMLINK="yes"
else
  IS_SYMLINK="no"
fi
if [ -f "$DEPLOYED" ]; then
  DEP_HASH="$(sha256sum "$DEPLOYED" | cut -d' ' -f1)"
  DEP_MTIME="$(stat -c %Y "$DEPLOYED")"
  NOW="$(date +%s)"
  AGE_HOURS=$(( (NOW - DEP_MTIME) / 3600 ))
else
  DEP_HASH="MISSING"
  DEP_MTIME="0"
  AGE_HOURS="-1"
fi

# --- evaluate ----------------------------------------------------------------
RC=0
STATE="FRESH"
if [ "$DEP_HASH" = "MISSING" ]; then
  RC=1; STATE="MISMATCH"
elif [ "$IS_SYMLINK" = "yes" ]; then
  RC=1; STATE="MISMATCH"
elif [ "$DEP_HASH" != "$MAIN_HASH" ]; then
  RC=1; STATE="MISMATCH"
elif [ "$AGE_HOURS" -ge "$STALE_HOURS" ]; then
  RC=2; STATE="STALE"
elif [ "$BASELINE_LAG_SEC" -gt 0 ]; then
  # Ranked last: the deployed CLAUDE.md is correct and sync is running, but the
  # next sync will mis-read a one-sided change as a conflict.
  RC=4; STATE="BASELINE_LAG"
fi

LINE="$(date -u +%Y-%m-%dT%H:%M:%SZ) host=$HOST profile=$PROFILE state=$STATE "\
"deployed=$DEP_HASH main=$MAIN_HASH symlink=$IS_SYMLINK age_hours=$AGE_HOURS "\
"baseline_lag_sec=$BASELINE_LAG_SEC"
mkdir -p "$LOG_DIR"
echo "$LINE" >> "$LOG_FILE"
echo "$LINE"

# --- notify -------------------------------------------------------------------
# Alerting failures are logged to the log file and never change RC: an
# unreachable Slack must not silence the detector or fake it healthy.
# Source the 0600 env file (token/user) if present. Env file is preferred over
# the cron line so the token never lives in crontab plaintext (CHA-987 rule:
# secret reaches the script as an exported env var, never argv).
if [ -f "$HOME/.claude/config-freshness.env" ]; then
  # shellcheck disable=SC1091
  set -a; . "$HOME/.claude/config-freshness.env"; set +a
  SLACK_TOKEN="${CONFIG_FRESHNESS_SLACK_TOKEN:-$SLACK_TOKEN}"
  SLACK_USER_ID="${CONFIG_FRESHNESS_SLACK_USER_ID:-$SLACK_USER_ID}"
  SLACK_WEBHOOK="${CONFIG_FRESHNESS_SLACK_WEBHOOK:-$SLACK_WEBHOOK}"
fi

if [ "$RC" -ne 0 ]; then
  last_sync="$(date -u -d "@$DEP_MTIME" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo 'unknown')"
  text="Config freshness ALERT on $HOST ($PROFILE): $STATE — deployed $DEP_HASH vs main $MAIN_HASH, sync age ${AGE_HOURS}h (last sync $last_sync)"

  notify_sent=""
  # Preferred path: DM via Slack Web API (conversations.open + chat.postMessage).
  if [ -n "$SLACK_TOKEN" ] && [ -n "$SLACK_USER_ID" ]; then
    open_resp="$(curl -sS -m 15 -H "Authorization: Bearer $SLACK_TOKEN" \
      --data "users=$SLACK_USER_ID" \
      https://slack.com/api/conversations.open 2>&1)"
    ch="$(printf '%s' "$open_resp" | python3 -c '
import json,sys
try:
    d=json.load(sys.stdin)
    print(d.get("channel",{}).get("id","") if d.get("ok") else "")
except Exception:
    print("")')"
    if [ -n "$ch" ]; then
      payload="$(SLACK_TEXT="$text" python3 -c '
import json,os,sys
print(json.dumps({"channel": "'$ch'", "text": os.environ["SLACK_TEXT"]}))')"
      post_resp="$(curl -sS -m 15 -H "Authorization: Bearer $SLACK_TOKEN" \
        -H 'Content-Type: application/json; charset=utf-8' \
        -d "$payload" https://slack.com/api/chat.postMessage 2>&1)"
      ok="$(printf '%s' "$post_resp" | python3 -c '
import json,sys
try:
    print(json.load(sys.stdin).get("ok", False))
except Exception:
    print(False)')"
      if [ "$ok" = "True" ]; then
        notify_sent="dm"
      else
        err="$(printf '%s' "$post_resp" | python3 -c '
import json,sys
try:
    print(json.load(sys.stdin).get("error","?"))
except Exception:
    print("unparseable response")')"
        echo "  Slack DM send failed (chat.postMessage: $err) — see log; detector result unchanged" >> "$LOG_FILE"
      fi
    else
      err="$(printf '%s' "$open_resp" | python3 -c '
import json,sys
try:
    print(json.load(sys.stdin).get("error","?"))
except Exception:
    print("unparseable response")')"
      echo "  Slack DM open failed (conversations.open: $err) — see log; detector result unchanged" >> "$LOG_FILE"
    fi
  fi

  # Fallback: legacy incoming webhook, kept only if still configured.
  if [ -z "$notify_sent" ] && [ -n "$SLACK_WEBHOOK" ]; then
    payload="$(SLACK_TEXT="$text" python3 -c '
import json,os
print(json.dumps({"text": os.environ["SLACK_TEXT"]}))')"
    if curl -fsS -m 15 -H 'Content-Type: application/json' -d "$payload" \
      "$SLACK_WEBHOOK" >/dev/null 2>&1; then
      notify_sent="webhook"
    else
      echo "  Slack webhook fallback failed — see log; detector result unchanged" >> "$LOG_FILE"
    fi
  fi

  if [ -n "$notify_sent" ]; then
    echo "  Slack notify sent via $notify_sent" >> "$LOG_FILE"
  elif [ -z "$SLACK_TOKEN" ] && [ -z "$SLACK_WEBHOOK" ]; then
    echo "  no Slack configured (log-only mode); alert present in this log" >> "$LOG_FILE"
  fi
fi

exit "$RC"
