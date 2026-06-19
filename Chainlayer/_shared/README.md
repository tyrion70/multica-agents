# Chainlayer _shared — Cross-Squad Agents

Agents in this directory are not permanently tied to a single squad. They are
utility specialists that any squad Tech Lead can invoke via `@mention` when the
work falls into their domain.

## Agent catalog

### Monitoring Operators

| Agent | Model | Runtime |
|---|---|---|
| Claude Monitoring Operator | claude-opus-4-8 | claude-runtime-01 |
| ChatGPT Monitoring Operator | gpt-5.5 | chatgpt-runtime-01 |
| DeepSeek Monitoring Operator | deepseek-v4-pro | deepseek-runtime-01 |

All three share the same instruction contract: they query Grafana Cloud
(PromQL/dashboards) and operate the monitoring2 (bare-metal NO/NL/DE) + k8s
Alertmanager stacks over the tailnet. Capabilities are identical across vendors
— the Tech Lead chooses which model to invoke based on cost, speed, or benchmark
requirements.

### CF/HAProxy Experts

| Agent | Model | Runtime |
|---|---|---|
| Claude CF/HAProxy Expert | claude-opus-4-8 | claude-runtime-01 |
| ChatGPT CF/HAProxy Expert | gpt-5.5 | chatgpt-runtime-01 |
| DeepSeek CF/HAProxy Expert | deepseek-v4-pro | deepseek-runtime-01 |

Domain experts for ChainLayer Cloudflare (DNS, LB/pools, Access/Zero Trust,
service tokens) and HAProxy (bare-metal RPC fleet + k8s ingress). All three
share the same instruction contract — the Tech Lead chooses which model to
invoke.

## Adding a new cross-squad agent

1. Create `<agent-slug>/agent.json` in this directory
2. Ensure `agent.json` conforms to `../../schemas/agent.json`
3. Open a PR to `github.com/tyrion70/multica-agents`
