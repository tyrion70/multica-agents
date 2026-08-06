---
name: Chainlayer Proxmox cluster endpoints (Prox7 / Prox9)
description: Work-cluster API endpoints — distinct from the homelab proxmox1-4 cluster
type: reference
originSessionId: b92ba0c7-ac87-4f2a-bd9e-7f7d30d71d3c
---
The chainlayer **work** Proxmox clusters are reachable at:

- **Prox7** → `https://10.24.0.16:8006`
- **Prox9** → `https://10.34.0.163:8006`

The homelab cluster (4-node `proxmox1..4`, master `192.168.16.200`) is a
**separate** environment hosting personal/lab workloads — including
`claude-workstation-01` and `claude-readonly-01`. The upstream
`tyrion70/claude-workstation-vm` README references `192.168.16.200` for
VM cloning, which is the homelab master, not Prox7.

Don't confuse them: when the task is "mint a Proxmox API token for
chainlayer infra", the endpoint is one of the `10.x.x.x` IPs above.
When the task is "clone the workstation VM", the endpoint is the
homelab master at `192.168.16.200`.
