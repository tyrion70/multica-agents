# Memory

## User Preferences

- **No Co-Authored-By in commits.** Do NOT add `Co-Authored-By: Claude ...` lines to commit messages. User wants only their own name on commits.
- [GitLab commit email](feedback_gitlab_email.md) — use peter@chainlayer.io for all GitLab repos
- [Branch/MR workflow](feedback_branch_mr_workflow.md) — always check MR state before pushing, rebase if open, new branch if merged
- [Always create Linear issues](feedback_always_create_linear.md) — create Linear issue BEFORE coding, use Linear branch name, no exceptions
- [Linear private vs company routing](feedback_linear_private_vs_company.md) — private→Tyrion/TYR (API key), company→Chainlayer DevOps (MCP); always issue-first + link GitHub
- [Tyrion (personal) Linear](reference_linear_tyrion.md) — TYR team, API key at ~/.claude/secrets/linear-tyrion.env (gitignored), direct GraphQL
- [Always assign Linear issues to user](feedback_linear_assignment.md) — pass `assignee: "me"` when creating; never leave unassigned
- [Don't start VMs after restore](feedback_no_start_after_restore.md) — user moves to target host first, then starts
- [STOP and ask on unexpected](feedback_ask_on_unexpected.md) — NEVER proceed autonomously when something goes wrong, always ask user
- [Prox9 VMID — next-free from 100](feedback_prox9_vmid_convention.md) — never reuse Prox7 vmid; scan from 100 upward
- [Proxmox disk-string PUT safety](feedback_proxmox_disk_string_safety.md) — always GET first, flip only the flags you mean to change; never use placeholder MAC; never blindly delete unused0
- [Validators in nl2_c4_protected](feedback_proxmox_validators_protected.md) — validators/signers go in `clusters/nl2_c4_protected/`, not `nl2_c4/`; add missing networks to protected rather than dropping VMs in non-protected
- [Cloudinit ide2→ide0 move](feedback_proxmox_cloudinit_slot.md) — naive PUT fails with "already attached"; need to delete the volume and call the cloudinit regenerate endpoint first
- [State mv vs removed+import](feedback_proxmox_state_mv_vs_import.md) — for cluster relocations prefer manual `tofu state mv` between state files; cleaner plan, no bookkeeping-resource creates
- [Persistent drift catalog](feedback_proxmox_persistent_drift.md) — mtu/dns/comment/vga/subnet recurring drift causes + API delete-trick fixes
- [LVM disk-size off-by-one](feedback_proxmox_disk_size_lvm_offbyone.md) — module adds +1, so set sum of vm_os_disk_size_lvm = target_disk - 1 (e.g. 99 for 100G)
- [UniFi PUTs are partial-commit](feedback_unifi_partial_writes.md) — 4xx response does NOT mean no fields applied; GET→modify-one-field→PUT
- [UniFi forbidden imports](feedback_unifi_forbidden_imports.md) — never import unifi_wan / non-corporate networks / default radius profile / gateway device
- [Tailscale URL beats LAN IP](feedback_tailscale_for_personal_devices.md) — for cross-device dev access, hand user the tailscale IP not the LAN IP

## Project Structure

- `repositories/documentation/` — Retype documentation site (GitLab, chainlayer/documentation)
- `projects/documentation/` — Source files/drafts for documentation
- `projects/chainlink/` — Plan for chainlink platform modernization
- [Chainlink Platform Modernization](project_chainlink_platform.md) — Service registry + dockerized CronJobs
- [K8s Deployment Guide](reference_k8s_deploy_guide.md) — Full workflow for deploying new apps to k8s (gitlab-iac → CI → secrets → k8s-apps → ArgoCD)
- [Proxmox 7→9 Migration](project_proxmox_migration.md) — Lift & shift 161 VMs via PBS, project at `projects/proxmox-migration/`
- [Composite Adapter System](project_chainlink_composite_adapters.md) — Annotations, bridge aliases, and detection logic
- [Adapter Traffic Metrics](project_chainlink_adapter_metrics.md) — Which Prometheus metrics to check before decommissioning adapters
- [Postgres Migration to k8s](project_postgres_migration.md) — 82 databases on 8 VMs → Zalando Postgres Operator, project at `projects/postgres-migration/`
- [Netbox URL](reference_netbox_url.md) — thebox2.cinternal.com, NOT netbox.chosts.io
- [Minecraft AMP Server](project_minecraft_amp_server.md) — minecraft-1a-nl2v, CubeCoders AMP + Docker, licence pinned to VM machine id
- [Homelab + Hetzner cluster](project_homelab_cluster.md) — 4-node PVE Cluster + off-site hetzner standalone (MinIO/PDM/PBS) + UniFi UDM; entry point at `projects/proxmox/README.md`
- [Homelab VPN VM](project_homelab_vpn_vm.md) — VM 102 NordVPN gateway (192.168.16.163); eth0 must stay static, netplan apply wipes wg rules, boot clock skew poisons WG handshakes
- [Chainlayer Proxmox endpoints](reference_chainlayer_proxmox_endpoints.md) — Prox7 at 10.24.0.16, Prox9 at 10.34.0.163; distinct from homelab proxmox1-4
- [ESS saas-pi-appliance local-first](project_ess_local_first.md) — only public data (prices/solar/weather) lives in cloud; energy data stays on Pi; subscription cancel kills history access only
- [ESS saas-pi-appliance status](project_ess_saas_pi_status.md) — read .planning/projects/saas-pi-appliance/STATUS.md first when resuming this project
- [ess-ai-planner project](project_ess_ai_planner.md) — PRIVATE optimizer project, no Linear, github.com/tyrion70/ess-ai-planner, ess repo read-only
- [ESS data topology](reference_ess_data_topology.md) — Prometheus + Grafana + InfluxDB live on grafana.252h.org (NOT dev); dev only runs ess-dashboard + mqtt-influx bridge
- [Weekend Escape Radar](project_weekend_escape_radar.md) — PRIVATE personal MVP, no Linear, github.com/tyrion70/weekend-escape-radar, working tree at `repositories/weekend-escape-radar/`
- [Optimism migration to k8s](project_optimism_migration.md) — OPS-2135; full-node works, archive blocked on OP snapshot pipeline; status doc at `projects/optimism-migration/STATUS.md`
- [Filecoin Lotus node](reference_filecoin_lotus_node.md) — voter = Lotus on k8s nl-oven (NOT filecoin-infra Forest); NVxx upgrades are mandatory/epoch-gated, fork-check via glif tipset CIDs
- [QuickNode URL structure](reference_quiknode_url_structure.md) — side-convincing-emerald.<network>.quiknode.pro/<token>; token in GCP mythic-fulcrum via k8s-shared store
- [Tremor earthquake monitor](project_earthquakes.md) — worldwide quake site (PostGIS+FastAPI+Leaflet) at ~/claude/projects/earthquakes, live over Tailscale :8080
- [claude-skills repo](reference_claude_skills_repo.md) — all skills live in tyrion70/claude-skills (private); ~/.claude/skills are symlinks; install.sh + make-zips.sh
