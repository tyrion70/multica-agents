#!/usr/bin/env bash
# detect-access.sh — determine whether this host's k8s access is READONLY or WRITEABLE.
#
# Identity model: kubectl contexts point at the Tailscale operator API proxy
# (https://tailscale-operator-<cluster>.java-moth.ts.net, user "tailscale-auth").
# The Kubernetes identity is therefore the host's Tailscale login:
#   - personal login (e.g. peter@chainlayer.io) -> impersonated as that user,
#     typically system:masters (full admin)
#   - tagged device (e.g. claude-readonly-01, owner "tagged-devices") -> no
#     personal grant; such hosts carry static view-only SA kubeconfigs instead
#
# Tailscale is the hint; RBAC is authoritative. We report both.
set -uo pipefail

echo "== Tailscale identity =="
if ! command -v tailscale >/dev/null 2>&1; then
  echo "tailscale CLI not found — cannot reach cluster API proxies. ACCESS=NONE"
  exit 0
fi

TS_JSON=$(tailscale status --json 2>/dev/null) || { echo "tailscale not running. ACCESS=NONE"; exit 0; }
HOSTNAME_TS=$(jq -r '.Self.HostName' <<<"$TS_JSON")
TAGS=$(jq -r '.Self.Tags // [] | join(",")' <<<"$TS_JSON")
LOGIN=$(jq -r '.Self.UserID as $id | .User[($id|tostring)].LoginName // "unknown"' <<<"$TS_JSON")
echo "host=$HOSTNAME_TS login=$LOGIN tags=${TAGS:-none}"

HINT="WRITEABLE"
if [[ "$LOGIN" == "tagged-devices" || -n "$TAGS" ]]; then
  HINT="READONLY"
fi
echo "tailscale hint: $HINT"

echo
echo "== Per-cluster RBAC (authoritative) =="
OVERALL="UNKNOWN"
ANY_WRITE=no
ANY_READ=no
for CTX in $(kubectl config get-contexts -o name 2>/dev/null); do
  WHO=$(kubectl --context "$CTX" --request-timeout=5s auth whoami 2>/dev/null \
        | awk '$1=="Username"{print $2}')
  if [[ -z "$WHO" ]]; then
    echo "$CTX: UNREACHABLE (operator proxy not resolvable/reachable from this host)"
    continue
  fi
  CAN_WRITE=$(kubectl --context "$CTX" --request-timeout=5s auth can-i create pods -A 2>/dev/null || echo no)
  CAN_SECRETS=$(kubectl --context "$CTX" --request-timeout=5s auth can-i get secrets -A 2>/dev/null || echo no)
  ANY_READ=yes
  [[ "$CAN_WRITE" == "yes" ]] && ANY_WRITE=yes
  echo "$CTX: identity=$WHO write=$CAN_WRITE secrets=$CAN_SECRETS"
done

echo
if [[ "$ANY_READ" == "no" ]]; then
  OVERALL="NONE"
elif [[ "$ANY_WRITE" == "yes" ]]; then
  OVERALL="WRITEABLE"
else
  OVERALL="READONLY"
fi
echo "ACCESS=$OVERALL"
