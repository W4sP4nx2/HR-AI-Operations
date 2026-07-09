# GPU Platform and Multi-Tenant Operations

The Kubernetes assets under `deploy/` are an optional, statically verified
production template. They are not evidence of a running cluster. Docker/SQLite
remains the laptop path and does not start GPU workloads.

## Risk controls and demo lane

| Risk | Concrete control | Demo evidence |
|---|---|---|
| AMD driver and framework setup | Use the pinned pre-built AMD `rocm/vllm` gfx94X image; mount only the host AMD device nodes | `docker-compose.amd.yml`, `/health`, and `rocm-smi` from the named host |
| Fireworks Batch queue delay | Normalize provider states, show `Pending` with an async explanation, and poll every 10 seconds | Analytics batch tracker and `GET /lifecycle/fireworks/batch/{job_id}` |
| Kubernetes complexity | Default to Docker Compose; keep K8s optional for a managed cluster | Clearly labeled scaling projection from `scripts.simulate_scaling` |

The default hackathon demonstration uses Docker Compose. The managed Kubernetes
path is a platform template for EKS, GKE, or an equivalent service, not a demo
prerequisite. Scaling projections are always labeled simulated and are never
mixed with live Prometheus metrics.

## Workload topology

| Workload | Base replicas | Scaling | Isolation |
|---|---:|---|---|
| Backend API | 3 | HPA 3-12, CPU 65% | non-root, read-only FS, no API token |
| Frontend | 2 | HPA 2-8, CPU 70% | non-root, read-only FS, no API token |
| AMD/vLLM inference | 2 | operator/model-aware scaling | dedicated MI300X nodes, one GPU/pod |

All deployments use rolling updates and PodDisruptionBudgets. The backend and
frontend have topology-spread requirements. The live checker warns when Ready
pods still collapse onto one node.

## GPU scaling and sharing

The default strategy is **service-level sharing**, not unsafe device sharing:

1. One vLLM process owns one GPU.
2. Continuous batching and prefix caching share that process across authorized
   backend requests.
3. Two replicas provide failure tolerance and rolling upgrades.
4. Scale by adding whole GPU-serving pods after queue depth, token throughput,
   p95 latency, and GPU memory/utilization justify it.

For the Compose demo, generate a projection from operator-supplied inputs:

```bash
cd backend
python -m scripts.simulate_scaling \
  --current-replicas 1 --queue-depth 25 --p95-ms 2400 --gpu-utilization 94
```

This is decision-policy evidence, not proof that replicas changed.

Do not enable MIG-style partitioning on AMD by analogy with NVIDIA. Device
partitioning/time-slicing depends on the installed AMD device plugin and cluster
policy and must be separately benchmarked. For strict tenants, use dedicated
namespaces, quotas, node pools, and model-serving deployments. For trusted
tenants with the same model and policy, share the inference service through an
authenticated gateway and retain tenant ids in audit metadata, never metric
labels.

## Provider route

`LLM_PROVIDER=amd_vllm` is first-class. It requires:

- `AMD_VLLM_BASE_URL`
- `AMD_VLLM_API_KEY`
- `ALLOWED_MODELS`

There is no host or model fallback in code. The base manifest points the backend
at the internal service; the API key and allowed model ids must come from the
pre-provisioned `hrcc-secrets` Secret.

## Observability

The API exposes `/internal/metrics` with:

- request count by method, route template, and status;
- request latency histogram;
- inference transformation counts by role/truncation/injection signal.

No user id, tenant id, prompt, email, or raw URL is a metric label. A
`ServiceMonitor` and `PrometheusRule` provide scrape and alert templates for:

- unavailable backend replicas,
- HTTP 5xx ratio above 5%,
- p95 latency above two seconds.

Install the Prometheus Operator before applying `deploy/observability`. Add the
AMD GPU exporter only after confirming metric names for the installed device
plugin; do not fabricate dashboards against guessed counters.

## Security and policy

- Pod Security Admission: `restricted`.
- Dedicated service accounts; tokens are not mounted into application pods.
- Containers run non-root with read-only root filesystems, RuntimeDefault
  seccomp, no privilege escalation, and all capabilities dropped.
- Namespace default-deny ingress/egress.
- Explicit frontend-to-backend and backend-to-GPU flows.
- Monitoring scrape is namespace-restricted.
- ResourceQuota and LimitRange prevent noisy-neighbor exhaustion.
- Operator Kubernetes RBAC is read-only and excludes Secrets.
- Application RBAC remains viewer/analyst/manager/admin with
  `AUTH_ENFORCE=true`.

Database, identity-provider, Fireworks, and external egress are denied by the
base policy until an operator adds destination-specific policies. This is
intentional fail-closed behavior.

## Multi-tenant cluster operations

`deploy/k8s/tenants/tenant-template.yaml` provides a namespace, GPU/CPU/memory
quota, default-deny policy, and read-only tenant-operator role. Before real SaaS
tenancy, the application data plane still requires tenant ids on every row,
database row-level security, per-tenant encryption/retention, and tenant-aware
rate limiting. Kubernetes namespaces alone do not create data isolation.

## GitOps

Argo CD templates live in `deploy/gitops`. Before sync:

1. Replace the repository URL and example frontend domain.
2. Build/push immutable linux/amd64 image digests and override Kustomize images.
3. Provision `hrcc-secrets` through an external secret manager.
4. Provision Postgres/pgvector and explicit network egress.
5. Provision the model-cache PVC with a storage class supporting the requested
   multi-reader mode.
6. Install the AMD device plugin and label/tolerate MI300X nodes.
7. Review automated prune/self-heal policy with the platform owner.

## Checks

Static, CPU-only:

```bash
python scripts/verify_platform_manifests.py
```

Live, read-only:

```bash
python scripts/check_cluster.py --namespace hr-ai-system
```

The live check fails unless backend, frontend, and GPU inference each have at
least two desired, Ready, and available replicas plus a PodDisruptionBudget. It
warns when replicas are not spread across nodes.

Useful operator follow-ups:

```bash
kubectl get deploy,pods,pdb,hpa -n hr-ai-system
kubectl top pods -n hr-ai-system
kubectl rollout status deployment/hrcc-backend -n hr-ai-system
kubectl rollout status deployment/hrcc-gpu-inference -n hr-ai-system
```

## Next steps

1. Add tenant ids and database row-level security before shared SaaS data.
2. Add Redis for rate limits, cache coordination, and WebSocket fan-out across
   backend replicas.
3. Add queue-depth/token-throughput GPU autoscaling after installing a verified
   metric adapter.
4. Run load, failure, drain, and rolling-upgrade tests on a real cluster.
5. Capture AMD GPU utilization and model latency from named hardware.
6. Promote only after the live multi-pod check, network-policy connectivity
   tests, restore test, and tenant-isolation test pass.
