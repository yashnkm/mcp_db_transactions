# Policies (ingest source)

Drop policy documents here. The ingestion script indexes them into Chroma:

```
python scripts/ingest_policies.py
```

Supported formats: `.pdf`, `.md`, `.txt`.

Chunks are 1000 chars with 200-char overlap (adjust in `src/agent/ingest.py`).
Retrieval uses MMR with `k=4` (see `src/agent/nodes/retrieve.py`).
