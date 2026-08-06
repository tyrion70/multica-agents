---
name: reference-claude-skills-repo
description: "All Claude Code skills live in the private repo tyrion70/claude-skills — edit there, not in ~/.claude/skills (those are symlinks)"
metadata: 
  node_type: memory
  type: reference
  originSessionId: f38825f1-351f-4ef3-89f6-4f1375d73fd2
---

All of Peter's Claude Code skills (company-k8s, company-proxmox, chainlink-ops,
haproxy, deploy-app, grafana-monitoring, linear, git-mr, new-repo, homelab,
bitwarden, …) live in **github.com/tyrion70/claude-skills** (PRIVATE), checked
out at `~/claude/repositories/claude-skills/`.

- `~/.claude/skills/*` are **symlinks** into that checkout — edit the repo, not
  the symlink targets' "copies".
- New machine: clone + run `install.sh`.
- Zips for Claude Desktop upload: `./make-zips.sh [skill]` → `dist/` (desktop
  skillsets don't sync with Claude Code; re-upload after edits).
- New skills follow the repo README conventions (kebab-case folder, SKILL.md
  with trigger-rich description, explicit ✅/🔶/🛑 permission model). Related:
  [[feedback_linear_private_vs_company]] for the TYR issue-first rule.
