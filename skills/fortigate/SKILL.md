---
name: fortigate
description: Operate ChainLayer's Fortigate core firewalls — nl2 (10.22.0.1) and no1 (10.122.0.1) — via the FortiOS API and the fortigate-iac Terraform repo. Use when reading or changing firewall address objects/groups, allowlisting k8s public IP ranges, looking up management-network CIDRs, or wiring API access. Object naming and color conventions are load-bearing for the TF/manual split.
---

# Fortigate firewalls (nl2 / no1 + fortigate-iac)

Two core firewalls, one per datacenter:

| FW | API endpoint | Mgmt network |
|---|---|---|
| **nl2** | `https://10.22.0.1:8443` | `10.22.0.0/16` |
| **no1** | `https://10.122.0.1:8443` | `10.122.0.0/16` |

## Auth / API access

- API tokens in GCP Secret Manager (project `gitlab-412312` / common
  chainlayer secrets):
  - `fortigate-automation-fg-nl2-core-api-token`
  - `fortigate-automation-fg-no1-core-api-token`
- Also available locally in `~/claude/projects/proxmox-migration/.env` as
  `FORTIOS_TOKEN_NL2` / `FORTIOS_TOKEN_NO1`.
- If a token is missing from both, look it up via the **bitwarden** skill
  (`company` folder); store newly minted tokens there too.

## IaC — `fortigate-iac`

Terraform-managed. **Object naming and color conventions are the contract that
tells TF-managed objects apart from manually-created ones** — follow them
exactly or you risk TF clobbering or orphaning objects.

### Naming conventions

| Prefix | Meaning |
|---|---|
| `A-AG-*` | Address groups (TF-managed) |
| `N-NL-*` | Network ranges |
| `A-H-*` | Hosts |
| `A-EXT-*` | External hosts |

### Color conventions

| Color | Object kind |
|---|---|
| 18 | addresses (sky-500) |
| 21 | TF-managed addresses (violet-200) |
| 22 | address groups — TF-managed (purple-200) |
| 23 | address groups — manual (purple-200) |

### Comment convention

TF-managed objects carry a two-line comment:

```
<context>
Managed by Terraform
```

## k8s public-IP allowlisting

The nl-oven cluster's P2P LoadBalancers sit on public IPs in
`176.103.222.0/23` / `176.103.223.0/24` (the k8s public-IP pool). These are
allowlisted in Fortigate via the address group **`A-AG-NL-K8S-PUBLIC-RANGES`**.

Related cluster egress to keep in mind when writing rules:

- **nl-oven cluster egress NAT IP: `89.149.216.9`** — use this to
  firewall-restrict external mirrors so only the cluster can pull. Also the
  ChainLayer corporate outbound NAT IP.

## Relevant IP scheme (chainlayer bare-metal)

| Prefix | DC / role |
|---|---|
| `176.103.222.0/23` + `176.103.223.0/24` | NL2 Worldstream — bare-metal chain VMs + k8s public-IP pool |
| `86.111.48.0/24` | NO1 Oslo bare-metal |
| `10.22.0.0/16` | nl2 management (Fortigate `10.22.0.1`) |
| `10.122.0.0/16` | no1 management (Fortigate `10.122.0.1`) |
| `10.3.x.x` | nl-oven pod / LB CIDRs |
| `89.149.216.9` | nl-oven cluster egress NAT / corporate egress |

## Terraform drift note

When Fortigate subnets are managed via the `proxmox-iac` Terraform (VM network
options reference Fortigate subnet objects), the **fortios subnet format** can
show up as one-time drift on a `tofu plan` — it applies clean once. See the
**company-proxmox** skill's drift catalog. Always `tofu fmt -recursive` before
committing.

## Permission model

✅ Without asking: GET reads of address objects / groups / policies via the
FortiOS API, token lookups.

🔶 GitOps: address/group/policy changes go through the `fortigate-iac` repo
(Linear issue first — **linear-company** skill; MR rules — **git-mr** skill).
Respect the naming + color conventions so TF and manual objects stay distinct.

🛑 Ask first: any write through the FortiOS API directly (bypassing
`fortigate-iac`), editing firewall policies, or changing allowlist ranges
(`A-AG-NL-K8S-PUBLIC-RANGES` and friends gate live cluster traffic).
