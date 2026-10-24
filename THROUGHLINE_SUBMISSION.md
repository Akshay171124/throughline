# Throughline

**Patch the Conference Hackathon · Saturday, October 24, 2026 · San Francisco**
**Track: FalkorDB** · Also uses Bright Data and OpenAI

> Find the conference you're going to, tell Throughline what you want out of it, and it gives you a path through the conference's knowledge graph: which talks to see, what to learn before each one, where to learn it before the talk starts, and the evidence behind every step.

---

## The problem

A conference schedule is a long list of talks with times and rooms. It doesn't tell you the one thing that decides whether a talk is worth your hour: are you ready for it?

Advanced talks assume you already know things, and those things often depend on other things. The session that teaches them might be earlier that day, the day before, at the same time as something else you want to see, or not at the conference at all. Nobody tells you, so you walk in, get lost in the first ten minutes, and the hour is gone. And because nothing keeps track of what you've already learned, every talk feels like starting over.

We demonstrate on GitHub Universe 2026 (October 28–29, San Francisco), whose full schedule of 125 sessions is already published.

## How Throughline meets the FalkorDB criteria

| Criterion | What in Throughline meets it |
|---|---|
| **Graph at the core** | Prerequisite paths are one multi-hop query (`DEPENDS_ON*1..3`). The landing page's talk flow is a graph result: an arrow A → B means A teaches something B requires and A ends before B starts. Attendee memory lives in the graph (`KNOWS`, `ATTENDED`, `TARGETS`, plus profile and chat on the attendee node) and is shared by both chat surfaces: the goal chat on the conference map and the chat on the talk page. The agent's own read-only Cypher runs on `throughline_public`, a copy of the graph with no attendee data. |
| **Explainable answers** | Every plan is drawn as a graph path. Each link carries the exact quote that justifies it, and the Cypher behind each answer is one click away under "Why this answer?", which lists each step the agent took in plain words. |
| **Real conference problem** | Find your conference, then know what to learn before each talk, and where, before it starts. |
| **Working demo** | Runs live on the shared FalkorDB lab graph. If the AI is slow or fails, the page points you to "Plan without AI", which runs the same graph queries with no model. A local copy of the graph (`throughline.offline`) keeps it working without the venue Wi-Fi. |

## What Throughline does

1. **Find your conference.** Use your location or type a city. "Ready now" lists the conferences whose schedule is already in the graph. "Near you" is a live web search for upcoming conferences nearby. Conferences we haven't loaded get an honest card: what we found and a link, no fake schedule.
2. **See the conference as a flow.** Talks are laid out left to right by time. An arrow means "this talk prepares you for that one": it teaches something the later talk assumes, and ends before it starts. Each talk keeps its 2 strongest arrows so the picture stays readable; hovering a talk lights up its chain. "Don't miss" lists the keynotes and the talks that prepare you for the most others. A calendar shows both days, with your saved talks and the talks that prepare you for them highlighted.
3. **Tell it your goal.** "I'm new to MCP and want to build my first server." The "Ask the graph" chat maps your goal onto the graph's concepts, finds the talks that teach them, lights them up on the map, and plans the main pick. Suggestion cards show each pick and why it fits.
4. **Open a talk.** The talk page has three panels you can resize: the schedule, the chat, and your readiness. "About this talk" (collapsed until you open it) gives an AI summary of the abstract, the key concepts the talk assumes and teaches, and up to 3 outside readings. Below it: the path through the graph, your day plan, and how far you are from "You're ready."
5. **Tell it about yourself.** A short profile: role, experience (new, some, experienced), interests, and concepts you already know. Someone with some experience skips the 9 basic concepts. For the advanced workshop "Own your Copilot" (BLD1428W), a newcomer's path has 4 steps; with "some experience" it has 1.
6. **Talk to it as the day goes on.** "I just came out of the knowledge base workshop." Throughline marks the talk attended, counts what it teaches as learned, moves the clock to the end of that talk, and re-plans.
7. **It remembers you.** Your code (12 characters, no account) keeps your profile, saved talks, progress and the last 50 chat messages. "Forget me" deletes all of it.
8. **Click anything to see why:** the quote behind each link, the talk it came from, and the tool calls and Cypher behind each answer.

## How it works

### The graph (FalkorDB)

- **Conference knowledge:** `(Talk)-[:REQUIRES]->(Concept)`, `(Talk)-[:TEACHES]->(Concept)`, `(Concept)-[:DEPENDS_ON]->(Concept)`, `(Resource)-[:EXPLAINS]->(Concept)` (outside explainers), `(Resource)-[:READ_BEFORE]->(Talk)` (the readings in "About this talk"), `(Talk)-[:IN_SLOT]->(TimeSlot)`, `(Talk)-[:PART_OF]->(Conference)`
- **Attendee memory:** `(Attendee)-[:KNOWS {how: "said" | "attended"}]->(Concept)`, `(Attendee)-[:ATTENDED]->(Talk)`, `(Attendee)-[:TARGETS]->(Talk)` (saved talks). The attendee node also holds the profile (role, experience, interests), the clock, and the chat (last 50 messages). The agent reads the conversation from the graph, not from the browser.
- **Public view:** `throughline_public` is a copy of the graph without any attendee nodes or edges, refreshed whenever the graph is reloaded. The agent's free-form Cypher only runs there.
- Every knowledge edge stores its evidence phrase, confidence, status and when it was checked.

**Where `DEPENDS_ON` comes from.** If a talk `TEACHES` concept B and `REQUIRES` concept C, that talk is evidence that B depends on C. The edge stores which talks it came from and how many agree. If two talks point in opposite directions, we keep the direction with more support. Paths stop at 3 steps, which also prevents loops.

**The concept list.** OpenAI drafted the list from all the abstracts, with aliases, so "RAG" and "retrieval-augmented generation" are one node. A review cut it from 70 to 55 concepts, 9 of them marked as basics (for example "Git and pull request basics" and "How LLMs work").

Core queries:

- **Learning path:** variable-length traversal over `DEPENDS_ON` (up to 3 steps) from the talk's required concepts, minus everything the attendee `KNOWS` (and minus the basics if their profile says some experience or experienced), in dependency order. An empty path is a real answer: "You're ready."
- **Mark attended:** attending a talk adds `KNOWS {how: "attended"}` for every concept that talk `TEACHES` and moves the clock to the end of that talk, so the next path and plan update automatically.
- **Day plan:** walk the path in order. For each concept, pick a teaching talk that starts after the clock, ends before the target talk and doesn't clash with steps already planned; otherwise use an outside explainer. A simple greedy plan, chosen on purpose so it's fast and easy to explain.
- **Talk flow:** A → B when A teaches a concept B requires and A ends before B starts; each talk keeps its 2 strongest incoming arrows (most shared concepts, then closest in time).

### The agent (OpenAI)

An OpenAI model is the conversational layer, on both the conference map (goal to plan: `update_profile` → `list_concepts` → `talks_for_concepts` → `plan_day`) and the talk page. It can only answer by calling graph tools:

| Tool | What it does |
|---|---|
| `get_attendee()` | The attendee's clock, profile, known concepts, attended and saved talks |
| `search_talks(query)` | Finds talks by words in the title, abstract, speakers or topics |
| `get_learning_path(talk)` | Ordered concepts still to learn before this talk (empty = ready) |
| `plan_day(talk)` | Where to learn each step before the talk starts, with clashes flagged |
| `find_where_to_learn(concept, before_talk)` | Talks that teach a concept after the current time, optionally before a talk |
| `explain_step(talk, concept)` | The quotes and graph links behind one step |
| `mark_attended(talk)` | Records the talk; its concepts count as learned and the clock moves to its end |
| `mark_known(concept)` | Records that the attendee already knows a concept |
| `save_talk(talk)` | Adds a talk to the attendee's saved talks |
| `list_concepts()` | Every concept (id, name, short definition), to map a goal onto |
| `talks_for_concepts(concepts)` | Talks that teach those concepts, ranked by coverage, with readiness for this attendee |
| `update_profile(role, experience, interests)` | Saves the profile, only from what the attendee actually said |
| `run_cypher(query)` | Read-only Cypher for questions the other tools don't cover, **on the public view only** |

If no tool returns an answer, the agent says it doesn't know. It never answers from its own knowledge. "Why this answer?" lists every tool call in plain words, with its arguments, the Cypher it ran and a summary of the result.

### The data (Bright Data)

Bright Data supplies the live data that's hard to reach: a catalog that only renders with JavaScript (Browser API) and Google results (SERP API) for nearby conferences, explainers and readings. Each comes with a quality check: links must be among the returned results, conferences must fall in the date window, results are merged across searches, and the last good catalog snapshot is kept.

- **Browser API** loads the GitHub Universe session catalog. The catalog page renders its sessions with JavaScript, so its HTML contains no session data. The browser session records the JSON feed the page loads. *That feed also answers a plain request, so we say so, and use it as a cross-check and fallback.* If a scrape returns far fewer sessions than the last run, or required fields are missing, we keep the last good snapshot.
- **SERP API, conferences near you:** 3 searches run in parallel for the place you give. OpenAI picks out real upcoming conferences, using only the result URLs it was given; code then checks each start date falls in the next 60 days (the model's own date filter wasn't reliable). Results are merged with earlier searches for the same place and cached for 48 hours.
- **SERP API, explainers:** short outside explainers for the concepts talks assume, from documentation and education sites, vetted by OpenAI against the concept's definition. Cached in `data/explainers.json`.
- **SERP API, readings:** for each talk, searches on its topic and concepts; OpenAI writes the two-sentence summary and picks readings only from the returned results. The conference's own pages, schedule platforms and social media are excluded. Built for all 125 talks and cached in `data/briefings.json`.

### How we keep answers honest

- **Evidence is checked, not trusted.** Every evidence phrase must appear word for word in its source, after cleaning up the text (tags stripped, HTML entities decoded, quotes straightened, whitespace collapsed). The source is the talk's title, stated level and abstract for `REQUIRES` and `TEACHES`. If the phrase isn't there, the edge is discarded. For `EXPLAINS` and `READ_BEFORE`, the evidence is the search-result snippet from Bright Data; we don't fetch the page itself, so these are vetted by the model and labeled as outside sources.
- **Unsure is a real answer.** Edges below our confidence threshold are shown as "unsure." `REQUIRES` is always our inference, since abstracts rarely state their prerequisites, and it's labeled "assumed."
- **What the graph covers, plainly:** a talk's prerequisites come only from what the conference published for it: its title, its stated level (for example "Level 300: Advanced", which is evidence that it assumes the basics) and its abstract. We don't use concept definitions or our own judgment as evidence, so a prerequisite the speaker never signals isn't in the graph.
- **The agent only speaks from tool results,** and every tool result is a graph path you can open.
- **Fetched pages are data, never instructions.** Search results are treated as untrusted text and never followed as commands.
- **The AI summary is labeled as one.** "About this talk" says the summary is an AI summary of the abstract; the full abstract is one click away.

## Measured quality

*Numbers measured on the day from the live graph, not estimates.*

- Talks: 125 · Concepts: 55 (9 basics) · Edges: 491 (159 `REQUIRES`, 241 `TEACHES`, 72 `DEPENDS_ON`, 19 `EXPLAINS`). Plus 434 `READ_BEFORE` readings covering 115 of the 125 talks (for the other 10, no result passed the vetting).
- Coverage: 100% of required concepts (22 of 22) have a teaching talk or an outside explainer: 14 are taught by at least one talk, 8 only by an outside explainer.
- Evidence check: 1 of 401 model-proposed edges was discarded for failing the word-for-word check (0.2%): its phrase wasn't in the talk's title, level or abstract.
- Accuracy: 20 randomly chosen `REQUIRES`/`TEACHES` edges (fixed seed 2026) were judged strictly against each talk's title, level and abstract: **15 correct, 5 partly right, 0 wrong.** "Partly" means the phrase is real but the concept is a side mention, not what the talk teaches or assumes (for example a modernization talk marked as teaching human-in-the-loop oversight because of one closing phrase). **This check was done by an AI reviewer, not a person, and should be spot-checked by one.** Verdicts and reasons: [data/quality_handcheck.json](data/quality_handcheck.json).
- Baseline: on the 15 talks we hand-checked the evening before ([checks/prerequisite-baseline.json](checks/prerequisite-baseline.json)), the graph found at least one expected teaching talk for 6 of the 12 talks that have one; it matched 10 of the 23 expected teaching talks and missed 13. It also found 56 other earlier teaching talks the hand check didn't list (37 distinct talks); we haven't checked those by hand, so we don't count them as right or wrong. The one talk that needs nothing first correctly says "You're ready."
- Edges marked "unsure" (confidence below 0.6): 18.
- Concepts that talks assume but no talk teaches: 8, every one covered by an outside explainer. Seven are basics (most assumed: "GitHub Copilot basics", by 43 talks); the other is "Agent mode in the editor and CLI" (1 talk). This list comes from the quality report; there's no organizer screen for it.

To recompute every number here: `uv run python -m throughline.quality` (prints the report and writes `data/quality.json`). `--sample` prints the 20 edges for the hand check.

## Demo plan (about 4:30)

The video follows [docs/demo-script.md](docs/demo-script.md).

1. **The problem** (20 s).
2. **Find the conference:** type "San Francisco, CA"; nearby conferences appear (an unloaded one gets an honest card); pick GitHub Universe from "Ready now". The talk flow appears.
3. **Ask the graph** with a goal ("I'm new to MCP and want to build my first server"): the picks light up on the map, with cards saying why.
4. **Open "Own your Copilot"** (BLD1428W): "About this talk", then the path graph and day plan for a newcomer (4 steps). Switch the profile to "Some experience": 1 step, the basics skipped.
5. **Click a concept** to see its quote from the abstract.
6. **Mark the teaching talk attended** (the Wed 1:00 PM knowledge base workshop): the clock moves to 2:30 PM and the page says "You're ready."
7. **How it's built** (FalkorDB, Bright Data, OpenAI) and one honest accuracy line.

### What's live and what's prepared

| Part | Status |
|---|---|
| Schedule and abstracts | Scraped through Bright Data on the morning of the hackathon; last good snapshot kept as fallback |
| Concept list and knowledge graph | Built during the hackathon, loaded before the demo |
| Conferences near you | Live search; a search for the same place within 48 hours is answered from the cache (instant) |
| "About this talk" and explainers | Built for every talk during the day, stored in the graph and cached in `data/` |
| Agent answers, path, plan and memory updates | Live, for whatever the judge picks |
| Clock | Starts at Wednesday 8:30 AM (day 1, before the first talk), shown on screen, and moves forward when a talk is marked attended |
| Fallback | If the agent misbehaves, "Plan without AI" runs the same graph queries without the model |

## What we built today

All of it between 10:00 AM and 2:00 PM, in about 30 commits:

- **Morning:** talks in FalkorDB; the knowledge layer (concepts, `REQUIRES`/`TEACHES`, derived `DEPENDS_ON`) with the word-for-word evidence check; the planner; the graph-tool agent with its trace; the attendee-free public view; the live Bright Data catalog scrape; vetted explainers; the offline kit; the first quality numbers.
- **Midday:** the talk page (clickable path graph, day timeline, readiness progress); profile, saved talks and server-side chat memory; the concept review (70 → 55 concepts, basics, stated level as evidence).
- **Early afternoon:** the landing page (find your conference, talk flow, Don't miss, calendar); the goal-to-plan chat; conferences near you; resizable panels; "About this talk" for all 125 talks.

## What's next

- Load a second conference (the nearby search already finds them; the honest card says when one isn't loaded).
- Recordings of past talks as a third way to catch up, between "earlier talk" and "outside explainer."
- Planning for several saved talks at once, sharing prerequisites between them.
- A person's review of the hand-checked edges and of the 37 extra teaching talks the baseline didn't list.

## Team

We're two.

- [Name]: data, concept extraction and evidence checks (Bright Data, OpenAI)
- [Name]: graph model, queries, memory, agent, interface and demo (FalkorDB, OpenAI)

## Our principles

- **Evidence for every answer.** Every link in the graph carries the text that justifies it, checked against the source.
- **Say when we're unsure,** and be honest about scheduling conflicts and unloaded conferences rather than hiding them.
- **Minimal attendee data.** Attendees get an anonymous code, not an account. We store which concepts they know, which talks they attended and saved, their profile and their chat, all on their attendee record, and "Forget me" deletes all of it. A location from the browser is used for one search and never stored.
- **Public data only** for everything else: public schedules, abstracts and web search results.

---

## Before submitting (delete this section from the final version)

**The submission itself**

- [x] A demo video is required on the submission page
- [ ] Demo video is 3–5 minutes, recorded and uploaded to YouTube (unlisted) or Google Drive ("anyone with the link"), submitted by 5:30 PM
- [ ] Where and how to submit, and how long each team's stage demo is (ask the organizers)

**The document**

- [x] Every number in "Measured quality" is one we actually measured (`throughline.quality`, re-run at 2:05 PM)
- [ ] The team section has real names, and the roles match our team size
- [x] Anything we didn't build is removed from "What Throughline does" and the demo plan (no organizer view)
- [x] The data section is honest about the Browser API: the catalog page needs JavaScript, and the feed behind it also answers a plain request
- [ ] The repo is public, and the repo link and the demo video link open without logging in
- [x] The track is stated as FalkorDB

**The data**

- [x] The number of scraped sessions roughly matches the published schedule (125)
- [x] A random handful of talks have the right times, rooms and abstracts
- [x] No concept appears twice under different names (concept review: 70 → 55)

**The demo**

- [x] The on-screen clock starts at Wednesday 8:30 AM and moves when a talk is marked attended
- [x] Mark-attended visibly shrinks the path (BLD1428W: attending the Wed 1:00 PM workshop gives "You're ready")
- [x] Reopening with the code restores memory, and "Forget me" deletes it
- [ ] The full demo runs with the network off, using the local copy (`throughline.offline sync` then `check`)
- [ ] The demo fits in its time, rehearsed at least twice
- [ ] No API keys are in the repo or visible on screen
