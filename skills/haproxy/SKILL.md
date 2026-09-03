---
name: haproxy
description: Work on ChainLayer's RPC load balancing — the bare-metal HAProxy fleet (hapee, backends.yaml, *.rpc.cinternal.com) and the k8s HAProxy Ingress Controller (ingress-haproxy ns, haproxy-backend chart/controller). Use when adding or changing a chain backend, debugging 503s/health checks on rpc.cinternal.com hostnames, or extending the k8s IC. All changes are GitOps — never live-edit the dataplane or IC ConfigMap.
---

