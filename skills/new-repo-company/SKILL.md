---
name: new-repo-company
description: Create a new COMPANY git repository the right way — GitLab chainlayer/* via the gitlab-iac Terraform repo, never via the GitLab UI or glab directly. Use whenever a ChainLayer project needs a new repo. Covers registry/CI wiring and the post-create checklist. For private github.com/tyrion70 repos use the `new-repo-private` skill instead.
---

# Creating a new company repository

Company side only: GitLab `chainlayer/*`, created through Terraform. Decide
**company vs private** first — if it's a personal/tyrion70 project, use the
**`new-repo-private`** skill. If ownership is unclear, ask the user; don't guess.

## Company → GitLab `chainlayer/*`, via gitlab-iac (Terraform)

**Never create company repos with `glab`, the GitLab UI, or the API** — every
chainlayer repo is Terraform-managed in `repositories/gitlab-iac/`. A
UI-created repo is invisible to IaC and will fight the next `tofu apply`.

1. Linear issue first (OPS/CLL/MAN — `linear-company` skill).
2. In `gitlab-iac`, add the project to the owning group's `_projects` local
   (e.g. `chainlink.tf`, `infrastructure.tf`):

   ```hcl
   my-app = {
     name                       = "My App"
     description                = "What it does"
     gcp_docker_registry_access = "private"   # only if it builds images
   }
   ```

   `gcp_docker_registry_access = "private"` enables the GAR integration and
   grants CI `artifactregistry.reader` (all branches) / `writer` (main only);
   images land in `europe-docker.pkg.dev/prime-hydra-436615-d6/chainlayer/`.
3. `tofu fmt -recursive`, MR per the `git-mr` skill, merge → Terraform creates
   the repo.
4. If the app deploys to k8s, continue with the `deploy-app` skill (CI
   template, secrets, manifests, ArgoCD).
5. Renovate autodiscovers `chainlayer/**` automatically — no opt-in needed
   (`chainlayer/personal/` is excluded).
6. Don't commit secrets in the bootstrap — credentials go in the vault
   (`bitwarden` skill, `company` folder) or gitignored `~/.claude/secrets/`.

## Post-create checklist

- Add a one-line entry to `~/.claude/REPOSITORIES.md` (the cross-session repo
  index) and, if a project dir uses it, the project's `REPOSITORIES.md`.
- First real change after creation follows the full `git-mr` flow (branch from
  the Linear issue, MR with closing magic words).

## When to ask the user

- Ownership unclear (company vs private → `new-repo-private`).
- Company repo group placement when no obvious group exists in gitlab-iac.
- Repo deletion, rename, transfer, or visibility change on an existing repo.
