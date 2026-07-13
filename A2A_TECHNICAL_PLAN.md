# Govern.ai A2A technical plan

## Why the product needed this

The earlier implementation had typed `A2AEnvelope` records and an orchestrator
plan, but no addressable Agent Card, message method, task state, or proof that
one role could hand a safe artifact to another. That made “A2A” a dashboard
label instead of an integration boundary.

## Current proof (implemented)

Govern.ai exposes two independently addressable roles in the same FastAPI
service:

| Role | Endpoint | Output | Next gate |
|---|---|---|---|
| Resume Extractor | `POST /a2a/agents/resume_extractor/rpc` | identity-free profile artifact | Policy Guard |
| Policy Guard | `POST /a2a/agents/policy_guard/rpc` | policy version, allowed/forbidden actions, evidence | Human reviewer |

Cards are discoverable at
`/a2a/agents/{agent}/.well-known/agent-card.json`. Calls use JSON-RPC
`message/send` and return an A2A-shaped task with `completed` or
`input-required` state plus a Govern.ai certified envelope. The proof test sends
one message to each endpoint and asserts that email/name data does not cross
the boundary, certification passes, and the second task requires a human.

Run the proof against a local preview:

```bash
curl -s http://127.0.0.1:8010/a2a/graph | jq .
curl -s http://127.0.0.1:8010/a2a/agents/resume_extractor/.well-known/agent-card.json | jq .
curl -s -X POST http://127.0.0.1:8010/a2a/agents/resume_extractor/rpc \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":"extract-1","method":"message/send","params":{"message":{"text":"Backend engineer with Python and FastAPI."}}}'
```

The returned profile is then passed as `params.profile` to the Policy Guard
endpoint. This is a same-service proof, not a claim of two separately deployed
services. The [official A2A specification](https://a2aproject.github.io/A2A/latest/specification/)
supports Agent Cards and HTTP JSON-RPC transports; remote federation is the
next deployment step, not current demo evidence.

## Governance invariants

1. Raw resume text is accepted only at the extractor boundary and is never put
   in the certified payload or audit record.
2. The Policy Guard adds `policy_version`, `allowed_actions`,
   `forbidden_actions`, and `human_approval_required=true`.
3. A downstream role receives a certified payload only when the schema and PII
   checks pass; otherwise it receives an empty payload and a failed task.
4. Ranking and explanation are advisory. `reject_candidate`,
   `make_hiring_decision`, and `override_policy` are forbidden actions.
5. Audit persistence stores trace, route, certification, latency, and cost
   metadata—not raw resume data.

## Remoteisation plan

1. Split `resume_extractor` and `policy_guard` into separate deployments while
   keeping these cards and payload schemas stable.
2. Add service-to-service authentication (mTLS or signed bearer tokens), replay
   protection, idempotency keys, and a durable task store.
3. Add SSE task updates and `tasks/get` once a broker-backed lifecycle is needed.
4. Add a contract test that runs both containers and verifies the same handoff,
   including a deliberate schema/PII failure.

The acceptance gate is not “A2A is configured”; it is a captured two-endpoint
handoff with a certified artifact and a human checkpoint.
