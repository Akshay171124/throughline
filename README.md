# Throughline

A readiness agent for conferences: pick a talk, and Throughline builds your path there through a FalkorDB knowledge graph. It shows what to learn first, in what order, and where to learn it before the talk starts. The plan and design are in [THROUGHLINE_SUBMISSION.md](THROUGHLINE_SUBMISSION.md).

## Run it

```sh
# 1. FalkorDB (graph on :6379, FalkorDB Browser on :3000)
docker run -d --name throughline-falkordb -p 6379:6379 -p 3000:3000 \
  -v throughline-falkordb-data:/var/lib/falkordb/data falkordb/falkordb:latest

# 2. Python deps and keys
uv sync
cp .env.example .env   # then fill in the keys

# 3. Build the talks snapshot and load it into the graph
uv run python -m throughline.catalog
uv run python -m throughline.graph

# 4. The app on http://localhost:8000
uv run uvicorn throughline.api:app --reload
```

Tests: `uv run pytest` (the graph tests need FalkorDB running and use a separate `throughline_test` graph).

## Layout

| Path | What it is |
|---|---|
| `throughline/catalog.py` | Turns the Universe catalog feed into clean talk records |
| `throughline/graph.py` | FalkorDB connection, indexes and the talk loader |
| `throughline/api.py` | FastAPI endpoints and the static page |
| `web/` | The page: schedule, talk detail, on-screen clock |
| `data/raw/` | Last good catalog snapshot (fallback when a scrape fails) |
| `checks/` | Hand-checked research from the evening before, including the 15-talk prerequisite baseline |
