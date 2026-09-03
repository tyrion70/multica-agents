#!/usr/bin/env bash
#
# new-network — orchestration glue for the "Spin Up a Network (VM RPC)" runbook.
#
#   new-network <network> --client <client> [--snapshot-url <url>] [options]
#
# Drives Steps 1–8 of documentation:docs/operations/spin-up-a-network.md end to
# end: existence check → snapshot discovery/sizing → gitlab-iac MR → proxmox-iac
# MR → <network>-infra pipeline → haproxy MR → monitoring2 MR → smoke test.
#
# This is *glue*, not new deploy mechanics. Steps 3/4/5/6/7 are already IaC/
# pipeline-driven; this script sequences them, calls the documented per-network
# snapshot commands (NOT an Ansible role), and runs the terminal smoke test. The
# actual infra changes land as reviewed MRs — the mutating steps open an MR and
# stop at the merge boundary (apply happens on merge). Read-only steps (1, 2,
# smoke test) run live.
#
# --dry-run produces the complete ordered artifact/MR list with zero side effects
# and zero clarifying questions — this is the Stage-3 validation deliverable.
#
# Scope: ends at a live, syncing, publicly-reachable RPC node. Chainlink/DON/
# oracle config is out of scope (Joakim's handoff).
#
set -euo pipefail

# ── Constants (single source of truth; mirror the runbook) ───────────────────
SNAPSHOT_BASE="http://quicksync-2a-nl2m.chosts.io:9000/chainlink"  # RustFS, port 9000, bucket "chainlink"
RPC_DOMAIN_SUFFIX="rpc.cinternal.com"                               # <network>.rpc.cinternal.com — grey-cloud DNS-only wildcard
DEFAULT_CLUSTER="nl2_c4"   # Prox9 — new VMs go here; Prox7/Norway/de2 are EOL
DEFAULT_SITE="nl2"
GITLAB_GROUP="chainlayer"

# ── Args ─────────────────────────────────────────────────────────────────────
NETWORK="" ; CLIENT="" ; SNAPSHOT_URL="" ; DRY_RUN=0
CLUSTER="$DEFAULT_CLUSTER" ; SITE="$DEFAULT_SITE"

usage() {
  sed -n '3,8p' "$0" | sed 's/^# \{0,1\}//'
  cat <<'EOF'

Options:
  --client <name>        Node software (reth, geth, …). Required.
  --snapshot-url <url>   Override with a direct archive URL (default: resolve <network>/latest.json).
  --cluster <dir>        proxmox-iac cluster dir (default: nl2_c4 / Prox9).
  --site <site>          monitoring2/haproxy site (default: nl2).
  --dry-run              Print the full artifact/MR plan; no side effects.
  -h, --help             This help.
EOF
}

if [[ $# -eq 0 ]]; then usage; exit 2; fi
# Flags may appear in any order relative to the positional <network> — the first
# bare (non-flag) token is the network, so `--dry-run <network> …` works too.
while [[ $# -gt 0 ]]; do
  case "$1" in
    --client)       CLIENT="${2:-}"; shift 2 ;;
    --snapshot-url) SNAPSHOT_URL="${2:-}"; shift 2 ;;
    --cluster)      CLUSTER="${2:-}"; shift 2 ;;
    --site)         SITE="${2:-}"; shift 2 ;;
    --dry-run)      DRY_RUN=1; shift ;;
    -h|--help)      usage; exit 0 ;;
    --*) echo "unknown option: $1" >&2; usage; exit 2 ;;
    *)
      if [[ -z "$NETWORK" ]]; then NETWORK="$1"; shift
      else echo "unexpected argument: $1 (network already set to '$NETWORK')" >&2; usage; exit 2; fi ;;
  esac
done

[[ -n "$NETWORK" ]] || { echo "error: <network> is required" >&2; exit 2; }
[[ -n "$CLIENT"  ]] || { echo "error: --client is required" >&2; exit 2; }
# Normalise: the slug is reused for the NetBox tag, the repo, and the backend.
[[ "$NETWORK" =~ ^[a-z0-9-]+$ ]] || { echo "error: network slug must be [a-z0-9-]" >&2; exit 2; }
# No fixed 'latest.tar.zst' object — the default is the per-network manifest, resolved at
# run time for the real object(s) + format. --snapshot-url overrides with a direct archive URL.
MANIFEST_URL="${SNAPSHOT_BASE}/${NETWORK}/latest.json"

RPC_URL="https://${NETWORK}.${RPC_DOMAIN_SUFFIX}/"
VM_NAME="${NETWORK}-main-rpc-1a-${SITE}v"
INFRA_REPO="git@gitlab.com:${GITLAB_GROUP}/nodes/${NETWORK}-infra.git"

log()  { printf '\n\033[1;34m▶ %s\033[0m\n' "$*"; }
step() { printf '\n\033[1;36m═══ %s ═══\033[0m\n' "$*"; }
note() { printf '   %s\n' "$*"; }
gate() {
  # Human-review boundary: infra applies on MR merge. Never auto-merged here.
  if [[ "$DRY_RUN" -eq 1 ]]; then note "[dry-run] would wait for MR merge: $*"; return 0; fi
  echo ""
  read -r -p "   ↳ merge the MR above, then press ENTER to continue ($*) " _
}

# ── Step 1 — Existence check (gate) ──────────────────────────────────────────
# Absent from all authoritative sources → provision. Present in any → record + close.
# NOTE: DNS is NOT an existence signal. `*.rpc.cinternal.com` is a grey-cloud
# wildcard that resolves for every <network> whether or not it exists, so a
# `dig` hit is meaningless here — checking it would false-positive every new
# network and wrongly close the onboarding. Gate on the four authoritative
# sources instead.
existence_check() {
  step "Step 1 — Existence check for '${NETWORK}'"
  local hits=()
  command -v nb >/dev/null 2>&1 && nb "$NETWORK" 2>/dev/null | grep -qi "$NETWORK" && hits+=("NetBox")
  [[ -d proxmox-iac ]] && ls proxmox-iac/clusters/*/vms-"${NETWORK}".tf >/dev/null 2>&1 && hits+=("proxmox-iac")
  command -v glab >/dev/null 2>&1 && glab repo view "${GITLAB_GROUP}/nodes/${NETWORK}-infra" >/dev/null 2>&1 && hits+=("<network>-infra repo")
  [[ -f haproxy/backends.yaml ]] && grep -q "name: ${NETWORK}\b" haproxy/backends.yaml 2>/dev/null && hits+=("haproxy backend")

  if [[ ${#hits[@]} -gt 0 ]]; then
    log "STOP: '${NETWORK}' already exists in: ${hits[*]}"
    note "Record where it lives and CLOSE the issue — no provisioning. (cf. Plasma.)"
    exit 3
  fi
  note "Absent from NetBox / proxmox-iac / infra repo / haproxy → proceed."
  note "(DNS not checked: *.rpc.cinternal.com is a grey-cloud wildcard, resolves for all.)"
}

# ── Step 2 — Snapshot discovery & disk sizing ────────────────────────────────
# Documented per-network commands (NOT a role): curl -f | tar, .bootstrapped on
# success only, no in-pipe --retry.
DISK_GB=""
snapshot_discover() {
  step "Step 2 — Snapshot discovery & disk sizing"
  local bytes="" key="" fmt="" parts=""
  if [[ -n "$SNAPSHOT_URL" ]]; then
    # Explicit override — a direct archive URL (e.g. a public provider). Size from HEAD.
    note "Snapshot URL (override): ${SNAPSHOT_URL}"
    bytes=$(curl -fsSI --connect-timeout 5 --max-time 15 "$SNAPSHOT_URL" 2>/dev/null | tr -d '\r' | awk 'tolower($1)=="content-length:"{print $2}')
  else
    # Default — resolve the per-network manifest (no fixed latest.tar.zst). The manifest
    # gives object path(s), archive format, and exact bytes (better than a HEAD guess).
    note "Manifest: ${MANIFEST_URL}"
    local snap=""
    if snap=$(curl -fsS --connect-timeout 5 --max-time 20 "$MANIFEST_URL" 2>/dev/null); then
      # Two shapes: array ({files:[…]}, multi-part) or flat ({path,format,bytes}); (.files // [.]) normalises both.
      bytes=$(printf '%s' "$snap" | jq -r '[ (.files // [.])[].bytes ] | add // empty' 2>/dev/null)
      key=$(printf '%s'   "$snap" | jq -r '(.files // [.])[0].path   // empty' 2>/dev/null)
      fmt=$(printf '%s'   "$snap" | jq -r '(.files // [.])[0].format // empty' 2>/dev/null)
      parts=$(printf '%s' "$snap" | jq -r '(.files // [.]) | length'  2>/dev/null)
      [[ -n "$key" ]] && note "Resolved: ${key} (format ${fmt}, ${parts} object(s))"
    fi
  fi
  if [[ -z "$bytes" ]]; then
    note "⚠ snapshot manifest not reachable / no size (jq required for manifest parsing)."
    note "  → confirm the network prefix in the bucket: curl \"${SNAPSHOT_BASE}/?prefix=${NETWORK}/\""
    note "    or pass --snapshot-url, or (no snapshot) record the expected unpacked size for sizing."
    [[ "$DRY_RUN" -eq 1 ]] || { echo "   abort: resolve the snapshot first" >&2; exit 4; }
    DISK_GB="__DISK_GB__ (TODO: no snapshot — record expected unpacked size)"
    return 0
  fi
  local comp_gb=$(( (bytes + 1073741823) / 1073741824 ))
  # Compressed snapshots unpack ~3–4×; size the data disk from unpacked + headroom.
  local disk=$(( comp_gb * 4 + 100 ))
  DISK_GB="$disk"
  note "Compressed ≈ ${comp_gb} GiB → data-disk estimate ≈ ${DISK_GB} GiB (unpacked×4 + 100 headroom)."
  note "The documented bootstrap the node/CI runs (object(s) + format resolved from the manifest — never hardcode zstd):"
  note '  set -euo pipefail'
  note '  # read latest.json -> per-object path + format -> matching --use-compress-program'
  note '  # full resolver: snapshot-bootstrap.md#standard-snapshot-bootstrap-commands-per-network'
  note "  curl -f \"${SNAPSHOT_BASE}/${NETWORK}/<object-from-manifest>\" | tar --use-compress-program=<lib> -x -C /data"
  note '  touch /data/.bootstrapped   # on SUCCESS only'
}

# ── Steps 3–8 — reviewed MRs (apply on merge) ────────────────────────────────
step3_gitlab_iac() {
  step "Step 3 — <network>-infra repo via gitlab-iac"
  note "Repo:  gitlab-iac (main.tf)"
  note "Add:   gitlab_project \"network_${NETWORK}_infra\" (namespace chainlayer/nodes, private) + CI/IAM"
  note "Seed:  .gitlab-ci.yml (include cicd/templates + extends/ansible-playbook.yml),"
  note "       inventories/01-netbox.yml, deploy-rpc.yml, job mainnet-rpc-deploy"
  note "       (ANSIBLE_LIMIT: ${NETWORK}:&mainnet:&rpc). NO Jenkinsfile. Seed from polygon-infra."
  note "MR → tofu apply on merge → repo exists at ${INFRA_REPO}"
  gate "gitlab-iac apply creates ${NETWORK}-infra"
}

step4_proxmox_iac() {
  step "Step 4 — Provision VM (proxmox-iac) + placement"
  note "Repo:  proxmox-iac (clusters/${CLUSTER}/vms-${NETWORK}.tf)"
  note "Module: modules/proxmox_vm_ubuntu  vm_name=${VM_NAME}"
  note "        vm_data_disk_size = ${DISK_GB}   # from Step 2c"
  note "        vm_host = local.vm_hosts.__PLACEMENT__   # ▶ Peter's capacity data (non-blocking TODO)"
  note "        netbox_tags = [ansible, mainnet, rpc, healthcheck, ${NETWORK}]  (register tag first)"
  note "Module also wires NetBox IP+registration, Cloudflare DNS, FortiGate, Alloy agent."
  note "Run tofu fmt -recursive; MR → tofu apply on merge."
  gate "proxmox-iac apply creates VM ${VM_NAME}"
}

step5_infra_pipeline() {
  step "Step 5 — Configure node (<network>-infra pipeline via CI)"
  note "deploy-rpc.yml runs the RPC role + the documented snapshot-bootstrap commands"
  note "(curl -f | tar, .bootstrapped on success only) — not a role."
  note "Trigger: mainnet-rpc-deploy CI job on main (glab ci run -R ${GITLAB_GROUP}/nodes/${NETWORK}-infra)."
  if [[ "$DRY_RUN" -eq 0 ]] && command -v glab >/dev/null 2>&1; then
    note "→ glab ci run -R ${GITLAB_GROUP}/nodes/${NETWORK}-infra (skipped until VM + repo exist)"
  fi
  note "Local done-check on the node: eth_blockNumber climbs between calls (catching up is fine)."
}

step6_haproxy() {
  step "Step 6 — Expose RPC via HAProxy"
  note "Repo:  haproxy (backends.yaml) — add services[] entry:"
  note "         name: ${NETWORK}; channels[0]={port:8545, ws_upgrade:true, ws_port:8546,"
  note "         check_port:\"check port 11001\"}; internal.nodes=[{name:${VM_NAME}.chosts.io, ip:<vm-ip>, location:${SITE^^}}]"
  note "Also:  monitoring2 configuration/sites/${SITE}/targets/haproxy-network.yml + haproxy-node-exporter.yml"
  note "CI deploys in waves (NO1 → NL2). MR → merge."
  gate "haproxy backend for ${NETWORK} deployed"
}

step7_monitoring() {
  step "Step 7 — Monitoring (monitoring2)"
  note "NetBox-tag discovery (file_sd) picks up tags ${NETWORK}/mainnet/rpc automatically."
  note "Static jobs only if needed: group_vars/${SITE}_prometheus/static_configs.yml"
  note "Alert rule keyed on chainlayer_network in .../node-agent.rules.yml (priority p2/p3). MR → merge."
  gate "monitoring2 target UP + alert rule live"
}

step8_docs() {
  step "Step 8 — Documentation"
  note "Repo:  documentation — scaffold docs/networks/${NETWORK}/ from docs/templates/:"
  note "         index.md, common-issues.md, upgrades.md, VALIDATION-CHECKLIST.md (+ ALERTS-INVENTORY.md)"
  note "Fill owner/ChainID/RPC/${NETWORK}-infra link/Grafana. MR → merge publishes."
}

# ── Smoke test — the terminal done-check ─────────────────────────────────────
smoke_test() {
  step "Smoke test — terminal done-check against ${RPC_URL}"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    note "[dry-run] would assert correct eth_chainId + strictly-advancing eth_blockNumber at ${RPC_URL}"
    return 0
  fi
  local body='{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}'
  local h='content-type: application/json'
  local cid b1 b2
  # -k: <network>.rpc.cinternal.com is grey-cloud (DNS-only) and the origin serves a
  # *.quickapi.com Origin-CA cert, not a browser-trusted public cert — so run this
  # from inside the network (Tailscale) and skip TLS verification.
  cid=$(curl -sk "$RPC_URL" -H "$h" -d '{"jsonrpc":"2.0","method":"eth_chainId","params":[],"id":1}' | grep -o '"result":"[^"]*"' || true)
  b1=$(curl -sk "$RPC_URL" -H "$h" -d "$body" | grep -o '"result":"[^"]*"' || true)
  sleep 10
  b2=$(curl -sk "$RPC_URL" -H "$h" -d "$body" | grep -o '"result":"[^"]*"' || true)
  note "chainId=${cid:-<none>}  block1=${b1:-<none>}  block2=${b2:-<none>}"
  if [[ -n "$cid" && -n "$b1" && -n "$b2" && "$b1" != "$b2" ]]; then
    log "✅ DONE — RPC answers with a chain id and an advancing head."
  else
    echo "   ❌ smoke test FAILED — RPC not answering or head not advancing." >&2
    exit 5
  fi
}

# ── Drive ────────────────────────────────────────────────────────────────────
log "new-network ${NETWORK} --client ${CLIENT}$([[ "$DRY_RUN" -eq 1 ]] && echo '  (dry-run: plan only, no side effects)')"
existence_check
snapshot_discover
step3_gitlab_iac
step4_proxmox_iac
step5_infra_pipeline
step6_haproxy
step7_monitoring
step8_docs
smoke_test
log "new-network ${NETWORK}: flow complete."
