# Throughline

Find the conference you're going to, tell Throughline your goal, and it gives you a path through the conference's FalkorDB knowledge graph: which talks to see, what to learn before each one, and where to learn it before the talk starts, with the evidence behind every step. Demonstrated on GitHub Universe 2026 (125 talks). The full write-up is in [THROUGHLINE_SUBMISSION.md](THROUGHLINE_SUBMISSION.md); the demo video script is in [docs/demo-script.md](docs/demo-script.md).

## Run it

```sh
# 1. FalkorDB: either the shared lab (put its URL in .env as FALKORDB_URL), or local Docker
#    (graph on :6379, FalkorDB Browser on :3000; used when FALKORDB_URL is empty)
docker run -d --name throughline-falkordb -p 6379:6379 -p 3000:3000 \
  -v throughline-falkordb-data:/var/lib/falkordb/data falkordb/falkordb:latest

# 2. Python deps and keys
uv sync
cp .env.example .env   # then fill in the keys (see below)

# 3. Check the setup (PASS/FAIL, never prints secrets)
uv run python -m throughline.check_setup

# 4. The app on http://localhost:8000
uv run uvicorn throughline.api:app --port 8000
```

### Keys in `.env`

| Key | Used for |
|---|---|
| `OPENAI_API_KEY`, `OPENAI_EXTRACT_MODEL`, `OPENAI_AGENT_MODEL` | Extraction (strong model), the live agent (fast model), summaries and vetting |
| `BRIGHTDATA_API_TOKEN`, `BRIGHTDATA_SERP_ZONE` | SERP API: conferences near you, explainers, readings |
| `BRIGHTDATA_BROWSER_WS` | Browser API: the catalog scrape |
| `FALKORDB_URL` | The shared lab graph (`falkors://...`). Empty = local Docker (`FALKORDB_HOST`, `FALKORDB_PORT`) |
| `GRAPH_NAME` | Graph name (default `throughline`; the attendee-free copy is `throughline_public`) |
| `CLOCK_START` | Where the on-screen clock starts: `2026-10-28T08:30` |

### Building the graph from scratch

Each step writes a file in `data/` and/or loads the graph. The graph in the lab is already built; you only need these to rebuild it.

```sh
uv run python -m throughline.brightdata catalog      # optional: live catalog through the Browser API (prints the feed)
uv run python -m throughline.catalog                 # raw snapshot (data/raw/) -> clean talks (data/universe26_talks.jsonl)
uv run python -m throughline.graph                   # load the talks into FalkorDB, refresh the public view
uv run python -m throughline.extract concepts        # OpenAI drafts the concept list (review data/extraction/concepts.json)
uv run python -m throughline.extract talks           # OpenAI proposes REQUIRES/TEACHES edges with evidence
uv run python -m throughline.knowledge               # word-for-word check, load edges, derive DEPENDS_ON
uv run python -m throughline.explainers              # outside explainers (Bright Data SERP + OpenAI vetting)
uv run python -m throughline.briefing                # "About this talk" for every talk (SERP + OpenAI)
```

`explainers` and `briefing` both take `--from-cache` to load `data/explainers.json` / `data/briefings.json` into the graph with no web calls, and `--local` to use the local FalkorDB.

### Measuring it

```sh
uv run python -m throughline.quality            # every number in "Measured quality"; writes data/quality.json (read-only on the graph)
uv run python -m throughline.quality --sample   # the 20 edges for the hand check (seed 2026); verdicts go in data/quality_handcheck.json
uv run python -m throughline.evaluate           # day plans compared with the 15-talk baseline in checks/
uv run pytest                                   # graph tests need FalkorDB and use a separate throughline_test graph
```

## Pages

| Page | What it is |
|---|---|
| `/` | Find your conference (your location or a city): "Ready now" and live "Near you". Then `/?conference=universe26`: the talk flow, "Ask the graph" goal chat, Don't miss, calendar, profile |
| `/talk.html?code=BLD1428W` | One talk: schedule, chat and readiness in resizable panels; "About this talk"; path graph, day plan and "You're ready" |

## Layout

| Path | What it is |
|---|---|
| `throughline/catalog.py` | Turns the Universe catalog feed into clean talk records |
| `throughline/graph.py` | FalkorDB connection, indexes, the talk loader and the attendee-free public view |
| `throughline/config.py` | Settings from `.env` |
| `throughline/extract.py` | OpenAI extraction: concept list, then REQUIRES/TEACHES edges with evidence |
| `throughline/knowledge.py` | Loads concepts and checked edges; derives DEPENDS_ON |
| `throughline/evidence.py` | The word-for-word evidence check |
| `throughline/planner.py` | Learning path, day plan, mark attended, attendee memory (profile, saved talks, chat, Forget me) |
| `throughline/graphview.py` | A plan's path as nodes and edges for the path graph |
| `throughline/flow.py` | The "prepares you for" talk flow and Don't miss |
| `throughline/agent.py` | The OpenAI agent and its graph tools; `run_cypher` runs on the public view only |
| `throughline/api.py` | FastAPI endpoints and the static pages |
| `throughline/brightdata.py` | Bright Data Browser API (catalog) and SERP API calls |
| `throughline/explainers.py` | Vetted outside explainers for required concepts |
| `throughline/briefing.py` | "About this talk": AI summary and vetted readings |
| `throughline/nearby.py` | Conferences near you: 3 parallel SERP searches, OpenAI extraction, date-window check, merge and cache |
| `throughline/offline.py` | Copy the lab graph to local FalkorDB and check it |
| `throughline/quality.py` | The measured quality report |
| `throughline/evaluate.py` | Comparison with the hand-checked baseline |
| `throughline/check_setup.py` | PASS/FAIL setup check |
| `web/` | `index.html` + `landing.js` (landing and conference map), `talk.html` + `app.js` (talk page), vendored Cytoscape |
| `data/` | Talks snapshot, raw catalog (fallback), extraction output, explainer and briefing caches, nearby cache, quality report |
| `checks/` | Hand-checked research from the evening before, including the 15-talk prerequisite baseline |
| `tests/` | pytest suite |

## What needs the internet

| Works offline (local FalkorDB) | Needs the internet |
|---|---|
| Talk flow, Don't miss, calendar | The agent chat ("Ask the graph", talk-page chat): OpenAI |
| Talk page, path graph, day plan, "Plan without AI" | A new "Near you" search (a cached place is answered from `data/cache/nearby.json`) |
| Profile, saved talks, mark attended, Forget me | Opening explainer and reading links |
| "About this talk" and explainers (stored in the graph) | Rebuilding: catalog, extraction, explainers, briefings |

## Offline demo

If the venue Wi-Fi fails, the app can run against the local Docker FalkorDB (`throughline-falkordb` on `localhost:6379`) instead of the shared lab. Do this before going on stage, while you still have internet:

```sh
uv run python -m throughline.offline sync    # copy the lab graph into local FalkorDB (replaces the local one)
uv run python -m throughline.offline check   # PASS/FAIL: talks, plan for BLD1428W, graph view, attendee memory
```

`sync` copies every node and edge, recreates the indexes, refreshes the attendee-free `throughline_public` view and checks that node and edge counts match on both sides. Attendee memory stays out of the copy unless you add `--with-attendees`. Run it again after any change to the lab graph you want in the demo. If explainers or briefings are missing locally, load them from the caches: `uv run python -m throughline.explainers --from-cache --local` and `uv run python -m throughline.briefing --from-cache --local`.

To switch the running app to the local copy:

1. In `.env`, comment out the lab line: `# FALKORDB_URL=...`
2. Restart the app: stop it, then `uv run uvicorn throughline.api:app --port 8000`
3. `/api/health` should now say `local FalkorDB (localhost:6379)`.

(Or, without editing `.env`: `FALKORDB_URL= uv run uvicorn throughline.api:app --port 8000`. An empty variable in the shell wins over `.env`.)

To switch back: uncomment `FALKORDB_URL` in `.env` and restart the app. Anything attendees saved while offline stays in the local graph and is not copied back to the lab.
