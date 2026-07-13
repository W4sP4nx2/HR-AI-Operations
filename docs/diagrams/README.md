# Project Diagrams

These diagrams are editable Excalidraw scenes generated from structured element
sources. The PNG files are review previews, not the source of truth.

| View | Purpose | Editable scene | Preview |
|---|---|---|---|
| Technical architecture | Runtime boundaries, provider routing, retrieval, and evidence | [technical-architecture.excalidraw](./technical-architecture.excalidraw) | [PNG](./previews/technical-architecture.png) |
| Product dataflow | Inputs, decision support, outcomes, and evaluation feedback | [product-dataflow.excalidraw](./product-dataflow.excalidraw) | [PNG](./previews/product-dataflow.png) |
| User flow | Open-access and enforced-auth paths into role-scoped workspaces | [user-flow.excalidraw](./user-flow.excalidraw) | [PNG](./previews/user-flow.png) |
| Agent workflows | Triage, policy RAG, resume, onboarding, and retention paths | [agent-workflows.excalidraw](./agent-workflows.excalidraw) | [PNG](./previews/agent-workflows.png) |
| Operations flow | Build, deploy, observe, evaluate, and release lifecycle | [operations-flow.excalidraw](./operations-flow.excalidraw) | [PNG](./previews/operations-flow.png) |
| Platform risk controls | ROCm image, async Batch states, and Compose/K8s demo boundary | [platform-risk-controls.excalidraw](./platform-risk-controls.excalidraw) | [PNG](./previews/platform-risk-controls.png) |

## Regenerate

Run the source generator:

```bash
node scripts/generate_diagram_sources.mjs
```

The generated element arrays live in [`source/`](./source/). Import each array
into the local Excalidraw canvas with `mcp-excalidraw-server add`, then export
the `.excalidraw` scene and PNG preview. The generator is deterministic, so
reviewers can inspect every label, boundary, and connector before rendering.

The project-scoped Codex MCP configuration is in
[`../../.codex/config.toml`](../../.codex/config.toml). It runs the Excalidraw
canvas on `http://127.0.0.1:3100`, away from the application on port 3000.

The diagrams describe the current product boundary. Hosted model providers and
AMD vLLM are explicit alternatives selected through injected configuration;
the diagrams do not claim that unverified hardware was used for a given run.
