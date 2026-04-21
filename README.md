# Transaction Analysis

Policy-aware RAG agent that answers questions about the payment-transaction DB
(`authstattab`, `tranlogtab`, `int_detail_tab`, `int_control_tab`).

## Pipeline

```
query -> retrieve_policy -> understand_query -> route -> execute_db -> compose_answer
                                                     \-> clarify (HITL-lite)
```

- `retrieve_policy` — MMR search over Chroma-indexed policy docs.
- `understand_query` — LLM call with structured output (`Intent`) using the schema-quirk prompt.
- `route` — conditional edge based on `Intent.target_table`.
- `execute_db` — `create_agent` with task-shaped tools (no generic `run_sql`).
- `compose_answer` — final LLM call combining policies + DB rows + raw flag interpretations.

## Modular model selection

Set `.env`:

```
LLM_PROVIDER=google_genai                   # or anthropic
LLM_MODEL=gemini-3.1-flash-lite-preview     # or gemini-3.1-pro, claude-sonnet-4-6, claude-opus-4-7
EMBEDDINGS_PROVIDER=google_genai            # or openai
EMBEDDINGS_MODEL=gemini-embedding-001       # or text-embedding-3-small
```

Provider factories live in `src/agent/models.py`. Adding a new provider is a
single `if` branch; no node/graph code changes.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env    # fill in keys + DATABASE_URL
```

Seed the DB (for local dev):

```bash
psql "$DATABASE_URL" -f schema.sql         # create tables
python scripts/seed_db.py --truncate       # 1000 auths + linked rows across all 4 tables
# options: --auth 2000 --recaps 50 --seed 42
```

Drop policy docs in `./policies/` then ingest:

```bash
python scripts/ingest_policies.py
```

Chat (CLI):

```bash
python scripts/chat.py --thread my-session
```

Chat (Streamlit UI — recommended for demo):

```bash
streamlit run streamlit_app.py                 # http://localhost:8501
streamlit run streamlit_app.py --server.port 8502
```

Chat (Gradio UI — legacy):

```bash
python scripts/ui.py              # http://127.0.0.1:7860
python scripts/ui.py --share      # public link (tunneled)
```

## Layout

```
src/agent/
├── config.py        # pydantic-settings loader
├── models.py        # build_chat_model / build_embeddings factories
├── state.py         # AgentState TypedDict + Intent pydantic model
├── prompts.py       # schema-quirk + role prompts
├── db.py            # SQLAlchemy engine + fetch_all helper
├── ingest.py        # loaders -> splitter -> Chroma
├── tools/db_tools.py  # @tool functions (task-shaped)
├── nodes/           # retrieve, understand, route, execute, compose
└── graph.py         # StateGraph wiring + checkpointer selection
```

## Notes

- Default checkpointer is `InMemorySaver`. Switch to Postgres with
  `CHECKPOINTER=postgres` + `CHECKPOINTER_POSTGRES_URL` (requires
  `pip install -e .[postgres-checkpoint]`).
- All DB tools parameterize inputs. Amounts and codes are strings — leading
  zeros are preserved. See `.claude/skills/payment-txn-db-schema/SKILL.md` for
  the full schema playbook.
