# Curated Evidence

This directory contains reviewed, secret-free evidence snapshots that may be
committed. Raw run bundles remain under ignored `hackathon-evidence/`.

## Local ETL integration

`local-etl-integration.json` proves one local Docker execution of the two
external data-store gates:

- Postgres with pgvector accepted the 40 poisoned-policy chunks, persisted
  temporal metadata, and returned `policy_pto_2024` for the PTO trap.
- MinIO listed exactly the 1,000 resume objects from the generated manifest,
  with no missing or unexpected keys.

Reproduce after starting `db` and `minio` and exporting the connection settings:

```bash
make etl-live-certify
```

This artifact does not prove Fireworks execution, AMD hardware execution,
latency, throughput, cost savings, availability, or production scale.
