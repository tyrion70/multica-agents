---
name: deploy-verify-rollback
description: Generic, target-agnostic deploy → verify → rollback procedure for shipping an approved change to production and safely reverting it when health checks fail. Use whenever deploying any service that is NOT covered by a target-specific skill — Kubernetes Deployments, docker / docker-compose hosts, or systemd-managed binaries reached over SSH. Always records the last-known-good state BEFORE deploying so rollback is a single known command. Tremor has its own deploy path — use the `tremor` skill for that, not this one.
---

# Deploy → Verify → Rollback (generic)

This is the safe-deploy loop for any target that does **not** already have its
own deploy skill. It is deliberately target-agnostic: you identify the runtime,
capture the last-known-good revision, deploy, run real health checks, and roll
back to that captured revision if verification fails.

**Out of scope:** the Tremor app — its deploy/reconcile is covered end-to-end by
the `tremor` skill (zero-downtime rules, gluetun proxy ports, Cloudflare tunnel).
ChainLayer's k8s GitOps pipeline (gitlab-iac → k8s-apps → ArgoCD) is covered by
`deploy-app`; for those targets follow that skill and use the Argo rollback in
§4d. This skill composes with `git-mr` / `git-pr` (merge the approved MR/PR — company / private respectively), `ssh` (reach
hosts), and `bitwarden` (pull deploy credentials — never hardcode them).

## 0. Hard rules

- **Deploy only after explicit approval** — a QA PASS *and* a release approval.
  No approval → set the issue `blocked` and ask. Never deploy on your own call.
- **Capture last-known-good BEFORE you touch anything** (§2). A deploy you can't
  name the previous state of is a deploy you can't roll back.
- **One target at a time.** Verify green before moving on.
- If anything is surprising, ambiguous, or the rollback itself fails → **STOP and
  report**, leaving the issue `blocked`. A half-rolled-back prod is the worst
  outcome; surface it loudly rather than improvising further.

## 1. Identify the target

Before deploying, answer these from the issue/PR or by inspecting the host:
- **Runtime**: Kubernetes Deployment? docker-compose stack? bare docker
  container? systemd service / binary? (Picks the playbook in §3/§4.)
- **Where**: cluster + namespace + workload name, or host + path + unit/stack name.
- **Health signal**: the URL, port, or command that proves the *new* code is
  actually serving (not just "the process is up"). If you can't name one, you
  cannot verify — get it before deploying.

## 2. Capture last-known-good (mandatory)

Record the current live revision so rollback is a single command later. Pick the
line that matches the runtime and **save its output in the issue/comment**:

```bash
# Kubernetes — current image + revision
kubectl -n <ns> get deploy <name> -o jsonpath='{.spec.template.spec.containers[0].image}'; echo
kubectl -n <ns> rollout history deploy/<name>            # note the current revision #

# docker-compose — currently running image tags/digests
docker compose -f <compose.yml> images

# bare docker — current container image
docker inspect --format '{{.Config.Image}}' <container>

# systemd binary — back up the live artifact before overwriting it
sudo cp -a /opt/<app>/<bin> /opt/<app>/<bin>.bak-$(date +%Y%m%d-%H%M%S)
systemctl show <unit> -p ExecStart --value
```

Also note the **git SHA / image tag** of the previous release — that is the
canonical "known-good" you roll back to.

## 3. Deploy

Merge the approved MR/PR first if needed (`git-mr` company / `git-pr` private skill: rebase, SSH-signed, no
Co-Authored-By). Then apply, by runtime:

```bash
# Kubernetes — set the new image and wait for the rollout
kubectl -n <ns> set image deploy/<name> <container>=<image>:<newtag>
# (or: kubectl -n <ns> apply -f <manifest>)

# docker-compose — pull the new tag and recreate
docker compose -f <compose.yml> pull && docker compose -f <compose.yml> up -d

# systemd binary — install new artifact, then restart
sudo install -m 0755 <new-bin> /opt/<app>/<bin> && sudo systemctl restart <unit>
```

## 4. Verify (must pass before you call it done)

Run the runtime check **and** the application health check. "Pod is Running" is
not "the new version is serving" — assert both.

**a. Rollout / process is healthy**
```bash
kubectl -n <ns> rollout status deploy/<name> --timeout=120s   # k8s: blocks until ready or fails
kubectl -n <ns> get pods -l app=<name>                        # all Running, 0 restarts climbing
docker compose -f <compose.yml> ps                            # State = running / healthy
systemctl is-active <unit>                                    # → active
journalctl -u <unit> -n 50 --no-pager                         # no crashloop / stack traces
```

**b. Application is actually serving the new code**
```bash
curl -fsS -o /dev/null -w '%{http_code}\n' https://<host>/healthz   # expect 200
curl -fsS https://<host>/version | grep <expected-new-sha-or-tag>   # confirms NEW build is live
```

**c. No new errors for a short soak** — watch logs/metrics for ~1–2 min:
```bash
kubectl -n <ns> logs -l app=<name> --since=2m | grep -iE 'error|panic|fatal'   # expect empty
```

If `/healthz` or `/version` is missing, substitute the real readiness signal you
identified in §1 (a known endpoint returning 200, a queue draining, a row count).
Do not skip this step — a green rollout with a 500ing endpoint is a failed deploy.

**d. ArgoCD / GitOps target** (e.g. via `deploy-app`): verify with
`argocd app get <app>` → `Synced` + `Healthy`, or `kubectl -n <ns> get application <app>`.

## 5. Rollback (when §4 fails — real commands, pick by runtime)

Roll back to the revision captured in §2, then re-run §4 against the restored
version to confirm prod is healthy again.

```bash
# Kubernetes — undo to the immediately-previous revision (or a specific one)
kubectl -n <ns> rollout undo deploy/<name>
kubectl -n <ns> rollout undo deploy/<name> --to-revision=<rev-from-§2>
kubectl -n <ns> rollout status deploy/<name> --timeout=120s

# docker-compose / bare docker — pin back the previous tag and recreate
docker compose -f <compose.yml> pull && docker compose -f <compose.yml> up -d   # after reverting the tag in compose.yml
docker run -d --name <container> <image>:<previous-tag-from-§2>                  # bare docker

# systemd binary — restore the backup taken in §2 and restart
sudo install -m 0755 /opt/<app>/<bin>.bak-<ts> /opt/<app>/<bin> && sudo systemctl restart <unit>

# ArgoCD / GitOps — roll back to the previous synced revision
argocd app rollback <app> <previous-history-id>
# (or git-revert the deploy commit in the manifests repo and let Argo re-sync)
```

After the rollback command, **re-verify with §4** (rollout/process healthy +
`/healthz` 200 + `/version` shows the OLD known-good build). A rollback you didn't
verify is not a rollback.

## 6. Report

- On success: post what was deployed, where, and the verification results
  (health-check status code + version confirmed). Pin `deploy_url` and set
  `pipeline_status=deployed` in issue metadata; set the issue `done`.
- On rollback: post that you reverted, the known-good revision now live, the
  verification proving prod is healthy again, and *why* the deploy failed. Set the
  issue `blocked` (not `done`) — the change still needs fixing and redeploying.
