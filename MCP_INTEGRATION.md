# MCP integration

The optional MCP adapter gives local agent clients a narrow, read-only view of
the HR AI Command Center. It is an integration boundary, not a second admin API.

## Product scope

| MCP tool | Product job | Side effects | External-data risk |
|---|---|---|---|
| `hrcc_get_agent_catalog` | Discover agent contracts, roles, and guardrails | None | None |
| `hrcc_preview_ticket_triage` | Preview deterministic routing before opening a case | None | None |
| `hrcc_get_policy_guidance` | Retrieve grounded policy guidance | Audit row only | Requires explicit consent when a remote provider is configured |

The adapter does not expose resume text, attrition records, case mutation,
policy ingestion, audit exports, or approval actions. Those workflows stay
behind the authenticated FastAPI and human-review boundaries.

The editable product-boundary diagram is stored at
[`docs/hrcc-product-access.excalidraw`](./docs/hrcc-product-access.excalidraw).

## Run locally

```bash
cd backend
pip install -r requirements-mcp.txt
python -m mcp_server.hr_command_center_mcp
```

Example Codex MCP configuration:

```toml
[mcp_servers.hr-command-center]
command = "python"
args = ["-m", "mcp_server.hr_command_center_mcp"]
cwd = "/absolute/path/to/hr-command-center/backend"
```

The server uses stdio and writes no diagnostics to stdout.

## Evaluation

The no-key evaluator launches the real stdio server, performs MCP discovery,
checks annotations, invokes each safe workflow, and verifies six routing
categories plus prompt-injection handling:

```bash
cd backend
python -m mcp_server.evaluate_protocol
```

Stable natural-language evaluation cases live in
`mcp_server/evals/hrcc_mcp_evaluation.xml`. Run an LLM-as-client evaluation only
when the harness injects an approved model and credentials; no model name or
provider URL is hardcoded in this integration.

## Security argument

MCP annotations are client hints, not authorization. The structural control is
the smaller tool inventory: the server simply has no tool capable of reading
employee-sensitive records or mutating HR state. If a future write tool is
needed, it should call the authenticated application API with delegated user
identity and preserve the same RBAC, approval, and audit gates.
