#!/usr/bin/env bash
set -euo pipefail

# CLIProxyAPI — install the local Anthropic-compatible endpoint and the
# claude-cliproxy wrapper a Multica runtime profile points at.
#
# Why this exists: the multica-02 install was done by hand and lived in exactly
# one place, on one machine, with no way to reproduce it. Every Claude agent in
# the workspace now dispatches through that wrapper, so a wiped ~/.local/bin
# takes the whole Claude fleet offline with a symptom that does not obviously
# point at a missing 20-line shell script (CHA-1149).
#
# What it installs:
#   ~/cliproxyapi/cli-proxy-api                  pinned release, sha256-verified
#   ~/.cli-proxy-api/config.yaml                 0600, localhost-only
#   ~/.local/bin/claude-cliproxy                 the wrapper Multica launches
#   ~/.config/systemd/user/cliproxyapi.service   Linux only
#
# What it does NOT do:
#   - log in. Filling the auth pool needs a browser and is a human step; the
#     command is printed at the end.
#   - overwrite an existing config.yaml. That file holds the inbound API key,
#     and clobbering it would silently break every wrapper already using the
#     old key. Pass --force-config to rewrite it (a new key is generated).
#   - touch the auth-dir credentials. Never.
#
# Usage:
#   scripts/install-cliproxy.sh                  # install / upgrade in place
#   scripts/install-cliproxy.sh --force-config    # also rewrite config.yaml
#   scripts/install-cliproxy.sh --no-service      # binary + wrapper only
#
# Multica side, after this script and the login:
#   multica agent update <agent-id> --runtime-id <Claude via CLIProxy runtime>

CLIPROXY_VERSION="7.2.155"

# From the release's own checksums.txt, not computed locally.
declare -A CLIPROXY_SHA256=(
  [linux_amd64]="5eb8e1ab3f90aa22e4843d0c881f113d4e359a8cb3d3ec130a53e356060be730"
  [linux_aarch64]="bd5f6b705124e4af160b1d236e6739bbcd10b7c76d0c5dda96095ec19f38d5e7"
  [darwin_amd64]="198794a2fafb9fb8083476ac18232647c57d443422aa3f008d19ed7e75ca4604"
  [darwin_aarch64]="f90c503ce41a798c85b6f61dfe5fe8b812c1b889634f0c80d04ee376424fe305"
)

INSTALL_DIR="${HOME}/cliproxyapi"
CONFIG_DIR="${HOME}/.cli-proxy-api"
CONFIG="${CONFIG_DIR}/config.yaml"
WRAPPER="${HOME}/.local/bin/claude-cliproxy"
UNIT_DIR="${HOME}/.config/systemd/user"
UNIT="${UNIT_DIR}/cliproxyapi.service"
LISTEN_HOST="127.0.0.1"
# Overridable so the script can be exercised against a throwaway HOME without
# touching a live instance; the fleet default is the only one anything expects.
LISTEN_PORT="${CLIPROXY_PORT:-8317}"

FORCE_CONFIG=0
WANT_SERVICE=1

die() { echo >&2 "error: $*"; exit 1; }
info() { echo "==> $*"; }
note() { echo "    $*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --force-config) FORCE_CONFIG=1 ;;
    --no-service)   WANT_SERVICE=0 ;;
    -h|--help)      sed -n '3,40p' "$0"; exit 0 ;;
    *)              die "unknown argument: $1 (see --help)" ;;
  esac
  shift
done

# --- platform ----------------------------------------------------------
case "$(uname -s)" in
  Linux)  OS="linux" ;;
  Darwin) OS="darwin" ;;
  *)      die "unsupported OS: $(uname -s)" ;;
esac
case "$(uname -m)" in
  x86_64|amd64)  ARCH="amd64" ;;
  arm64|aarch64) ARCH="aarch64" ;;
  *)             die "unsupported architecture: $(uname -m)" ;;
esac
PLATFORM="${OS}_${ARCH}"
SHA="${CLIPROXY_SHA256[$PLATFORM]:-}"
[ -n "$SHA" ] || die "no pinned checksum for ${PLATFORM}"

# launchd, not systemd. Installing a unit here would be a file nothing reads.
if [ "$OS" = "darwin" ] && [ "$WANT_SERVICE" = 1 ]; then
  WANT_SERVICE=0
  DARWIN_NO_SERVICE=1
fi

info "CLIProxyAPI ${CLIPROXY_VERSION} (${PLATFORM})"

if command -v sha256sum >/dev/null 2>&1; then
  sha_cmd() { sha256sum "$1" | cut -d' ' -f1; }
elif command -v shasum >/dev/null 2>&1; then
  sha_cmd() { shasum -a 256 "$1" | cut -d' ' -f1; }
else
  die "need sha256sum or shasum to verify the download"
fi
command -v curl >/dev/null 2>&1 || die "need curl"
command -v openssl >/dev/null 2>&1 || die "need openssl to generate the API key"

# One scratch dir for the whole run, cleaned on any exit. Not a predictable
# /tmp name: this script runs on shared machines, and `curl -o` happily follows
# a symlink someone else planted there first.
TMP="$(mktemp -d)"
# shellcheck disable=SC2064
trap "rm -rf '$TMP'" EXIT

# --- binary ------------------------------------------------------------
installed=""
if [ -x "${INSTALL_DIR}/cli-proxy-api" ]; then
  # There is no --version flag: the binary prints its version banner and then
  # exits 2 on the unknown flag. The banner is what we want, so swallow the
  # status -- under `set -o pipefail` an unguarded 2 here aborts the script.
  # lint:fail-open-ok exit status carries no information, the banner does
  installed="$( ("${INSTALL_DIR}/cli-proxy-api" --config /dev/null --version 2>/dev/null || true) \
    | sed -n 's/.*Version: \([0-9.]*\).*/\1/p' | head -1)"
fi

if [ "$installed" = "$CLIPROXY_VERSION" ]; then
  info "binary already at ${CLIPROXY_VERSION}, leaving it alone"
else
  TARBALL="CLIProxyAPI_${CLIPROXY_VERSION}_${PLATFORM}.tar.gz"
  URL="https://github.com/router-for-me/CLIProxyAPI/releases/download/v${CLIPROXY_VERSION}/${TARBALL}"
  info "downloading ${TARBALL}"
  curl -fsSL -o "${TMP}/${TARBALL}" "$URL" || die "download failed: $URL"

  got="$(sha_cmd "${TMP}/${TARBALL}")"
  # Verified BEFORE extraction: a tarball that fails this is never unpacked.
  [ "$got" = "$SHA" ] || die "checksum mismatch for ${TARBALL}
  expected ${SHA}
  got      ${got}"
  info "sha256 verified"

  mkdir -p "$INSTALL_DIR"
  tar -xzf "${TMP}/${TARBALL}" -C "$INSTALL_DIR"
  chmod 0755 "${INSTALL_DIR}/cli-proxy-api"
  info "installed ${INSTALL_DIR}/cli-proxy-api"
fi

# --- config ------------------------------------------------------------
mkdir -p "$CONFIG_DIR"
chmod 0700 "$CONFIG_DIR"

if [ -f "$CONFIG" ] && [ "$FORCE_CONFIG" = 0 ]; then
  info "config exists, keeping it (--force-config to rewrite)"
  chmod 0600 "$CONFIG"
else
  [ -f "$CONFIG" ] && cp -a "$CONFIG" "${CONFIG}.bak.$(date +%s)"
  API_KEY="$(openssl rand -hex 32)"
  umask 077
  cat > "$CONFIG" <<EOF
# Managed by multica-agents scripts/install-cliproxy.sh — do not hand-edit the
# parts below without reading that script; --force-config rewrites this file
# and rotates the API key, which every claude-cliproxy wrapper reads at runtime.

# 127.0.0.1, NOT the shipped default. config.example.yaml has host: "" which
# binds every interface -- on a box inside ChainLayer's advertised tailnet
# ranges that publishes a Claude subscription to anything that can route to it.
host: "${LISTEN_HOST}"
port: ${LISTEN_PORT}

tls:
  enable: false

# Off. This is the surface that can rewrite auth at runtime, including
# replacing the whole config. An empty secret-key 404s every management route.
remote-management:
  allow-remote: false
  secret-key: ""
  disable-control-panel: true

auth-dir: "${CONFIG_DIR}"

# The inbound key. Callers are an allowlist of strings with no binding to an
# upstream credential -- anything holding this key can use any account in the
# pool. That is why the listener is localhost-only.
api-keys:
  - "${API_KEY}"

# On from the start, not retroactively: with round-robin across several
# accounts, nothing else records which account served which request, and a
# usage record enabled after the fact answers nothing about what already ran.
usage-statistics-enabled: true

debug: false
logging-to-file: false
EOF
  chmod 0600 "$CONFIG"
  info "wrote ${CONFIG} (0600, new API key)"
fi

# The key is read from the config rather than held here, so a rotation in the
# config is a rotation everywhere and no key is ever passed in argv.
read_key() {
  awk '/^api-keys:/{f=1;next} f&&/^[[:space:]]*-/{gsub(/^[[:space:]]*-[[:space:]]*"?|"?[[:space:]]*$/,"");print;exit}' "$CONFIG"
}
KEY="$(read_key)"
[ -n "$KEY" ] || die "no api-keys entry in ${CONFIG}"

# Any credential already in the auth dir stays put; only the mode is corrected.
# 0644 on an OAuth token leaves the directory mode as the only control, and
# that does not survive the file being copied anywhere.
if compgen -G "${CONFIG_DIR}"/*.json >/dev/null; then
  chmod 0600 "${CONFIG_DIR}"/*.json
fi

# --- wrapper -----------------------------------------------------------
mkdir -p "$(dirname "$WRAPPER")"
cat > "$WRAPPER" <<WRAP
#!/usr/bin/env bash
# Claude Code, routed through the local CLIProxyAPI instead of its own login.
# Installed by multica-agents scripts/install-cliproxy.sh -- edit there.
#
# Multica has no "CLIProxy provider" to select, and shouldn't: CLIProxyAPI is a
# drop-in Anthropic-compatible endpoint, not a backend. Claude Code already
# knows how to talk to one -- it just needs to be told where. That is all this
# wrapper does, so a Multica runtime profile can point at it by name.
#
# The key is read from the 0600 config at call time rather than baked in here or
# passed as an argument: a value in argv is visible to anyone running ps.
set -euo pipefail

CONFIG="\${CLIPROXY_CONFIG:-\$HOME/.cli-proxy-api/config.yaml}"
[[ -r "\$CONFIG" ]] || { echo "claude-cliproxy: cannot read \$CONFIG" >&2; exit 1; }

KEY="\$(awk '/^api-keys:/{f=1;next} f&&/^[[:space:]]*-/{gsub(/^[[:space:]]*-[[:space:]]*"?|"?[[:space:]]*\$/,"");print;exit}' "\$CONFIG")"
[[ -n "\$KEY" ]] || { echo "claude-cliproxy: no api-keys entry in \$CONFIG" >&2; exit 1; }

# Fail loudly rather than silently falling back to the subscription login: a
# wrapper that quietly stops proxying looks identical to one that works, and
# you would never know the pooled accounts were not being used.
if ! curl -fsS -o /dev/null --max-time 5 \\
     -H "Authorization: Bearer \$KEY" http://${LISTEN_HOST}:${LISTEN_PORT}/v1/models; then
  echo "claude-cliproxy: CLIProxyAPI is not answering on ${LISTEN_HOST}:${LISTEN_PORT}" >&2
  echo "  systemctl --user status cliproxyapi" >&2
  exit 1
fi

export ANTHROPIC_BASE_URL="http://${LISTEN_HOST}:${LISTEN_PORT}"
# Header, not a query string: the endpoint also accepts ?key= / ?auth_token=,
# which would put the credential into access logs and shell history.
export ANTHROPIC_AUTH_TOKEN="\$KEY"
# Would take precedence over ANTHROPIC_AUTH_TOKEN and send the wrong credential.
unset ANTHROPIC_API_KEY

# Claude Code only defers MCP tool definitions behind its ToolSearch tool when
# it recognises a first-party Anthropic host. Behind this proxy it does not, so
# it inlines every schema instead -- 323 tools is ~246k tokens of prompt before
# the first user message, and every run dies "Prompt is too long". Its own log
# line names the fix, conditional on the proxy forwarding tool_reference blocks;
# CLIProxyAPI does (tool_search_tool_bm25 round-trips through it end to end).
export ENABLE_TOOL_SEARCH=true

exec claude "\$@"
WRAP
chmod 0755 "$WRAPPER"
info "installed ${WRAPPER}"

# --- service -----------------------------------------------------------
if [ "$WANT_SERVICE" = 1 ]; then
  mkdir -p "$UNIT_DIR"
  cat > "$UNIT" <<EOF
[Unit]
Description=CLIProxyAPI (Claude/Codex subscription -> OpenAI/Anthropic compatible API)
Documentation=https://help.router-for.me/
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=%h/cliproxyapi/cli-proxy-api --config %h/.cli-proxy-api/config.yaml
WorkingDirectory=%h/cliproxyapi
Restart=on-failure
RestartSec=5
# The process holds a Claude subscription OAuth token; keep the blast radius small.
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=%h/.cli-proxy-api
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictRealtime=true
LockPersonality=true
# NOT ProtectKernelModules=true - an unprivileged --user manager cannot drop
# CAP_SYS_MODULE from the bounding set, so the unit dies 218/CAPABILITIES
# before ExecStart. Bisected on multica-02, 2026-09-09.
MemoryMax=1G

[Install]
WantedBy=default.target
EOF
  info "installed ${UNIT}"

  systemctl --user daemon-reload
  systemctl --user enable --now cliproxyapi.service
  systemctl --user restart cliproxyapi.service

  # Without lingering the proxy dies on logout and every agent pointed at it
  # fails on its next dispatch -- with the runtime still reading online.
  if ! [ -e "/var/lib/systemd/linger/${USER}" ]; then
    note "WARNING: lingering is off for ${USER} — the proxy will not survive logout."
    note "         sudo loginctl enable-linger ${USER}"
  fi
fi

# --- verify ------------------------------------------------------------
info "verifying the endpoint"
ok=0
for _ in $(seq 1 15); do
  # 2>/dev/null: a not-yet-listening socket during the retry window is
  # expected, and 15 connection-refused lines read like a failure.
  if curl -fsS -o "${TMP}/models.json" --max-time 5 \
       -H "Authorization: Bearer ${KEY}" \
       "http://${LISTEN_HOST}:${LISTEN_PORT}/v1/models" 2>/dev/null; then ok=1; break; fi
  sleep 1
done

if [ "$ok" != 1 ]; then
  if [ "${DARWIN_NO_SERVICE:-0}" = 1 ]; then
    note "not running — macOS has no systemd, start it yourself:"
    note "  ${INSTALL_DIR}/cli-proxy-api --config ${CONFIG}"
    note "(then re-run this script to verify, or wire a launchd agent)"
    exit 0
  fi
  die "endpoint not answering on ${LISTEN_HOST}:${LISTEN_PORT}
  systemctl --user status cliproxyapi
  journalctl --user -u cliproxyapi -n 50"
fi

# A parse failure here is a real answer, not a cosmetic one: the endpoint
# answered 200 with something that is not the model list, which is exactly the
# state the wrapper's preflight cannot distinguish from a healthy proxy.
if ! models="$(python3 -c "
import json
d = json.load(open('${TMP}/models.json'))
print(len(d.get('data', [])))
" 2>/dev/null)"; then
  die "endpoint answered but /v1/models was not the expected JSON:
$(head -c 400 "${TMP}/models.json")"
fi

# Auth enforcement is asserted, not assumed: a listener that answers without a
# key is worse than one that is down, and looks identical from the wrapper.
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
  "http://${LISTEN_HOST}:${LISTEN_PORT}/v1/models")"
[ "$code" = "401" ] || die "endpoint answered ${code} with NO credential (expected 401)"

info "endpoint up, auth enforced, ${models} model(s) advertised"

if [ "$models" = "0" ]; then
  cat <<EOF

    The auth pool is EMPTY — nothing can be served yet. Logging in needs a
    browser, so it is a human step, once per account:

      cd ${INSTALL_DIR} && ./cli-proxy-api --config ${CONFIG} --claude-login --no-browser

    Two non-obvious things about it:
      * No SSH tunnel needed. After ~15s it prompts for the callback URL —
        open the printed link, authorise, let the browser fail to load
        localhost:54545, and paste that URL back.
      * If it complains about "port 3000", ignore the 3000. That string is
        hardcoded upstream; the port it actually checks is 54545.

    Logging in twice with two accounts on ONE host overwrites the same
    claude-<email>.json when the email matches. Rename the first file before
    the second login if you want both accounts pooled.

    Then re-run this script to see the model count, and point agents at the
    "Claude via CLIProxy" runtime with:
      multica agent update <agent-id> --runtime-id <runtime-id>
EOF
else
  note "wrapper: ${WRAPPER}"
  note "accounts pooled: $(ls -1 "${CONFIG_DIR}"/claude-*.json 2>/dev/null | wc -l | tr -d ' ')"
  note "round-robin has no per-request attribution — every pooled account"
  note "serves an arbitrary share of the traffic. Keep personal and company"
  note "accounts in separate pools if that distinction matters."
fi
