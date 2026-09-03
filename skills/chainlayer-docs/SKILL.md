---
name: chainlayer-docs
description: "Write, review, and publish ChainLayer operational documentation in the gitlab.com/chainlayer/documentation repo — a Retype static site published to docs.chainlayer.cloud. Use whenever creating or editing docs (runbooks, network/alert pages, operations guides, policies), scaffolding a new network/runbook from docs/templates/, running markdownlint + retype build locally, or merging a doc change to publish. Covers the house style + Documentation Principles, the gitleaks/lint CI gates, what counts as a sensitive page (human sign-off before merge), and how doc delivery differs from code MRs (Multica issue is the system of record — no Linear ticket). Pairs with git-mr for the GitLab mechanics."
---

# ChainLayer documentation — write, review, publish

The `gitlab.com/chainlayer/documentation` repo is a **Retype static site**, not a
code project. Source is markdown under `docs/`; **publishing is a merge to `main`**
→ GitLab CI builds and deploys to GitLab Pages at **docs.chainlayer.cloud**. There
is no test suite, no app to stand up, no staged prod cutover. The bulk of the site
is operational: runbooks, network and alert pages that on-call follows live. "Wrong"
here means a runbook misleads someone at 3am — so the real quality gate is
**technical-accuracy review**, not CI.

This skill owns the docs toolchain and house rules. For the GitLab branch/rebase/MR
mechanics use the **`git-mr`** skill (this repo IS `gitlab.com/chainlayer`); the
**docs delivery carve-out** below overrides `git-mr`'s Linear-issue requirement.

## Repo layout

```
docs/
  index.md                  # site landing page
  documentation-guide.md    # the full framework (read it once)
  templates/                # scaffolding — RUNBOOK-TEMPLATE, network-*, alert-page, etc.
  networks/<network>/        # per-network: index, common-issues, upgrades, runbooks/, ALERTS-INVENTORY, VALIDATION-CHECKLIST
  alerts/                    # alert pages
  operations/                # generic, cross-network patterns (snapshot-bootstrap, …)
  infra/                     # infrastructure docs
  guides/                    # how-to guides
  policies/                  # policy / sensitive pages  (see "Sensitive pages")
  _includes/                 # shared snippets
retype.yaml                  # site config (url: docs.chainlayer.cloud, excludes templates/)
.markdownlint.json           # lint rules (MD013/MD022/MD032/MD033/MD034 disabled)
.gitlab-ci.yml               # gitleaks + lint-markdown (validate) → pages (deploy, main only)
```

`docs/networks/polygon/` is the reference network — the most complete example. Copy
its structure and section headings when documenting a new network.

## Scaffolding a new doc — don't start from a blank file

Everything is template-driven. Scaffold from `docs/templates/` instead of recreating
structure:

- **New network:** create `docs/networks/<network>/{,runbooks/}`, then copy
  `network-index-template.md → index.md`, `network-common-issues-template.md →
  common-issues.md`, `network-upgrades-template.md → upgrades.md`,
  `network-validation-checklist-template.md → VALIDATION-CHECKLIST.md`, and the
  `RUNBOOK-*` templates into `runbooks/`. (Full checklist: `docs/templates/README.md`.)
- **New runbook:** copy `RUNBOOK-TEMPLATE.md`; see `RUNBOOK-EXAMPLE-REFACTORED.md`
  for a worked example. Structure is **Diagnose → Fix → Verify**.
- **New alert page:** copy `alert-page-template.md`.
- **Generic cross-network pattern:** put it in `docs/operations/` and reference it
  from each network's `common-issues.md` (single source of truth).

`templates/` is excluded from the published site (`retype.yaml`), so templates never
appear on docs.chainlayer.cloud — keep them as scaffolding, don't link to them as if
they were live pages.

## House style — the Documentation Principles

The canonical statement lives in `docs/templates/README.md` and
`docs/documentation-guide.md`. The principles a writer/reviewer must apply:

1. **Chainlayer-specific only.** Document *our* setup, decisions, and procedures —
   not what a blockchain or proof-of-stake is. No generic background filler.
2. **Distill patterns, not incidents.** "Bad-block errors → roll back 2 blocks with
   `debug.setHead`, ~15 min" — not "Feb 19, Thomas fixed block 52384291 in 14 min."
   A doc captures the reusable pattern; incident logs belong elsewhere.
3. **Diagnose → Fix → Verify.** Every runbook has 🔍 commands to confirm the problem,
   🔧 steps to fix, ✅ commands to confirm resolution.
4. **Generic + network-specific split.** When a pattern spans networks, write the
   generic doc in `operations/` and reference it from the network's `common-issues.md`.
5. **Commands that actually work.** Copy-pasteable, with placeholders and expected
   success/failure output. Don't paste a command you haven't reasoned through.
6. **Mark knowledge gaps explicitly — never invent.** Use the 📝 Gap notation
   inline where it matters operationally, and track systematic gaps in the network's
   `VALIDATION-CHECKLIST.md`:

   ```markdown
   > **📝 Gap:** [what's missing] [why it matters during an incident] [how to close it]
   ```

   Better a marked gap than a guessed command, URL, namespace, or contact. Making up
   operational details is the one unrecoverable error in this repo.

Formatting conventions (also in the templates README): Mermaid for
architecture/decision trees, fenced `bash` blocks with a comment + expected output,
the ✅ / ❌ / ⏳ status markers, and `{.compact}` tables for reference data.

## Verifying accuracy — use the read-only infra skills

Because docs are accuracy-critical, **check the operational facts a doc asserts**
against the real systems, read-only, before writing or approving them:

- `kubectl`/namespace/manifest references → verify with the **`company-k8s`** skill
  (read-only; never mutate clusters from a docs task).
- Grafana dashboard links, panel names, PromQL → verify with **`grafana-monitoring`**.
- Host paths, service names, things only confirmable on a box → **`ssh`**, read-only.
- Background/state and key decisions → **`chainlayer-knowledge`** is the factual
  grounding for runbooks and network docs.

A docs task needs **no `bitwarden`** and no write access to any cluster — if a doc
seems to need a secret, that's a 📝 Gap or a CI/gitleaks concern, not a reason to
fetch credentials. (`chainlayer-knowledge` and this repo can drift: the skill is the
cross-cutting state/decisions, the repo is the published operational docs. When they
disagree, verify against the live system and fix whichever is stale.)

## Local checks before the MR — markdownlint + retype build

CI runs two `validate` components (`gitleaks`, `lint-markdown`) and then, on `main`
only, a `pages` deploy (`retype build`). Reproduce the gates locally before pushing:

```bash
# 1. Lint markdown against the repo's .markdownlint.json
npx --yes markdownlint-cli2 "docs/**/*.md"        # or: markdownlint -c .markdownlint.json docs/

# 2. Build / preview the site the way CI deploys it
npm install --global retypeapp                     # once
retype build --output public                       # must succeed — this is the deploy step
retype watch                                        # optional local preview at http://localhost:5000
```

- **gitleaks** scans the diff for secrets. Never commit tokens, kubeconfigs, private
  keys, or live credentials — redact to `<placeholder>`. A gitleaks hit blocks the
  pipeline; fix the content, don't try to bypass the scan.
- **lint-markdown** must pass; respect `.markdownlint.json` (note MD013 line-length
  and MD033 inline-HTML are intentionally disabled — don't re-wrap or strip HTML to
  satisfy a rule that's off).
- A failing `retype build` breaks the Pages deploy — broken links, bad frontmatter,
  or malformed Mermaid will surface here. Build clean locally first.

Report failures honestly; a red lint/build means the doc isn't ready, not that the
check is wrong.

> **Retype gotcha — never name a page with a leading underscore.** Retype silently
> excludes files and folders that start with `_` from the build: a page named
> `_pipeline-test.md` (or anything under a `_dir/`) **never renders, produces no
> error, and won't appear on docs.chainlayer.cloud** — `retype build` and CI stay
> green while the page is simply missing. Name pages without a leading underscore.
> (`_includes/` uses this on purpose for shared snippets that aren't standalone
> pages.) If a freshly-added page doesn't show up after publish, check its filename
> for a leading `_` first.

> **Check CI synchronously, within your turn.** When you gate on the pipeline
> (the Reviewer/Publisher does), poll its status in-turn — a short sleep-loop on the
> MR pipeline until it resolves to success/failure — and act on the result before
> the turn ends. **Never hand off to or wait on a background CI notification:** a
> Multica turn that ends while "waiting for the pipeline" is over, and the
> notification never arrives, so the relay stalls. Block in-turn or re-check on the
> next turn; don't wait on a callback.

## Publishing = merge to main

There is no separate deploy step or rollback runbook: **merging the MR to `main`
publishes.** CI's `pages` job (`only: main`) runs `retype build` and ships the
artifact to GitLab Pages, live at **docs.chainlayer.cloud** within a few minutes.
After merge, confirm the page renders at its docs.chainlayer.cloud URL. To revert,
open a follow-up MR (or revert commit) — same path, merge republishes.

## Sensitive pages — human sign-off before publish

The repo is also "better than Notion for sensitive items" (`README.md`), so some
pages are sensitive. **Default publishing is ungated** — most docs are runbooks and
network/alert notes and a reviewer can merge them on a green review. **A change that
touches a sensitive page requires explicit human (Peter) sign-off before the merge.**

Treat a change as **sensitive** when it touches any of:

- anything under `docs/policies/` (policy pages);
- access control, credential-handling, secret-rotation, or security procedures;
- legal, HR, financial, customer/contractual, or otherwise confidential content;
- a page that names internal hostnames/IPs, contact details, or other data we would
  not want publicly indexed (the site is reachable at docs.chainlayer.cloud).

If you're unsure whether a page is sensitive, treat it as sensitive and ask. For a
sensitive change: do not merge — surface it for human sign-off (the Docs Lead
escalates to Peter) and hold the MR until approved. Routine, non-sensitive docs do
not need this gate.

## Doc delivery carve-out — Multica issue is the system of record

Doc work in this repo is tracked in **Multica**, not Linear. When shipping a doc MR,
follow `git-mr` for the GitLab mechanics (identity, fetch/rebase, SSH-signed commits,
no `Co-Authored-By`, the MR template) **with these doc-specific overrides:**

- **No Linear-issue-first requirement and no Linear closing magic words.** The Multica
  issue is the system of record; reference it in the MR description instead. Do **not**
  block on creating an OPS/CLL/MAN ticket and do **not** add `Closes OPS-XXXX`.
- **Exception:** if the doc change *derives from* an existing OPS/CLL/MAN Linear issue
  (e.g. documenting the outcome of an infra ticket), then keep the normal `git-mr`
  Linear linkage and closing words for traceability.
- Use `docs:` (or `fix:`/`chore:` as appropriate) conventional-commit prefixes;
  branch names follow the Multica issue identifier.
- Link the MR back on the Multica issue and pin `pr_url` in metadata.

## When to ask

- A page might be sensitive (per the list above) — treat as sensitive and get sign-off.
- A command/namespace/dashboard you can't verify read-only — mark a 📝 Gap, don't guess.
- gitleaks flags content you believe is a false positive — confirm with a human rather
  than weakening the scan.
- The change is large enough to need new templates or a structural reorg of `docs/`.
