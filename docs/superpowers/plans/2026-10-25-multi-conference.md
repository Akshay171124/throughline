# Every Conference Gets a Map: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Any conference the nearby search finds can be clicked, built into its own FalkorDB graph from its real schedule page, and opened with the same map, chat and planning Universe has.

**Architecture:**
- **Graphs.** One FalkorDB graph per conference. Universe keeps `throughline`; new ones get `throughline_c_<id>_v<n>`, each with a `_public` copy.
- **Registry.** A small `throughline_registry` graph lists conferences (status, counts, graph name) and attendee accounts (profile).
- **Self-describing graphs.** Each conference graph carries its own `Conference` node (name, dates, location, `clock_start`), so the planner, flow and agent read "their" conference from the graph they're given, and most signatures don't change.
- **Building.** A background build pipeline fetches the schedule page (plain HTTP, falling back to the Bright Data Browser API), has the model extract talks, verifies every title, URL, time and abstract against the page text in code, then reuses the existing concept and edge extraction.

**Tech Stack:**
- Python 3.12, FastAPI, FalkorDB (`falkordb` client), OpenAI (`gpt-5.5` extraction, `gpt-5.4-mini` agent/briefings), Bright Data (Browser API via Playwright CDP, SERP API), httpx, stdlib `html.parser`, pytest.
- Vanilla JS front end. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-25-multi-conference-design.md`

## Global Constraints

- Nothing made up:
  - A talk is kept only if its title appears in the page text (`evidence.normalize`).
  - A detail URL is kept only if it is one of the page's own links.
  - Times are parsed in code from a time string that appears on the page.
  - An abstract is kept only if it appears in the page text.
- End time = a stated end time, else start + a stated duration such as "(50 minutes)". Never inferred from the next slot.
- Fewer than 5 kept talks → status `not_found` with a plain-words reason.
- Right-event check: with known conference dates, ≥80% of kept talks must fall within those dates ±1 day, else `not_found` with "The schedule we found is for a different event (dates <Mon YYYY>)". Talks outside the dates are dropped.
- Detail pages: every talk with a detail URL is fetched, cap 300, a few at a time. Placeholders ("Details coming soon") count as no abstract; such talks stay but get no concept links.
- At most 2 link hops from the start URL to the schedule page; the model may only choose a link present on the page.
- Levels: Beginner/Introductory → 100, Intermediate → 200, Advanced/Expert → 300. No level → `level_num` 0, no badge.
- `sponsor` is true only if the page says the talk is sponsored.
- Conference id: slug of name + year, e.g. `qcon-san-francisco-2026`. Two entries are the same conference when their websites share a domain and their dates overlap; with no dates, fall back to a name match.
- Statuses: `none`, `building`, `ready`, `partial`, `failed`, `not_found`.
- Clock for a new conference: 08:30 on its first talk day, or 30 minutes before its first talk if earlier.
- Universe: graph `throughline`, id `universe26`, clock `CLOCK_START`. It must behave exactly as before, and the existing 93 tests must pass.
- Every conference-scoped endpoint takes the conference (default `universe26`).
- The registry graph is never exposed to `run_cypher`.
- Tests make no network or OpenAI calls: saved pages in `tests/fixtures/sites/` and stubbed `ask`/`fetch` callables. FalkorDB tests use the local Docker instance (`connect(name, local=True)`) and skip when it is unreachable, like the existing tests.
- Run tests with `uv run pytest -q`.

## Review Focus

1. **A page with talks from several events** (ai.engineer/ links to /code/2025): never a map of the wrong year. Pinned in Task 6 (`test_wrong_year_schedule_is_rejected`).
2. **Server restarts mid-build**: the conference must not stay "building" forever. Pinned in Task 8 (`test_interrupted_builds_become_failed`).
3. **Two clicks on the same unbuilt conference**: one build, both see its progress. Pinned in Task 8 (`test_second_start_joins_running_build`).
4. **An attendee code saved in the browser from before this change**: it still works on Universe and its profile follows to QCon. Pinned in Task 3 (`test_existing_universe_attendee_is_migrated`).
5. **A relative or fragment link on the schedule page** (`/presentation/nov2026/x`, `#day2`): it resolves to an absolute URL and fragments don't count as separate pages. Pinned in Task 4 (`test_links_are_absolute_and_fragment_free`).

---

### Task 1: Registry and accounts

**Files:**
- Create: `throughline/registry.py`
- Modify: `throughline/graph.py` (`upsert_conference` takes a record)
- Test: `tests/test_registry.py`

**Interfaces:**
- Produces:
  - `REGISTRY = "throughline_registry"`, `UNIVERSE_ID = "universe26"`
  - `registry_graph(local: bool = False) -> Graph`
  - `conference_id(name: str, start_date: str) -> str`: lowercase slug of name; append the year from `start_date` if the name has no 4-digit year.
  - `same_conference(a: dict, b: dict) -> bool`: domain match (`urlparse(url).hostname` without `www.`) and date overlap; when either has no `start_date`, a name match (the existing `nearby._loaded` word rule, moved here as `_names_match`).
  - `ensure_universe(reg: Graph) -> dict`: MERGE the Universe entry from `settings`, with `graph="throughline"`, `status="ready"`, `clock_start=settings.clock_start`.
  - `list_conferences(reg) -> list[dict]` and `get(reg, conf_id) -> dict | None`. Dict keys: `id, name, dates, start_date, end_date, location, url, schedule_url, graph, status, step, counts (dict), reason, checked_at, clock_start, talks`.
  - `upsert_found(reg, found: dict) -> dict`: returns the existing entry when `same_conference`, else creates one with status `none`.
  - `set_status(reg, conf_id, **fields) -> dict`: `counts` stored as a JSON string, `checked_at` set to now on every call.
  - `mark_interrupted(reg) -> int`: `building` → `failed`, reason "The build was interrupted".
  - Accounts:
    - `create_account(reg, code)`, `account_exists(reg, code) -> bool`, `delete_account(reg, code)`
    - `get_profile(reg, code) -> dict` and `set_profile(reg, code, role, experience, interests) -> dict`, with the same validation as `planner.set_profile` (reuse `planner.EXPERIENCE_LEVELS`). Each sets `profile_updated_at`.
  - `graph.upsert_conference(g: Graph, conf: dict | None = None)`: `None` means Universe from settings (current behaviour). It also writes `c.clock_start` and `c.url`.

- [ ] **Step 1: Write failing tests** in `tests/test_registry.py` (fixture graph `throughline_test_registry`, deleted after):
  - `test_conference_id_slugs_and_adds_year`: `conference_id("QCon San Francisco", "2026-11-16") == "qcon-san-francisco-2026"`; `conference_id("QCon San Francisco 2026", "2026-11-16") == "qcon-san-francisco-2026"`.
  - `test_same_conference_by_domain_and_dates`: `{"url": "https://ai.engineer/", "start_date": "2026-11-10", "end_date": "2026-11-12"}` and `{"url": "https://ai.engineer/code/2026", "start_date": "2026-11-10"}` → True; the same domain with `start_date` `2026-06-03` → False.
  - `test_upsert_found_merges_duplicates`: two upserts of those two ai.engineer records → one entry; `len(list_conferences(reg)) == 1` (plus Universe after `ensure_universe`).
  - `test_set_status_round_trips_counts`: `set_status(reg, id, status="partial", counts={"kept": 12, "no_time": 8})` → `get()["counts"] == {"kept": 12, "no_time": 8}`, with `checked_at` set.
  - `test_mark_interrupted`: an entry with status `building` → `mark_interrupted` returns 1, and its status is `failed` with reason "The build was interrupted".
  - `test_account_profile_round_trip`: `create_account`; `set_profile(... "some" ...)`; `get_profile` matches; `set_profile(..., "guru", ...)` raises `ValueError`; `delete_account` → `account_exists` False.
- [ ] **Step 2: Run** `uv run pytest tests/test_registry.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `throughline/registry.py` and the `upsert_conference` change. `load_talks(g, talks, source, conf: dict | None = None)` passes `conf` through and uses `conf["id"]` for `PART_OF` (default Universe).
- [ ] **Step 4: Run** `uv run pytest -q`. Expected: all pass (93 existing + new).
- [ ] **Step 5: Commit** with message `Registry: conferences, build status and attendee accounts`.

### Task 2: The planner and agent read their conference from the graph

**Files:**
- Modify: `throughline/planner.py` (`new_attendee`, `plan_day` clock fallback), `throughline/agent.py` (`SYSTEM_PROMPT` → function)
- Test: `tests/test_conference_scope.py`

**Interfaces:**
- Consumes: `graph.upsert_conference(g, conf)` (Task 1).
- Produces:
  - `planner.default_clock(g) -> int`: reads `MATCH (c:Conference) RETURN c.clock_start LIMIT 1`, falling back to `settings.clock_start`, and returns `to_minutes`. `new_attendee` and `plan_day` use it.
  - `agent.conference_of(g) -> dict`: name, dates, location from the graph's `Conference` node, with the settings fallback.
  - `agent.system_prompt(conf: dict) -> str`: today's text with the conference filled in. `SYSTEM_PROMPT` is removed. `run_agent` builds it from `conference_of(g)`.
  - The examples in the prompt and tool descriptions that name Universe talks (e.g. "BLD1428W", "the MCP security talk") stay. They're illustrations, not facts.

- [ ] **Step 1: Write failing tests** (fixture graph `throughline_test_scope`, with `upsert_conference(g, {"id": "qcon-san-francisco-2026", "name": "QCon San Francisco 2026", "dates": "Nov 16–20, 2026", "start_date": "2026-11-16", "end_date": "2026-11-20", "location": "San Francisco, CA", "clock_start": "2026-11-16T08:30", "url": "https://qconsf.com/"})`):
  - `test_new_attendee_starts_at_the_graphs_clock`: `attendee_clock(g, new_attendee(g)) == to_minutes("2026-11-16", "08:30")`.
  - `test_system_prompt_names_the_graphs_conference`: `"QCon San Francisco 2026 (Nov 16–20, 2026, San Francisco, CA)" in system_prompt(conference_of(g))`.
  - `test_graph_without_conference_falls_back_to_settings`: on an empty graph, `default_clock(g) == to_minutes(*settings.clock_start.split("T"))`.
- [ ] **Step 2: Run** `uv run pytest tests/test_conference_scope.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** with message `Planner and agent take the conference from the graph they're given`.

### Task 3: Conference-scoped API and accounts

**Files:**
- Modify: `throughline/api.py`
- Test: `tests/test_api_scope.py`

**Interfaces:**
- Consumes:
  - Task 1: `registry_graph`, `get`, `ensure_universe`, `mark_interrupted`, accounts, `set_profile`.
  - Task 2: `planner.new_attendee`.
- Produces:
  - `api.Ctx` dataclass: `conf: dict, g: Graph, public: Graph`.
  - `api.ctx(conf: str | None = Query(None), x_conference: str | None = Header(None)) -> Ctx`, a FastAPI dependency.
    - Resolution order: query → header → `universe26`.
    - It returns 404 "Unknown conference" when the id isn't in the registry, and 409 "This conference's map isn't built yet" when its status is not `ready` or `partial`.
    - Graph handles are cached per graph name in a dict, replacing `_graph` and `_public`. Keep `api.graph()` and `api.public_graph()` as Universe shortcuts so `tests/test_memory.py`'s `monkeypatch.setattr(api, "_graph", g)` keeps working: `ctx` uses `_graph`/`_public` for Universe when they're set.
  - `api.registry()` returns the cached registry graph.
  - `ensure_attendee(c: Ctx, code) -> None`:
    - 404 when there's no account and no `Attendee` node in `c.g`.
    - Creates the per-conference `Attendee` (clock from `planner.default_clock`) when only the account exists.
    - Copies the account profile onto the node when the account's `profile_updated_at` is newer.
    - Replaces `_require_attendee`.
  - `POST /api/attendees` creates the account and the node in the requested conference.
  - `PUT /profile` writes the account, then the node.
  - `DELETE /api/attendees/{code}` deletes the account and runs `planner.forget_attendee` on every registry graph whose status is `ready` or `partial`.
  - Startup (`@app.on_event("startup")`, or lifespan): `ensure_universe`, `mark_interrupted`, and `migrate_accounts`, which creates an account for every Universe `Attendee` without one, copying its profile.
  - Every endpoint that used `graph()` takes `c: Ctx = Depends(ctx)`. `/api/clock` returns `c.conf["clock_start"]` and `c.conf["name"]`. `/api/health` reports `c.conf["graph"]`. `/api/agent` passes `c.g` and `c.public`.

- [ ] **Step 1: Write failing tests.** Two local graphs, `throughline_test_api_a` (Universe-like) and `throughline_test_api_b` (QCon-like), each with one talk, one concept and a `Conference` node; a test registry graph; `monkeypatch` `api.registry` and the graph cache.
  - `test_flow_and_talks_never_mix`: `GET /api/talks?conf=<b>` returns only B's talk code; `GET /api/flow` with header `X-Conference: <b>` has no A codes; no `conf` → A's talks (Universe default).
  - `test_unbuilt_conference_is_409`: registry entry with status `none` → `GET /api/talks?conf=<id>` returns 409.
  - `test_profile_follows_the_attendee_across_conferences`: `POST /api/attendees?conf=<a>` → code; `PUT /api/attendees/{code}/profile?conf=<a>` with experience "some"; `GET /api/attendees/{code}?conf=<b>` → 200, and the profile's experience is "some".
  - `test_forget_me_removes_everywhere`: after `DELETE /api/attendees/{code}`, there's no `Attendee` with that code in A or B, and `account_exists` is False.
  - `test_existing_universe_attendee_is_migrated`: an `Attendee {code:'OLD1-OLD1-OLD1', experience:'new', clock_min: …}` created directly in A, then `migrate_accounts` → `account_exists` and `get_profile(...)["experience"] == "new"`; `GET /api/attendees/OLD1-OLD1-OLD1` → 200.
- [ ] **Step 2: Run** `uv run pytest tests/test_api_scope.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest -q`. Expected: all pass, including `tests/test_memory.py` unchanged.
- [ ] **Step 5: Commit** with message `API: every endpoint is scoped to one conference; accounts follow attendees`.

### Task 4: Fetching and reading a page

**Files:**
- Create: `throughline/importer.py` (this task: the page layer only)
- Modify: `throughline/brightdata.py` (add `render_page`)
- Test: `tests/test_importer_page.py`
- Fixtures (already saved): `tests/fixtures/sites/qcon_schedule.html`, `qcon_talk.html`, `aie_code_2026.html`. If any is missing, re-save with `curl -sL -A "Mozilla/5.0" <url> -o <file>` from https://qconsf.com/schedule/nov2026, https://qconsf.com/presentation/nov2026/apis-cant-afford-be-wrong-lessons-moving-money and https://ai.engineer/code/2026.

**Interfaces:**
- Produces:
  - `Page` dataclass: `url: str, html: str, text: str, links: list[tuple[str, str]]`. Text is visible text, without script/style, whitespace collapsed. Links are (anchor text, absolute URL without fragment), de-duplicated, in page order.
  - `parse_page(url: str, html: str) -> Page`, using a stdlib `html.parser.HTMLParser` subclass.
  - `MIN_TEXT = 1500`
  - `fetch_page(url: str, http=httpx.get, render=brightdata.render_page) -> Page`:
    - Tries a plain GET first (timeout 20, a browser User-Agent, follow redirects).
    - Falls back to `render(url)` when the status is ≥ 400, the request raises, or the text is shorter than `MIN_TEXT`.
  - `brightdata.render_page(url: str, timeout_ms: int = 90_000) -> str`: a Browser API page load (`connect_over_cdp(BRIGHTDATA_BROWSER_WS)`, `goto(wait_until="networkidle")`) that returns `page.content()`.

- [ ] **Step 1: Write failing tests:**
  - `test_parse_qcon_schedule_text_and_links`: `parse_page("https://qconsf.com/schedule/nov2026", fixture)`. The text contains "Live Resharding Without Regret" and "10:35AM PST", and not "<script". Links include `https://qconsf.com/presentation/nov2026/live-resharding-without-regret-lessons-building-valkeys-atomic-slot-migration`.
  - `test_links_are_absolute_and_fragment_free`: `parse_page("https://x.org/a/", '<a href="/p/1#top">One</a><a href="#day2">D</a><a href="b">B</a>')` gives links `[("One", "https://x.org/p/1"), ("D", "https://x.org/a/"), ("B", "https://x.org/a/b")]`.
  - `test_thin_page_falls_back_to_browser`: `fetch_page(url, http=lambda *a, **k: Resp(200, "<p>hi</p>"), render=lambda u: fixture_html)` gives the rendered text. A plain response with 5000 chars of text never calls `render`.
- [ ] **Step 2: Run** `uv run pytest tests/test_importer_page.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** with message `Importer: fetch and read any page (plain HTTP, Bright Data browser fallback)`. Include the fixtures.

### Task 5: Finding the schedule and reading the listing

**Files:**
- Modify: `throughline/importer.py`
- Test: `tests/test_importer_listing.py`

**Interfaces:**
- Consumes: Task 4 (`Page`, `fetch_page`).
- Produces:
  - `Ask = Callable[[str, str, dict], dict]` (system, user, JSON schema → parsed JSON); `ask_openai` is the default, using `settings.extract_model`, like `explainers.ask_openai`.
  - `find_schedule(start_url: str, fetch=fetch_page, ask=ask_openai, max_hops: int = 2) -> tuple[Page | None, list[str]]`:
    - Returns the page judged to be a schedule and the URLs tried.
    - The model answers `{"is_schedule": bool, "link": str | null}` given the page text (first 6000 chars) and its numbered links.
    - A `link` that isn't one of the page's links is ignored. That ends the hop chain with `None`.
  - `RawTalk` dict keys from the model: `title, date (YYYY-MM-DD), time_text (exact as on the page), start (HH:MM 24h), end (HH:MM or null), duration_text (exact, e.g. "(50 minutes)", or null), room, track, type, level, speakers [{name, company}], abstract, detail_url, sponsored (bool)`.
  - `read_listing(page: Page, ask=ask_openai, chunk_chars: int = 20000) -> list[dict]`: chunks the text on whitespace with 500 chars of overlap, merges the results, and de-duplicates on (normalized title, date).
  - `verify_listing(page: Page, raw: list[dict]) -> tuple[list[dict], Counter]`. Keeps a talk only if:
    - its title is in `normalize(page.text)`;
    - its `detail_url`, if given, is in the page's link URLs (otherwise it is set to None, not dropped);
    - its `time_text` is in the page text, and `parse_time(time_text) == start`.
    The drop reasons counted are `"title_not_on_page"` and `"time_not_on_page"`.
  - `parse_time(text: str) -> str | None`: the first `h:mm(am|pm)` or `HH:MM` in the text, as `HH:MM` 24h. For example "10:35AM PST" → "10:35" and "1:35 PM" → "13:35".

- [ ] **Step 1: Write failing tests** with stub `ask`/`fetch`:
  - `test_hops_to_the_schedule_link`: the home page lists a link `https://qconsf.com/schedule/nov2026`; the stub `ask` returns `{"is_schedule": False, "link": that}` and then `{"is_schedule": True, "link": None}` → returns the schedule page, with `tried` of length 2.
  - `test_link_not_on_page_is_refused`: the stub returns `{"is_schedule": False, "link": "https://evil.example/x"}` → `(None, [start])`.
  - `test_invented_title_is_dropped`: on the QCon fixture, raw = [the real "Live Resharding Without Regret: Lessons from Building Valkey's Atomic Slot Migration" with `time_text` "10:35AM PST" and start "10:35", plus "A Talk That Isn't There"] → kept 1, `Counter({"title_not_on_page": 1})`.
  - `test_time_must_be_on_page_and_match`: a real title with `time_text` "10:35AM PST" but start "11:00" → dropped as `time_not_on_page`.
  - `test_parse_time`: "10:35AM PST" → "10:35", "1:35 PM" → "13:35", "12:05PM" → "12:05", "12:30 AM" → "00:30", "no time" → None.
- [ ] **Step 2: Run** `uv run pytest tests/test_importer_listing.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** The prompts state that page text is untrusted data, like the existing prompts.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** with message `Importer: find the schedule page and read talks from it, verified against the page`.

### Task 6: Talk pages, end times, levels and the right-event check

**Files:**
- Modify: `throughline/importer.py`
- Test: `tests/test_importer_talks.py`

**Interfaces:**
- Consumes: Task 5 output (`kept` RawTalks).
- Produces:
  - `MAX_DETAIL_PAGES = 300` and `DETAIL_WORKERS = 4`.
  - `PLACEHOLDERS = ("details coming soon", "abstract coming soon", "tba", "to be announced")`
  - `enrich(talks: list[dict], fetch=fetch_page, ask=ask_openai, progress: Callable[[int, int], None] = lambda done, total: None) -> Counter`. For each talk with a `detail_url`:
    - Fetch the page; the model returns `{abstract, time_text, duration_text}`.
    - Replace the abstract when the new one is in the detail page text and longer than the listing teaser.
    - Fill `duration_text`/`end` when they're on the page.
    - Counts `"detail_failed"`.
  - `duration_minutes(text: str) -> int | None`: "(50 minutes)" → 50, "1 hour 15 minutes" → 75, "90 min" → 90.
  - `finish_times(talks) -> Counter`: sets `end` from start + duration where `end` is missing, and drops talks still without `date`/`start`/`end`, counted as `"no_time"`.
  - `level_num(level: str | None) -> int | None`: "Level 300" → 300 (the existing Universe format); Beginner/Introductory → 100; Intermediate → 200; Advanced/Expert → 300. QCon's "Advanced Topic" → 300.
  - `talk_code(conf_id: str, title: str) -> str`: first 8 chars of base32 over `sha1(conf_id + "|" + normalize(title))`, mapped onto `planner.CODE_ALPHABET`. It is deterministic.
  - `check_event(talks, start_date: str | None, end_date: str | None) -> tuple[list[dict], str | None]`:
    - With dates, it keeps talks within ±1 day.
    - If fewer than 80% are within, it returns `([], "The schedule we found is for a different event (dates Nov 2025)")`, where the month and year come from the median talk date.
    - With no dates, it keeps all talks and returns `None`.
  - `to_talks(conf_id: str, raw: list[dict]) -> list[dict]`: the exact dict shape `catalog.normalize_items` produces, with keys `code, session_id (None), title, type, level, level_num, topics ([track] or []), sponsor, date, day (weekday name), start, end, start_min, end_min, room, speakers [{name, company, title: ""}], abstract ("" for placeholders), url (detail_url or page url)`, sorted by (`start_min`, `code`).

- [ ] **Step 1: Write failing tests:**
  - `test_duration_gives_end_time`: start "10:35" + `duration_text` "(50 minutes)" → end "11:25".
  - `test_talk_without_end_or_duration_is_dropped`: → `Counter({"no_time": 1})`.
  - `test_detail_page_abstract_replaces_teaser`: with the `qcon_talk.html` fixture and a stub `ask` returning an abstract sentence copied from that page → the abstract is replaced. A stub returning a sentence not on the page → the teaser is kept.
  - `test_placeholder_abstract_becomes_empty`: abstract "Details coming soon" → `to_talks(...)[0]["abstract"] == ""`.
  - `test_level_mapping`: "Advanced Topic" → 300, "Beginner" → 100, "Level 200: Intermediate" → 200, None → None.
  - `test_talk_code_is_stable`: the same input gives the same 8-char code; a different title gives a different code.
  - `test_wrong_year_schedule_is_rejected`: 10 talks dated 2025-11-20 with conference dates 2026-11-10..2026-11-12 → `([], "The schedule we found is for a different event (dates Nov 2025)")`.
- [ ] **Step 2: Run** `uv run pytest tests/test_importer_talks.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** with message `Importer: full abstracts and durations from talk pages, levels, codes, right-event check`.

### Task 7: Concept extraction for any conference

**Files:**
- Modify: `throughline/extract.py`
- Test: `tests/test_extract.py`

**Interfaces:**
- Consumes: `importer.Ask` and `importer.ask_openai` (Task 5).
- Produces:
  - `draft_concepts(talks: list[dict], ask: Ask = ask_openai) -> list[dict]`: each concept has `{id, name, aliases, definition, basic: bool}`.
    - `CONCEPTS_SCHEMA` gains a required `basic` boolean.
    - `CONCEPTS_PROMPT` examples become conference-neutral, e.g. "OAuth 2.0", "vector databases", "Kubernetes pods", "event sourcing". It asks the model to mark 5–10 foundations as `basic`.
    - Duplicate ids keep the first.
  - `extract_edges(talks, concepts, ask=ask_openai, workers: int = 8, progress=lambda done, total: None) -> tuple[list[dict], int]`: returns the edges and the number of failed talks, reusing `extract_talk`'s prompt and schema. Talks with an empty abstract are skipped and not sent.
  - `extract_talk(client, talk, concepts)` stays for the Universe CLI. The `run_concepts`/`run_talks` CLI keeps working and writes the same files.

- [ ] **Step 1: Write failing tests** with a stub `ask`:
  - `test_draft_concepts_keeps_basic_flag_and_dedupes`: the stub returns two concepts with the same id → one kept, with `basic` preserved.
  - `test_extract_edges_skips_empty_abstracts`: 2 talks, one with `abstract == ""` → the stub is called once; the edges carry `talk` codes.
  - `test_extract_edges_counts_failures`: a stub raising for one talk → `failed == 1`, and the other talk's edges are returned.
- [ ] **Step 2: Run** `uv run pytest tests/test_extract.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** with message `Extraction works on any conference's talks; the model marks foundations`.

### Task 8: The build job

**Files:**
- Create: `throughline/build.py`
- Test: `tests/test_build.py`

**Interfaces:**
- Consumes:
  - Task 1: `registry.get`, `set_status`, `get_profile`.
  - Tasks 4–6: `importer.find_schedule`, `read_listing`, `verify_listing`, `enrich`, `finish_times`, `check_event`, `to_talks`.
  - Task 7: `extract.draft_concepts`, `extract_edges`.
  - Existing modules: `graph.ensure_schema`, `load_talks(g, talks, source, conf)`, `upsert_conference`, `publish_public_view`; `knowledge.load_concepts`, `load_edges`, `derive_depends_on`; `explainers.run`.
- Produces:
  - `MIN_TALKS = 5`
  - `STEPS = {"schedule": "Finding the schedule", "listing": "Reading the talks", "details": "Reading talk pages ({done} of {total})", "concepts": "Making the concept list", "edges": "Linking talks to concepts ({done} of {total})", "finish": "Finishing the map"}`
  - `start(reg, conf_id: str, schedule_url: str | None = None, deps: Deps | None = None) -> dict`:
    - Sets `building`, starts a daemon thread and returns the registry entry.
    - When a build for `conf_id` is already running (a module-level `dict[str, Thread]` guarded by a `Lock`), it returns the entry without starting another.
  - `Deps` dataclass: `fetch, ask, connect (name -> Graph), explain (Graph -> None)`. Defaults are the real ones; tests pass stubs.
  - `run(reg, conf_id, schedule_url, deps) -> dict` is the pipeline, run synchronously by the thread. It returns the final entry.
    - Status `not_found` with a reason, one of:
      - "We couldn't find a schedule page on <url>."
      - "<url> doesn't list any talks yet."
      - "The schedule page needs a login."
      - the `check_event` reason.
    - Status `partial` when `sum(dropped counts) > 0` or `detail_failed > 0` or extraction `failed > 0`; otherwise `ready`. `counts = {"kept": n, **drop_counts}`.
    - A login wall is detected when the page text contains "sign in" or "log in" and has fewer than 5 extracted talks.
    - The graph name is `f"throughline_c_{conf_id}_v{n}"`, where `n` is 1 + the previous version.
    - **Swap rule.** If the conference already has a `ready`/`partial` graph and the new build kept ≤ the old talk count, delete the new graph, keep the old status and set `reason="The retry found fewer talks, so the earlier map was kept."`.
    - **Carry-over on a swap.** Copy each `Attendee` node: properties; `ATTENDED`/`TARGETS` by talk code; `KNOWS` by concept `id`, else by `normalize(name)` matching the new concept's name or any alias. Then delete the old graph and its `_public` copy.
    - The Conference node is written with `clock_start` per the Global Constraints clock rule.
    - `explain(g)` runs after the status is set; its errors are swallowed and logged.
    - Any exception → `failed` with `reason=f"The build stopped: {type(e).__name__}"`.

- [ ] **Step 1: Write failing tests** with stub deps (local FalkorDB; `connect` uses test-prefixed graph names; stub `ask` routes by the system prompt's first words to canned answers built from the QCon fixture):
  - `test_qcon_fixture_builds_partial_or_ready`: the end status is `ready` or `partial`; `counts["kept"] >= 5`; the new graph has `Talk` nodes with `PART_OF` to `qcon-san-francisco-2026` and a `Conference.clock_start == "2026-11-16T08:30"`.
  - `test_aie_fixture_is_not_found`: the AI Engineer fixture, with a stub listing that returns `[]` → `not_found` and a reason containing "doesn't list any talks yet"; no conference graph is created.
  - `test_second_start_joins_running_build`: a stub `fetch` blocks on an `Event`; two `start()` calls → one thread (`len(build._running) == 1`); release; both see the final status.
  - `test_interrupted_builds_become_failed`: covered by `registry.mark_interrupted`. Assert that `start()` after it runs a fresh build.
  - `test_worse_retry_keeps_the_old_map`: a first build keeps 6 talks; a retry stub keeps 5 → the registry `graph` is unchanged and the reason is "The retry found fewer talks, so the earlier map was kept.".
  - `test_better_retry_carries_attendee_marks`: the first build has an attendee who `KNOWS` the concept "OAuth 2.0" (id `oauth2`) and `ATTENDED` a talk; the retry has the concept id `oauth_2_0` with name "OAuth 2.0" and the same talk title → in the new graph, the attendee `KNOWS` `oauth_2_0` and `ATTENDED` the same code; the old graph is deleted.
- [ ] **Step 2: Run** `uv run pytest tests/test_build.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** with message `Build job: schedule to map in the background, with partial, not-found and safe retries`.

### Task 9: Build endpoints, nearby results with status, readings on demand

**Files:**
- Modify: `throughline/api.py`, `throughline/nearby.py`, `throughline/briefing.py`
- Test: `tests/test_build_api.py`, and update `tests/test_nearby.py` where it asserts `loaded`/`id`

**Interfaces:**
- Consumes: Task 8 (`build.start`, `registry.get`), Task 1 (`upsert_found`, `list_conferences`).
- Produces:
  - `POST /api/conferences/{id}/build`, body `{"schedule_url": str | null}`:
    - 404 for an unknown id.
    - A `schedule_url` that isn't `http(s)` → 422.
    - Otherwise it returns `build.start(...)`'s entry.
  - `GET /api/conferences/{id}/build` returns `{status, step, counts, reason, checked_at, talks}`.
  - `GET /api/conferences` returns `{"current": <Universe entry>, "loaded": [entries with status ready|partial], "all": [every entry]}`. `loaded` keeps the shape the landing page uses today: `id, name, dates, location, talks`, plus `status, counts`.
  - `nearby.nearby(reg_upsert: Callable[[dict], dict], place, lat, lon)`:
    - Each result is passed through `reg_upsert` (registry `upsert_found`), and the response entries gain `id, status, reason, checked_at, counts`.
    - `loaded` stays as `status in ("ready", "partial")` for compatibility.
    - Ready conferences in the place are still listed first.
  - `nearby._unwrap(url: str) -> str | None`:
    - For `google.com/url?q=` or `?url=` and `google.com/goto?url=`, it returns the decoded target if it's `http(s)`.
    - Other `google.com` paths → None.
    - Any other URL is returned unchanged.
    - It is applied in `_extract` before the grounding check, and the grounding check compares unwrapped URLs.
  - `GET /api/talks/{code}/briefing` (scoped): when the stored status is `missing` and the talk has an abstract, it starts `briefing.build` + `store` in a background thread (one per talk, using the same running-dict pattern as `build.start`) and returns `{"status": "building", ...}`. A talk without an abstract returns `"status": "none"`.

- [ ] **Step 1: Write failing tests:**
  - `test_build_endpoint_validates_and_starts`: an unknown id → 404; `{"schedule_url": "javascript:x"}` → 422; a valid call with `build.start` monkeypatched → 200 and the stub was called with that URL.
  - `test_google_redirects_are_unwrapped`: `_unwrap("https://www.google.com/url?q=https%3A%2F%2Fqconsf.com%2F&sa=U") == "https://qconsf.com/"`; `_unwrap("https://www.google.com/goto?url=CAESUAHr") is None`; `_unwrap("https://qconsf.com/") == "https://qconsf.com/"`.
  - `test_nearby_results_carry_registry_status`: with `reg_upsert` stubbed to return `{"id": "qcon-san-francisco-2026", "status": "not_found", "reason": "r", ...}` → the result entry has those fields and `loaded is False`.
  - `test_briefing_builds_on_first_open`: a scoped talk with no summary and `briefing.build` monkeypatched → the first GET returns "building" and the stub is called once, even on a second GET while it's running.
  - Update the existing `tests/test_nearby.py` tests to the new `nearby()` signature without changing what they assert.
- [ ] **Step 2: Run** `uv run pytest tests/test_build_api.py tests/test_nearby.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** with message `Build and status endpoints; nearby results show each conference's map status; readings on first open`.

### Task 10: The front end

**Files:**
- Modify: `web/landing.js`, `web/landing.css`, `web/index.html`, `web/app.js`, `web/talk.html`, `web/style.css`

**Interfaces:**
- Consumes: Task 3 (`X-Conference` header, 409 for unbuilt), Task 9 (build endpoints, statuses on nearby and `/api/conferences`, `"building"` briefing status).
- Produces (behaviour):
  - Both `api()` helpers send `X-Conference: <id>`.
    - The landing page uses the open conference's id.
    - The talk page reads `?conference=` from its URL, else `throughline.conference` from storage, else none (the server then defaults to Universe).
    - Every link to `talk.html` carries `&conference=<id>`.
  - Conference cards by status:
    - ready → "✓ Map ready" / "Open the map →"
    - partial → "Partial map" / "Open the map →"
    - none → "Build the map" (primary button)
    - building → "Building…" (opens the build screen)
    - not_found → "No schedule yet (checked <relative time>)" with "Try again"
    - failed → "Build failed" with "Try again"
  - Build screen (a new view beside picker/detail/map, inside `#pickview`):
    - Shows the conference name, the current `step` text from polling `GET /api/conferences/{id}/build` every 2 s, and an elapsed-seconds counter.
    - On `ready`/`partial`, it opens the map.
    - On `not_found`/`failed`, it shows `reason`, an "Open the conference site" link (`safeUrl(conf.url)`), and an "I have the schedule link" form: a URL input, which POSTs `{schedule_url}` and resumes polling.
    - On `partial`, the form is also shown under the map's label.
  - On the map, when the status is `partial`: a label at the top, "Partial schedule: {kept} talks found", plus one clause per non-zero count:
    - `no_time` → "{n} listed without times were left out"
    - `title_not_on_page` + `time_not_on_page` → "{n} couldn't be checked against the page"
    - `detail_failed` → "{n} talk pages couldn't be read"
  - Level badges render only when `level_num > 0` (check `levelBadge`-style helpers in both files).
  - The "About this talk" card shows "Finding readings…" while the briefing status is `building`, and re-polls every 3 s, up to 60 s.

- [ ] **Step 1: Implement**, following the existing patterns: `escapeHtml`/`safeUrl` for every server string; the existing `setView`; the `storageGet`/`storageSet` wrappers.
- [ ] **Step 2: Verify in the browser.** Use the `run` skill, or start `uv run uvicorn throughline.api:app --port 8000`.
  - Universe opens as before: the map, the goal chat ("I'm new to MCP and want to build my first server" lights up 4 talks) and a talk page path.
  - With the registry entry for QCon set to `none`, the card shows "Build the map".
  - Universe has no partial label, and its level badges still show.
- [ ] **Step 3: Run** `uv run pytest -q`. Expected: all pass.
- [ ] **Step 4: Commit** with message `Front end: build screen, map status on every card, partial label, conference carried to talk pages`.

### Task 11: The real runs, and docs

**Files:**
- Modify: `README.md` (a "Any conference" section: how a build works and its statuses), `throughline/check_setup.py` (registry reachable)

- [ ] **Step 1: Live QCon build** (spends OpenAI and Bright Data credit; Akshay approved no limits).
  - Start the server, search "San Francisco" and click QCon San Francisco → Build.
  - Expected: it ends `ready` or `partial` with kept ≥ 60 talks; the map opens; talks have end times; a talk page shows a path; readings appear within about a minute.
  - Record the build time and counts in the commit message.
- [ ] **Step 2: Goal chat on QCon.** "I want to learn how to evaluate LLM apps" → only QCon talks (check that the codes are in the QCon graph).
- [ ] **Step 3: AI Engineer.** Click it → it ends `not_found` with a "doesn't list any talks yet" or similar reason. Click again → the saved result shows at once with "checked … ago".
- [ ] **Step 4: Paste a link.** On the AI Engineer screen, paste `https://qconsf.com/schedule/nov2026` → expected: `not_found` with the different-event reason, since QCon's dates don't overlap Nov 10–12. This proves the pasted link still goes through the right-event check.
- [ ] **Step 5: Universe regression.** The flow map, goal chat, path, "I attended this" and readings behave as before. Run `uv run pytest -q`; all pass.
- [ ] **Step 6: Update the README** and `check_setup.py`, then commit with message `Docs: any conference can be built into a map`.
