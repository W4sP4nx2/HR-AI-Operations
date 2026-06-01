# Load testing (Locust)

Measures the RAG chat path under concurrency. **Not run in CI** (locust is a
dev-only tool; `pytest` ignores this folder — the file is `locustfile.py`, not
`test_*.py`).

## Run

```bash
pip install locust
# Start the backend (and Postgres+pgvector for the real RAG path):
uvicorn api.main:app --port 8000

# Optional: grab a token (advisory mode needs none)
# curl -s -XPOST localhost:8000/auth/register -d '{"email":"load@x.com","password":"loadtest1"}' ...
# export HR_TOKEN=<token>

locust -f tests/load/locustfile.py --host http://localhost:8000 \
       --users 50 --spawn-rate 5 --run-time 2m --headless
```

## Targets

| Metric | Target |
|--------|--------|
| Vector retrieval (pgvector `<->` query) | **< 100 ms** |
| Full chat response (retrieve → synthesise) | **< 3 s p95** |

## If retrieval is slow

The pgvector store auto-creates an **HNSW** cosine index
(`USING hnsw (embedding vector_cosine_ops)`) — correct at any corpus size (unlike
ivfflat, which needs training data). For very large corpora, tune
`hnsw.ef_search` per session. Compare `ENABLE_RAG=true` vs `ENABLE_RAG=false`
(or `MOCK_LLM=true`) to isolate retrieval vs. LLM latency.

> Record p95 with/without RAG and paste the summary table into the README.
