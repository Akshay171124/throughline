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

## Offline demo

If the venue Wi-Fi fails, the app can run against the local Docker FalkorDB (`throughline-falkordb` on `localhost:6379`) instead of the shared lab. Do this before going on stage, while you still have internet:

```sh
uv run python -m throughline.offline sync    # copy the lab graph into local FalkorDB (replaces the local one)
uv run python -m throughline.offline check   # PASS/FAIL: talks, plan for BLD1428W, graph view, attendee memory
```

`sync` copies every node and edge with Cypher (labels, properties, relationship types and properties), recreates the indexes, refreshes the attendee-free `throughline_public` view and checks that node and edge counts match on both sides. Attendee memory stays out of the copy unless you add `--with-attendees`. Run it again after any change to the lab graph you want in the demo.

To switch the running app to the local copy:

1. In `.env`, comment out the lab line: `# FALKORDB_URL=...`
2. Restart the app: stop it, then `uv run uvicorn throughline.api:app --port 8000`
3. `/api/health` should now say `local FalkorDB (localhost:6379)`.

(Or, without editing `.env`: `FALKORDB_URL= uv run uvicorn throughline.api:app --port 8000`. An empty variable in the shell wins over `.env`.)

What works offline: "Plan without AI" (the schedule, talk detail, learning path, day plan and path diagram) and attendee memory (`/api/talks`, `/api/plan`, `/api/graph`, `/api/attendees`). The agent chat calls OpenAI, so it needs the internet. Explainer links come from the graph, so `sync` brings them along. If they're missing locally, `uv run python -m throughline.explainers --from-cache` (with `FALKORDB_URL` commented out, or add `--local`) loads them from `data/explainers.json` without any web calls. The links themselves still need the internet to open.

To switch back: uncomment `FALKORDB_URL` in `.env` and restart the app. Anything attendees saved while offline stays in the local graph and is not copied back to the lab.
