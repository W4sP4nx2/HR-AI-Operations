# AMD-Hosted Gemma Kubernetes Overlay

This overlay is the localhost port-forward judging profile for the hackathon
**Best AMD-Hosted Gemma Project** track. It keeps the product workflow unchanged
and swaps the live inference endpoint to an OpenAI-compatible vLLM server running
on AMD ROCm. It is deliberately explicit about dependencies it does not deploy.

## Prerequisites

- An AMD Instinct node with a compatible ROCm driver.
- The AMD GPU Operator or device plugin exposing at least one `amd.com/gpu`
  allocatable resource.
- A default StorageClass that supports `ReadWriteOnce` and at least 500 GiB.
- Google Gemma usage terms accepted for the Hugging Face account, followed by a
  read-scoped `HF_TOKEN`.
- A reachable PostgreSQL 16 database with the `pgvector` extension installed.
  Replace the external placeholder in `DATABASE_URL`; this overlay does not
  create or own a database.
- A private first-run `ADMIN_EMAIL` and strong `ADMIN_PASSWORD`. The overlay
  enforces authentication and disables public registration, so these values
  bootstrap the initial administrator on an empty database.
- Pullable or node-preloaded `hrcc-backend:1.0.0` and
  `hrcc-frontend:1.0.0` application images. Replace these base references with
  immutable registry digests for a remote cluster.

References: [AMD GPU device plugin](https://instinct.docs.amd.com/projects/k8s-device-plugin/en/latest/index.html),
[AMD ROCm/vLLM images](https://hub.docker.com/r/rocm/vllm/tags), and the
[Gemma 3 27B model access terms](https://huggingface.co/google/gemma-3-27b-it).

Verify and label the judged node before applying the overlay:

```bash
kubectl get nodes \
  -o custom-columns=NAME:.metadata.name,ARCH:.status.nodeInfo.architecture,GPU:.status.capacity.amd\.com/gpu
export AMD_NODE_NAME=replace-with-mi300x-node-name
kubectl label node "$AMD_NODE_NAME" accelerator=amd-instinct-mi300x --overwrite
```

The deployment requests one `amd.com/gpu`, matching the default `single`
resource naming strategy documented by AMD's device plugin.

## Apply

Create the secret from a private copy of the example file:

```bash
kubectl apply -f deploy/k8s/base/namespace.yaml
cp deploy/k8s/overlays/amd-gemma/hrcc-secrets.example.env /tmp/hrcc-secrets.real.env
cp deploy/k8s/overlays/amd-gemma/hrcc-gpu-secrets.example.env /tmp/hrcc-gpu-secrets.real.env
# accept the Gemma license, then edit every replace-* value, ADMIN_EMAIL,
# ADMIN_PASSWORD, and DATABASE_URL;
# do not commit either file
kubectl -n hr-ai-system create secret generic hrcc-secrets \
  --from-env-file=/tmp/hrcc-secrets.real.env \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n hr-ai-system create secret generic hrcc-gpu-secrets \
  --from-env-file=/tmp/hrcc-gpu-secrets.real.env \
  --dry-run=client -o yaml | kubectl apply -f -
```

Deploy the overlay:

```bash
kubectl apply -k deploy/k8s/overlays/amd-gemma
```

## Expected routing

- `hrcc-backend` reads `LLM_PROVIDER=amd_vllm`.
- `hrcc-backend` sends live model calls to
  `http://hrcc-gpu-inference:8000/v1`.
- `hrcc-gpu-inference` runs `vllm.entrypoints.openai.api_server`.
- The served model name is `amd-gemma-3-27b-it` in the example, and the same
  value must appear in `ALLOWED_MODELS`.
- The judged overlay defaults to one GPU replica, a `Recreate` rollout, and a
  writable `ReadWriteOnce` model cache so it works on a single MI300X node.
- The GPU pod receives HTTPS egress for the initial gated-model download. For a
  long-lived environment, pre-populate the PVC and replace this broad port-443
  rule with an FQDN-aware policy supported by the cluster CNI.
- The backend receives PostgreSQL egress on TCP 5432. This portable hackathon
  rule permits any destination on that port; narrow it to the database CIDR with
  `ipBlock`, or use a CNI-specific FQDN policy, before treating the profile as a
  production deployment.
- `hrcc-secrets` is consumed by the backend, while `hrcc-gpu-secrets` contains
  only the model IDs and Hugging Face token consumed by the inference pod.
- `ADMIN_EMAIL` and `ADMIN_PASSWORD` create the first administrator exactly once.
  Concurrent backend replicas tolerate the unique-email race on a fresh database.
- `AMD_VLLM_API_KEY` is a backend-to-vLLM service credential. The AMD profile
  reports `byok_supported=false`; never paste this key into the browser BYOK
  control or send it as `X-Client-LLM-Key`.
- The default context is bounded to 32,768 tokens to leave predictable KV-cache
  headroom. Change it only after a measured memory/capacity check.

## Offline checks

```bash
python scripts/preflight_amd_gemma_judge.py --mode static
```

Runtime checks to capture on the AMD cluster:

```bash
kubectl -n hr-ai-system rollout status deploy/hrcc-gpu-inference
kubectl -n hr-ai-system get pods -l app.kubernetes.io/name=hrcc-gpu-inference -o wide
```

Keep these three port-forwards open in separate terminals. The checked-in
frontend image is built for these localhost URLs, and the overlay CORS policy
allows only `http://localhost:3000`:

```bash
kubectl -n hr-ai-system port-forward svc/hrcc-backend 8000:8000
kubectl -n hr-ai-system port-forward svc/hrcc-frontend 3000:3000
kubectl -n hr-ai-system port-forward svc/hrcc-gpu-inference 8001:8000
```

Then open `http://localhost:3000` and verify both the product API and the direct
AMD/Gemma inference endpoint:

```bash
curl http://localhost:8000/health
curl http://localhost:8001/health
curl -H "Authorization: Bearer $AMD_VLLM_API_KEY" http://localhost:8001/v1/models
python scripts/capture_amd_runtime_evidence.py \
  --target kubernetes \
  --out /tmp/amd-runtime.json
python scripts/verify_amd_runtime_evidence.py /tmp/amd-runtime.json
# Export the same ADMIN_EMAIL/ADMIN_PASSWORD values placed in hrcc-secrets;
# live preflight verifies an actual admin login without printing credentials/JWT.
python scripts/preflight_amd_gemma_judge.py \
  --mode live \
  --amd-runtime-evidence /tmp/amd-runtime.json
```

For a real ingress hostname, patch `FRONTEND_BASE` and `CORS_ORIGINS`, and build
the frontend image with matching `NEXT_PUBLIC_API_BASE` and
`NEXT_PUBLIC_WS_URL` values. Those variables are compiled into the Next.js
client bundle, so changing only the backend ConfigMap is insufficient.

Do not publish speed or throughput claims until the evidence names the AMD GPU,
ROCm image tag, vLLM version, Gemma model, prompt shape, p50/p95 latency,
memory, and correctness/error result.
