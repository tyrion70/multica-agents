---
name: Proxmox TF persistent drift on imported VMs (mtu, dns, comment, vga, subnet)
description: Catalog of in-place updates that keep showing on every plan for imported/relocated VMs, what causes each, whether apply actually fixes them, and the one-shot API command to clear the underlying state on Proxmox so the drift goes away
type: feedback
originSessionId: 9fbf0170-b405-4e85-80f9-b25d22615a9d
---
After importing or `state mv`-ing a VM into the BPG-provider TF modules (`proxmox_vm_ubuntu` / `proxmox_vm_ubuntu_protected`), the first plan typically shows several in-place updates. Some apply cleanly and stay clean afterwards. Others **recur every plan** because the BPG provider can't fully unset the underlying Proxmox attribute via the API.

## One-time drift (apply once, gone)

| Drift | Cause | Apply behavior |
|---|---|---|
| `+ vga { memory=16, type=std, clipboard=null }` | import doesn't populate `vga` block in state, but module sets it | Apply writes the same values, plan clean after |
| `comment: "Managed by Terraform - Protected" -> "Managed by Terraform in proxmox-iac"` (cloudflare/fortios) | older provider/module wrote one tag, current default is the other | Apply rewrites the comment field, plan clean after |
| `fortios subnet: "IP MASK" -> "IP/32"` | fortios provider serialization changed between versions; state has old format | Apply rewrites; plan clean unless provider version downgrades |
| `network_device.enabled: null -> true` (only when moving non-protected → protected) | non-protected module's dynamic network_device doesn't set `enabled`; protected module sets it explicitly | Apply writes `enabled=1` (already implied by VM running), plan clean after |

## Persistent drift (apply doesn't actually fix the underlying Proxmox attribute, recurs every plan)

| Drift | Cause | One-shot fix via Proxmox API |
|---|---|---|
| `mtu: 1500 -> 0` | BPG provider returns `0` from API when Proxmox stores "default" (= 1500). New module sets `mtu=1500` explicitly. Apply writes 1500 → API stores it as default → next refresh reads 0 again. | `curl -sk -X PUT -H "Authorization: PVEAPIToken=$PROX9_TOKEN" "$PROX9_URL/api2/json/nodes/<node>/qemu/<vmid>/config" -d "delete=mtu"` — clears the explicit mtu so state and config both consistently read 0/default. (Or set `vm_mtu = 0` in module, but that's wrong-direction.) |
| `- dns { servers = ["8.8.8.8","1.1.1.1","8.8.4.4"] }` | VM has `nameserver = ...` set in cloud-init from its Prox7 origin. Module's `initialization` block doesn't include a `dns` sub-block. State refresh reads the servers from API; config has none → plan removes. **Apply doesn't actually clear the nameserver field on the VM** — known BPG provider quirk for `initialization.dns`. | `curl -sk -X PUT -H "Authorization: PVEAPIToken=$PROX9_TOKEN" "$PROX9_URL/api2/json/nodes/<node>/qemu/<vmid>/config" -d "delete=nameserver"` — clears the cloud-init nameserver line. State refresh sees no servers, matches config, drift gone. **No reboot impact** — running VMs keep their `/etc/resolv.conf`; only matters on next cloud-init reboot. |

## Verifying which kind of drift you're looking at

Run plan twice in a row (no apply between). If it disappears the second time → it was something `tofu refresh` cleaned up. If it persists → it's the structural kind. If it persists even after apply → the BPG provider can't reconcile it, use the API delete trick.

## When to use lifecycle ignore_changes

Suppressing via `lifecycle { ignore_changes = [...] }` in the module is a permanent solution but masks legitimate future changes too. Only use this if:
- The drift recurs after the API delete trick (rare)
- The attribute is one we never want TF to manage (e.g., a kubernetes-deployed app's container labels)

For the catalog above, **prefer the API delete trick** — keeps TF in charge of meaningful changes while clearing the noise.

## Discovery references

- mtu drift first observed: OPS-1738 fuel migration (2026-04-29) — never goes clean even after apply.
- dns drift first investigated: OPS-1764 minecraft pilot review (2026-04-30) — paloma-validator (vmid 238) showed it persisting after OPS-1741 apply.
- enabled drift: OPS-1744 protected-relocation MR !995 (2026-04-30) — only when moving from non-protected to protected module.
