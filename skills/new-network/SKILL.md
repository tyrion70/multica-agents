---
name: new-network
description: "Spin up a NEW network as a publicly-reachable RPC node, end to end — the single entrypoint for BOTH the VM plane (Proxmox + Ansible + HAProxy) and the Kubernetes plane (op-stack/op-reth on ArgoCD). Use when onboarding a network that does not yet run anywhere: Step 0 is a VM-vs-k8s class-branch that routes to the matching runbook (VM: existence check → snapshot → proxmox VM → <network>-infra pipeline → HAProxy → monitoring → docs; k8s: chart choice → snapshot on PV → ApplicationSet → AppProject allowlist → config → Cilium LB → monitoring → docs). This skill is the thin entrypoint: it points at the canonical runbook and the owning domain skills — it does NOT restate their steps. Runs the `new-network` orchestration (bundled `new-network.sh`, VM) or walks the runbook by hand. Scope ends at a live, syncing, public RPC; Chainlink/DON/oracle config is out of scope (Joakim's handoff)."
---

