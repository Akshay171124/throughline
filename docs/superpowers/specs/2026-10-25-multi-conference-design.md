# Every conference gets a map

Design for making Throughline work for any conference the nearby search finds, not just GitHub Universe 2026.

## Why

Throughline's promise is "know what to learn before each talk", at any conference. Today the landing page searches the live web for conferences near you, but only GitHub Universe can be opened. Every other result says "Schedule not loaded" and leads nowhere. The search finds conferences; nothing turns them into maps. This project closes that gap.

The app is for Akshay's own use for now. It is not shared with anyone, so there are no spending limits or access rules on builds.

## What it does

1. **Click any conference.** If it has no map yet, a build screen opens and shows progress in plain steps: finding the schedule, reading the talks, linking concepts. It takes a few minutes.
2. **The map opens when the build finishes.** It is the same experience Universe has today: the talk flow map, the goal chat, "Don't miss", the calendar, the talk page with its path, "Why this answer?" and "About this talk". Everything is limited to the chosen conference.
3. **It's saved.** A built map is stored, so the next visit opens instantly.
4. **Partial schedules are labeled.** If only some talks could be read, the map still opens, with a label at the top such as "Partial schedule: 12 talks found". The label says what was left out, for example "8 listed without times were left out".
5. **Nothing found is said plainly.** If no talks could be found, the build screen ends with what was tried and why it failed. Example: "We looked at ai.engineer/code/2026, but this conference hasn't published its talks yet." It offers two actions:
   - **"Open the conference site"**
   - **"I have the schedule link"**: the user pastes an agenda page URL and the build retries from there.
   The failure is saved with the time it was checked. The next visit shows "No schedule found yet (checked 2 hours ago)" at once, with a "Try again" button, instead of repeating the wait.

## Goals

- Any conference from the nearby search can become a working map. If its own site doesn't lead to a schedule, a schedule URL the user pastes on the failure screen can.
- The builder works on sites we have not seen before, starting with QCon San Francisco.
- Universe keeps working exactly as it does now: same graph, same data, same tests.

## Non-goals (for this project)

- Importers for Sessionize or Sched. They could be a fast path later; no upcoming conference we checked has a published Sessionize schedule.
- Spending limits, logins or rate limits on builds.
- Automatic refreshes of an already built conference. "Try again" exists only for failed or partial builds.
- Hand review of each new conference's concept list. Universe's list was reviewed by a person; new conferences rely on the automatic checks below.
- Splitting `web/app.js` and `web/landing.js` into smaller files. That's worth doing, but as its own change.

## Anti-goals (failure even if it "works")

- **Made-up talks or times.** Every talk on a map must come from a real page. A talk whose title is not on the page is dropped. A talk without a date, a start time, and an end time or a stated duration is dropped and counted in the partial label. Times are never guessed, including from the next slot on the schedule.
- **Mapping the wrong event.** A conference site often links to past years and other cities. A map built from another event's schedule is a failure even though its talks are real.
- **Conferences mixing.** No talk, concept, path or chat answer from one conference may appear in another.
- **A silent partial map.** If anything was left out, the map says so.
- **Breaking Universe.**

## Test conferences

These come from the nearby search results checked on Oct 25, 2026:

- **QCon San Francisco (Nov 16–20, 2026): the main test.**
  - Home page: https://qconsf.com/. Schedule: https://qconsf.com/schedule/nov2026.
  - About 89 talks with day, start time, room, track and speakers, all in the plain HTML.
  - The listing shows only start times (slot headers like "10:35AM PST") and a one-to-three-sentence abstract teaser.
  - Each talk links to `/presentation/nov2026/<slug>`. That page has the full abstract and the duration, e.g. "10:35AM PST (50 minutes)". Some say "Details coming soon".
  - Talks are tagged "Beginner / Intermediate / Advanced Topic" rather than 100/200/300.
- **AI Engineer Code Summit (Nov 10–12, 2026): the "not published yet" test.**
  - Page: https://ai.engineer/code/2026. It says "FULL AGENDA SOON".
  - It lists about 39 speakers with company and format (talk or workshop), but no talk titles or descriptions.
  - Expected result: the "nothing found" screen. It must not build a map out of speaker names.

## Decisions

### Made with Akshay

- Maps are built **when someone first clicks** a conference. The user waits on a build screen, then sees the map. Nothing is built ahead of time.
- The partial, nothing-found, paste-a-link and saved-failure behaviour above.
- Same rules as Universe: talks come from a real page; each concept link quotes the talk's own words and is checked in code.
- Use QCon and AI Engineer Code Summit as the test cases.
- No limits on builds.

### Claude's calls (Akshay can overrule)

- **Stack.** Keep what exists: Python/FastAPI, FalkorDB, OpenAI (`gpt-5.5` for extraction, `gpt-5.4-mini` for the agent) and Bright Data (Browser API, SERP API).
- **One FalkorDB graph per conference.** Each conference's talks, concepts, edges and attendee memory live in their own graph.
  - Universe keeps its current graph name (`throughline`).
  - New conferences get `throughline_c_<conference id>`, each with its own `_public` copy for free-form Cypher.
  - Why: every existing query (flow, planner, agent tools, briefing, explainers) keeps working unchanged against "the conference's graph". Data cannot mix, and concept ids can't collide.
  - The alternative, one big graph with a conference filter on every query, touches every query and fails silently when one is missed.
- **A small registry graph** (`throughline_registry`) holds one `Conference` node per conference. Fields:
  - id, name, dates, start/end date, location, website URL, schedule URL, graph name
  - build status: `none`, `building`, `ready`, `partial`, `failed`, `not_found`
  - current build step, counts (talks kept, talks dropped and why), `checked_at`, and the failure reason in plain words
  - `clock_start`
  Universe is registered from the current settings on startup. `GET /api/conferences` reads the registry.
- **Attendees.**
  - The attendee code is global.
  - The profile (role, experience, interests) is shared across conferences and lives in the registry graph, on an `Account` node keyed by code. Each conference graph has its own `Attendee` node with the same code for known concepts, attended talks, saved talks, chat and clock.
  - Creating an attendee creates the `Account`; the per-conference `Attendee` node is created on first use in that conference.
  - "Forget me" deletes the `Account` and every per-conference `Attendee` node with that code.
  - The registry graph is never exposed to `run_cypher`.
  - The `Account` is the source of truth for the profile. It is copied onto the conference's own `Attendee` node when that node is created and whenever the profile is newer than the copy, so the planner and flow keep reading it from the conference graph unchanged (and `tests/test_memory.py` keeps passing).
  - On startup, every existing Universe `Attendee` that has a profile but no `Account` gets one, copied from its profile. Codes already saved in browsers keep working.
- **Conference clock.** For a new conference it starts at 08:30 on its first talk day, or 30 minutes before its first talk if that is earlier. It is stored on the registry node. Universe keeps `CLOCK_START`.
- **Conference id.** A slug from the name plus the year, for example `qcon-san-francisco-2026`. Two search results are the same conference when their websites share a domain and their dates overlap. For example, "AI Engineer Conference" at ai.engineer/ and "AI Engineer Code Summit 2026" at ai.engineer/code/2026, both Nov 10–12, are one conference. When one has no dates, fall back to a name match. The same conference found twice never builds twice.
- **How the build finds talks** (a general importer, not a per-site scraper):
  1. Start from the pasted schedule URL if there is one, else the conference website.
  2. Load the page. Try a plain HTTP fetch first; use the Bright Data Browser API if the plain page has too little text (it renders with JavaScript) or the fetch is blocked.
  3. If the page is not itself a schedule, the model picks the schedule/agenda/program link from the page's own links. It may only choose a link that is on the page. Follow at most 2 such hops.
  4. The model extracts talks from the schedule page text as structured JSON: title, date, start, end, room, track, type, level if stated, speakers, short abstract if present, and detail URL if linked. Long pages are processed in chunks.
  5. **Verification in code**: each title must appear in the page text (using the existing `evidence.normalize`), and each detail URL must be one of the page's links. Failures are dropped and counted.
  6. **Every talk with a detail page has that page fetched** (up to 300 pages, a few at a time). The detail page's full abstract replaces the listing's teaser, and its time and duration fill in a missing end time. Abstracts and the time strings used must appear in that page's text, checked in code. Placeholders such as "Details coming soon" count as no abstract; such talks stay on the map but get no concept links.
  7. **End time** = a stated end time, else start + a stated duration (e.g. "(50 minutes)"). Both must be on the listing or the detail page. Never inferred from the next slot. Keep talks with a title, date, start and end.
  8. **Right event check.** When the conference has known dates, at least 80% of kept talks must fall within those dates (±1 day). Otherwise the build ends `not_found` with "The schedule we found is for a different event (dates Nov 2025)". Talks outside the dates are dropped. When the search gave no dates, the dates come from the talks and are shown on the card. Fewer than 5 kept talks means `not_found`, with the reason (no schedule page found, page has no talks yet, or the page needs a login).
  9. `partial` means some talk-like entries were dropped, or detail pages failed. The counts go in the label.
- **Concepts per conference.**
  - The existing two-step extraction runs on the new conference's talks: first a concept list, then per-talk REQUIRES/TEACHES with word-for-word evidence.
  - Two changes to the concept step: the examples in `CONCEPTS_PROMPT` are made conference-neutral, and the model also marks which concepts are foundations (`basic`), which a person did by hand for Universe.
  - Then the same `load_edges` evidence check and `derive_depends_on`.
- **Talk codes.** New conferences have none, so generate a stable short code from the conference id and the title.
- **Levels and sponsors.** A stated level maps to 100/200/300: Beginner/Introductory → 100, Intermediate → 200, Advanced/Expert → 300 (QCon's "Beginner / Intermediate / Advanced Topic" tags). The planner prefers level-100 talks, and the extraction prompt uses the level line as evidence for foundation concepts. No level means no badge and `level_num` 0. `sponsor` is true only if the page says the talk is sponsored.
- **Readings ("About this talk") are built when a talk is first opened**, using the existing `briefing.build`, and stored. They are not built for every talk during the map build, which keeps the wait shorter. While building, the card shows "Finding readings…".
- **Outside explainers** (for concepts no talk teaches in time) run at the end of the build, after the map is already marked `ready`, so they don't add to the wait. A path opened before they finish simply has no outside explainer yet.
- **"Try again" on a partial or failed build** builds into a fresh graph. It is swapped in only if it kept more talks than the current map; otherwise the current map stays, and the screen says the retry found less.
  - On a swap, attendee data carries over: attended and saved talks match by talk code (codes come from conference + title, so they're stable); "I know this" marks match by concept name or alias. Marks that match nothing are dropped.
  - `knowledge.reload_all`'s delete-missing-concepts behaviour never runs on a live conference graph.
- **"I have the schedule link"** appears only on the nothing-found and partial screens of a conference that's already in the registry. It is not a standalone way to add conferences. The pasted URL may be on another site (Sessionize, Sched, a venue site); the right-event check above still applies.
- **Build runs in a background thread** in the API process. The build screen polls a status endpoint every 2 seconds.
  - On startup, any registry node still marked `building` becomes `failed` with "The build was interrupted", so it can be retried.
  - Only one build per conference at a time; a second click joins the running build.
- **API shape.**
  - Every conference-scoped endpoint takes `conf` (the conference id), defaulting to `universe26` so existing links keep working.
  - New endpoints:
    - `POST /api/conferences/{id}/build`, with an optional `schedule_url` body. Starts a build, or joins a running one.
    - `GET /api/conferences/{id}/build`, which returns status, step, counts and reason.
  - Nearby search results get a registry id and status, so cards can show "Map ready", "Partial", "No schedule yet (checked …)" or "Build the map".
- **Front end.**
  - The chosen conference is carried in the URL (`?conf=<id>`) on both pages and sent on every API call. `throughline.conference` in local storage remembers the last one.
  - The agent's system prompt is built per request from the conference's registry record instead of the module-level constant.
- **Nearby search bug fix.** Results whose URL is a Google redirect (`google.com/goto?...`, `google.com/url?...`) must be unwrapped to the real target URL, or dropped if they can't be. The Boston search stored such a link.

## Left to the builder

- Prompt wording for the schedule-link pick and the talk extraction, and the chunk size for long pages.
- How the build screen looks, as long as it shows the plain steps, an elapsed time and the outcome states above.
- The exact "too little text" threshold for switching from a plain fetch to the Browser API.
- Code layout. A new `throughline/importer.py` (find and read a schedule), `throughline/registry.py` (conferences, accounts, status) and `throughline/build.py` (the pipeline and background job) is the suggested shape.

## How we'll know it's done

- Clicking QCon San Francisco builds a map that opens with its talks on the flow map, with end times from the stated durations and full abstracts from the talk pages. The label is "Partial schedule" if some talks were dropped.
- The ai.engineer/ result (which links to last year's /code/2025 schedule) never builds a 2025 map. It merges with the Code Summit 2026 entry and ends on the not-published-yet screen.
- On QCon, a goal in the chat ("I want to learn how to evaluate LLM apps") returns QCon talks only.
- A QCon talk page shows a path and, after a short wait, readings.
- Clicking AI Engineer Code Summit ends on the nothing-found screen with a plain reason, and the saved failure shows at once on the next click.
- Pasting a schedule URL into "I have the schedule link" starts a build from that page.
- Universe opens and behaves exactly as before, and the existing 93 tests still pass.
- New tests cover these, using saved copies of the QCon and AI Engineer pages and stubbed model responses, so tests make no network or OpenAI calls:
  - title verification drops invented talks
  - talks without times are dropped and counted; a stated duration gives the end time
  - a schedule from the wrong dates is rejected
  - a worse retry doesn't replace a partial map, and a swap keeps attendee marks
  - fewer than 5 talks gives `not_found`
  - two conference graphs never mix in flow, path or agent tool results
  - "Forget me" removes the attendee everywhere
  - Google redirect URLs are unwrapped
