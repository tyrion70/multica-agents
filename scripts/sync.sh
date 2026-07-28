#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Drop injected env vars so multica CLI calls fall back to the host's local
# config (~/.multica/config.json) and its user login.  Agent/autopilot tasks
# inherit MULTICA_TOKEN, MULTICA_WORKSPACE_ID etc from the runtime — these
# override the local config and scope the CLI to the task's workspace, which
# may not be the one the operator intended (e.g. a Chainlayer-dispatched
# task trying to sync the Private workspace).
# 
# Unsetting them means every `multica` call in this script uses the host's
# local login (peter@tyrion.nl) and whatever workspace is active in
# config.json.  sync.sh is always executed, never sourced, so the parent
# process keeps its original env.
for var in MULTICA_AGENT_ID MULTICA_AGENT_NAME MULTICA_DAEMON_PORT \
           MULTICA_SERVER_URL MULTICA_TASK_ID MULTICA_TASK_SLOT \
           MULTICA_TOKEN MULTICA_WORKSPACE_ID; do
  unset "$var"
done

# Single EXIT cleanup for everything below (daemon-ctx restore + bw teardown).
# Both steps are opt-in: the vars stay empty until their block populates them,
# so this is a no-op if neither runs. bw teardown goes first, then the ctx
# restore, so the isolated vault is logged out and removed before we hand the
# workdir back.
DAEMON_CTX=""; DAEMON_CTX_BAK=""; BW_DATADIR=""
_cleanup() {
  if [ -n "$BW_DATADIR" ]; then
    bw logout >/dev/null 2>&1 || true
    rm -rf "$BW_DATADIR"
  fi
  if [ -n "$DAEMON_CTX_BAK" ] && [ -n "$DAEMON_CTX" ]; then
    mv -f "$DAEMON_CTX_BAK" "$DAEMON_CTX"
  fi
}
trap _cleanup EXIT

# The multica CLI also reads a file-based task context from
# .multica/daemon_task_context.json, which it discovers by walking UP from the
# CWD through ancestor dirs (not just the CWD). It is the on-disk twin of the
# MULTICA_* vars we just unset, so a leftover one from a prior task re-scopes the
# CLI (or makes it reject calls) and defeats the host-login fallback. Find it the
# same way the CLI does — nearest ancestor wins — move it aside for the duration
# of this script, and restore it on exit (_cleanup above).
_d="$PWD"
while [ -n "$_d" ]; do
  if [ -f "$_d/.multica/daemon_task_context.json" ]; then
    DAEMON_CTX="$_d/.multica/daemon_task_context.json"
    break
  fi
  [ "$_d" = "/" ] && break
  _d="$(dirname "$_d")"
done
if [ -n "$DAEMON_CTX" ]; then
  DAEMON_CTX_BAK="$(mktemp)"
  mv "$DAEMON_CTX" "$DAEMON_CTX_BAK"
  echo "  → moved aside stale $DAEMON_CTX (restored on exit) so CLI falls back to host login" >&2
fi

# Resolve MCP secrets from Bitwarden.
#
# Session isolation (CHA-873): the bw CLI keeps ONE active session per user
# data-dir, and every `bw unlock` mints a fresh session key that invalidates all
# prior ones for that data-dir. On this shared host other bw consumers (the
# Private-workspace sync autopilot, the datafeeds watchdog, any agent using the
# `bitwarden` skill, even an overlapping run of this same autopilot) periodically
# re-key the default data-dir, silently invalidating a BW_SESSION captured here
# mid-run — `bw get` then returns rc=0 with empty stdout and sync.py resolves
# every placeholder to None, skipping every agent fail-closed.
#
# Fix: give this run a PRIVATE BITWARDENCLI_APPDATA_DIR that no other bw consumer
# touches, log in there with the API key, unlock, and probe the vault once to
# confirm the session is live before trusting it. The isolated data-dir is
# preferred over a host-wide flock: it needs no shared lock file and can't be
# starved by a long-running peer holding the lock.
BOOTSTRAP="${BW_BOOTSTRAP:-$HOME/.claude/secrets/bw-bootstrap.env}"
if [ -f "$BOOTSTRAP" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$BOOTSTRAP"
  set +a
  export NODE_TLS_REJECT_UNAUTHORIZED=0

  # Private per-run data-dir — logged out and removed by _cleanup on exit.
  BW_DATADIR="$(mktemp -d)"
  export BITWARDENCLI_APPDATA_DIR="$BW_DATADIR"

  # config server → apikey login → unlock → sync → liveness probe, all inside the
  # isolated dir. --nointeraction makes a bad/stale session fail loud (non-zero)
  # instead of dropping to a silent `? Master password:` prompt (the CHA-873
  # signature). The `bw list items` probe confirms the session can actually
  # decrypt the vault, so a rc=0-but-broken unlock is caught here rather than
  # surfacing as "every item missing" downstream. Capture the real bw error
  # instead of swallowing it — a silently-failed unlock is what let unresolved
  # #…# placeholders get pushed over live MCP keys (CHA-790). On any failure we
  # leave BW_SESSION unset so sync.py fails closed (skips + reports every agent
  # whose config needs a secret, exits non-zero) rather than pushing placeholders.
  bw_err="$(mktemp)"
  if bw config server "$BW_HOST" >/dev/null 2>"$bw_err" \
     && bw login --apikey --nointeraction >/dev/null 2>"$bw_err" \
     && BW_SESSION="$(bw unlock --passwordenv BW_PASSWORD --raw --nointeraction 2>"$bw_err")" \
     && [ -n "$BW_SESSION" ] \
     && bw sync --session "$BW_SESSION" --nointeraction >/dev/null 2>"$bw_err" \
     && bw list items --session "$BW_SESSION" --nointeraction >/dev/null 2>"$bw_err"; then
    export BW_SESSION
    echo "  → bw session ready in isolated data-dir (survives concurrent unlocks on the host)" >&2
  else
    echo "  ERROR: bw unlock/liveness failed — MCP secret placeholders cannot be resolved." >&2
    echo "         bw reported:" >&2
    sed 's/^/           /' "$bw_err" >&2
    echo "         Continuing without BW_SESSION; sync.py will fail closed and" >&2
    echo "         SKIP (never overwrite) any agent whose config needs a secret." >&2
    unset BW_SESSION || true
  fi
  rm -f "$bw_err"
fi

# Parse --workspace without consuming positional args (sync.py needs them all).
workspace=""
prev=""
for arg in "$@"; do
  case "$arg" in
    --workspace=*) workspace="${arg#*=}" ;;
    *) if [ "$prev" = "--workspace" ]; then workspace="$arg"; fi ;;
  esac
  prev="$arg"
done

# Pre-flight guard: verify the host's active workspace matches --workspace.
# After the unset above, multica workspace get reflects the local config.
if [ -n "$workspace" ]; then
  active="$(multica workspace get --output json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('name',''))" 2>/dev/null || true)"
  if [ -n "$active" ] && [ "$active" != "$workspace" ]; then
    echo "ERROR: --workspace is '$workspace' but the host's active workspace is '$active'." >&2
    echo "       Run 'multica workspace switch $workspace' first, or set your" >&2
    echo "       MULTICA_WORKSPACE_ID (not recommended — the unset block drops it)." >&2
    exit 1
  fi
fi

python3 "$SCRIPT_DIR/sync.py" "$@"
rc=$?

if [ $rc -eq 0 ] && [ -n "$workspace" ]; then
    case "$workspace" in
      Chainlayer) md="claude-config/chainlayer/CLAUDE.md" ;;
      Private)    md="claude-config/private/CLAUDE.md" ;;
      *)          md="" ;;
    esac
    if [ -n "$md" ] && [ -f "$REPO_ROOT/$md" ]; then
      mkdir -p "$HOME/.claude"
      # Copy, don't symlink: the repo checkout lives in an ephemeral Multica
      # workdir, so a symlink into it dangles once that workdir is reaped.
      # rm -f first so we replace any pre-existing symlink (from older runs)
      # with a regular file — otherwise cp would follow it and write through to
      # the symlink's (now-stale) target instead. Last sync wins.
      rm -f "$HOME/.claude/CLAUDE.md"
      cp "$REPO_ROOT/$md" "$HOME/.claude/CLAUDE.md"
      echo "  → copied ~/.claude/CLAUDE.md ← $REPO_ROOT/$md"
    fi
    # Install nb NetBox CLI (script and install step — survives re-provisioning
    # when the sync autopilot runs after container rebuild).
    if [ -x "$REPO_ROOT/scripts/install-nb.sh" ]; then
      "$REPO_ROOT/scripts/install-nb.sh"
    fi
fi

exit $rc
