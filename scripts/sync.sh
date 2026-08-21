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
#
# MULTICA_TASK_CONFIG_ROOT and MULTICA_TASK_WORKSPACES_ROOT were added 2026-08
# (CHA-1066): the CLI resolves its config file via MULTICA_TASK_CONFIG_ROOT,
# which points at a per-task path that doesn't exist on the host, so the CLI
# fails with "No server configured" instead of falling back to
# ~/.multica/config.json.  They must be dropped alongside the other
# MULTICA_* vars.
for var in MULTICA_AGENT_ID MULTICA_AGENT_NAME MULTICA_DAEMON_PORT \
           MULTICA_SERVER_URL MULTICA_TASK_CONFIG_ROOT MULTICA_TASK_ID \
           MULTICA_TASK_SLOT MULTICA_TASK_WORKSPACES_ROOT MULTICA_TOKEN \
           MULTICA_WORKSPACE_ID; do
  unset "$var"
done

# Single EXIT cleanup for everything below (daemon-ctx restore + bw teardown).
# Both steps are opt-in: the arrays/vars stay empty until their block populates
# them, so this is a no-op if neither runs. bw teardown goes first, then the ctx
# restore, so the isolated vault is logged out and removed before we hand the
# workdir back. DAEMON_CTXS / DAEMON_CTX_BAKS are parallel arrays — one entry per
# ancestor marker we moved aside (see the walk-all-ancestors block below).
DAEMON_CTXS=(); DAEMON_CTX_BAKS=(); BW_DATADIR=""
_cleanup() {
  if [ -n "$BW_DATADIR" ]; then
    bw logout >/dev/null 2>&1 || true
    rm -rf "$BW_DATADIR"
  fi
  if [ "${#DAEMON_CTXS[@]}" -gt 0 ]; then
    for _i in "${!DAEMON_CTXS[@]}"; do
      mv -f "${DAEMON_CTX_BAKS[$_i]}" "${DAEMON_CTXS[$_i]}"
    done
  fi
}
trap _cleanup EXIT

# The multica CLI also reads a file-based task context from
# .multica/daemon_task_context.json, which it discovers by walking UP from the
# CWD through ancestor dirs (not just the CWD). It is the on-disk twin of the
# MULTICA_* vars we just unset, so a leftover one from a prior task re-scopes the
# CLI (or makes it reject calls) and defeats the host-login fallback.
#
# The CLI stops at the FIRST marker it finds, but a nested task workdir can carry
# MORE than one on its ancestor path — e.g. the task's own marker plus a stale
# one higher up under .../multica_workspaces/. Neutralising only the nearest
# leaves the higher one still re-scoping the CLI (CHA-874, surfaced during
# CHA-873's deploy where sync had to be run from /home/peter to dodge it). So
# walk ALL ancestors and move every marker aside for the duration of this
# script, restoring them all on exit (_cleanup above).
_d="$PWD"
while [ -n "$_d" ]; do
  if [ -f "$_d/.multica/daemon_task_context.json" ]; then
    _ctx="$_d/.multica/daemon_task_context.json"
    _bak="$(mktemp)"
    mv "$_ctx" "$_bak"
    DAEMON_CTXS+=("$_ctx")
    DAEMON_CTX_BAKS+=("$_bak")
    echo "  → moved aside stale $_ctx (restored on exit) so CLI falls back to host login" >&2
  fi
  [ "$_d" = "/" ] && break
  _d="$(dirname "$_d")"
done

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
     && export BW_SESSION="$(bw unlock --passwordenv BW_PASSWORD --raw --nointeraction 2>"$bw_err")" \
     && [ -n "$BW_SESSION" ] \
     && bw sync --nointeraction >/dev/null 2>"$bw_err" \
     && bw list items --nointeraction >/dev/null 2>"$bw_err"; then
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

# Which profile this HOST deploys. `--workspace` selects it when given; otherwise fall
# back to the hostname, using the same mapping check-config-freshness.sh already uses.
#
# This fallback is the fix for a silent no-op (CHA-1087): the copy below used to be gated
# on `-n "$workspace"`, so a plain `sync.sh` — the exact command the CLAUDE.md
# "once merged, run sync.sh on each host" instruction tells you to run — skipped the copy
# entirely and deployed nothing. The rule file stayed at its previous revision while the
# run reported success. Caught when a merged change to that file did not appear on the
# host and check-config-freshness.sh reported MISMATCH.
deploy_profile="$workspace"
if [ -z "$deploy_profile" ]; then
  case "$(hostname)" in
    multica-01) deploy_profile="Private" ;;
    multica-02) deploy_profile="Chainlayer" ;;
  esac
fi

if [ $rc -eq 0 ] && [ -n "$deploy_profile" ]; then
    case "$deploy_profile" in
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

# An uncommitted .sync-state.json is not cosmetic (CHA-1087). It is the record of what
# was last pushed to each workspace; leave it uncommitted and the baseline falls behind
# the live workspaces, so the NEXT unrelated change reads as "both sides changed" and a
# later run exits 2 on a conflict that is not one. That is exactly how the Private/ssh
# conflict happened. Say so here, at the moment the person who can fix it is watching.
if [ -n "$(git -C "$REPO_ROOT" status --porcelain -- .sync-state.json 2>/dev/null)" ]; then
  echo
  echo "==> ACTION REQUIRED: .sync-state.json is uncommitted."
  echo "    It records what this run pushed. Uncommitted, the baseline lags the live"
  echo "    workspaces and a future sync will report a false conflict (CHA-1087)."
  echo "    Commit it straight to main — it is generated bookkeeping, not reviewable"
  echo "    content, and the PR round-trip is friction that gets it skipped (which is"
  echo "    the staleness this warning exists to prevent). The Sync autopilot does the"
  echo "    same. The no-direct-commits rule covers rules and skill wiring, not this."
  echo "      git -C $REPO_ROOT add .sync-state.json"
  echo "      git -C $REPO_ROOT commit -m 'chore: sync state'"
  echo "      git -C $REPO_ROOT push origin main"
  echo "    check-config-freshness.sh reports this as BASELINE_LAG (exit 4) if it is"
  echo "    left behind."
fi

exit $rc
