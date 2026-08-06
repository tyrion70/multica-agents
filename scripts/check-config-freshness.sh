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
# Profile auto-detection (override with --profile):
#   multica-01 -> private     multica-02 -> chainlayer
#
# Exit codes:
#   0  fresh (deployed matches origin/main, sync recent)
#   1  MISMATCH (deployed file != origin/main copy for this profile)
#   2  STALE (deployed file matches main, but last sync is older than
#      CONFIG_FRESHNESS_STALE_HOURS)
#   3  check itself failed (fetch/clone/hash), i.e. could not determine state
#
# Notifier: log-only by default (appends to CONFIG_FRESHNESS_LOG). If
# CONFIG_FRESHNESS_SLACK_WEBHOOK is set, a Slack message is also posted on any
# non-zero result. The destination trade-off is a deliberate design decision
# (see CHA-992) — when agent config itself is broken, Slack is the most
# independent channel; a Multica comment/autopilot rides on the stack being
# checked.
set -euo pipefail

PROFILE=""
REPO="${CONFIG_FRESHNESS_REPO:-$HOME/multica-agents}"
DEPLOYED="$HOME/.claude/CLAUDE.md"
STALE_HOURS="${CONFIG_FRESHNESS_STALE_HOURS:-30}"
LOG_DIR="${CONFIG_FRESHNESS_LOG_DIR:-$HOME/.claude/logs}"
LOG_FILE="${CONFIG_FRESHNESS_LOG:-$LOG_DIR/config-freshness.log}"
SLACK_WEBHOOK="${CONFIG_FRESHNESS_SLACK_WEBHOOK:-}"
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
if [ ! -d "$REPO/.git" ]; then
  git clone git@github.com:tyrion70/multica-agents.git "$REPO" \
    >/dev/null 2>&1 || { echo "clone failed: $REPO" >&2; exit 3; }
fi
if ! git -C "$REPO" fetch origin main >/dev/null 2>&1; then
  echo "fetch failed: $REPO" >&2
  exit 3
fi
MAIN_HASH="$(git -C "$REPO" show "origin/main:$SRC" | sha256sum | cut -d' ' -f1)"

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
fi

LINE="$(date -u +%Y-%m-%dT%H:%M:%SZ) host=$HOST profile=$PROFILE state=$STATE "\
"deployed=$DEP_HASH main=$MAIN_HASH symlink=$IS_SYMLINK age_hours=$AGE_HOURS"
mkdir -p "$LOG_DIR"
echo "$LINE" >> "$LOG_FILE"
echo "$LINE"

# --- notify -------------------------------------------------------------------
if [ "$RC" -ne 0 ] && [ -n "$SLACK_WEBHOOK" ]; then
  last_sync="$(date -u -d "@$DEP_MTIME" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo 'unknown')"
  text="Config freshness ALERT on $HOST ($PROFILE): $STATE — deployed $DEP_HASH vs main $MAIN_HASH, sync age ${AGE_HOURS}h (last sync $last_sync)"
  payload="$(SLACK_TEXT="$text" python3 -c 'import json,os; print(json.dumps({"text": os.environ["SLACK_TEXT"]}))')"
  curl -fsS -m 10 -H 'Content-Type: application/json' -d "$payload" \
    "$SLACK_WEBHOOK" >/dev/null 2>&1 || echo "slack notify failed" >&2
fi

exit "$RC"
