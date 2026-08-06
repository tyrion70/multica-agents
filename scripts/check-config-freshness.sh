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
DEPLOYED="$HOME/.claude/CLAUDE.md"
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
