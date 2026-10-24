# Throughline

**Patch the Conference Hackathon · Saturday, October 24, 2026 · San Francisco**
**Track: FalkorDB** · Also uses Bright Data and OpenAI

> Throughline is a readiness agent for conferences. Tell it the talk you care about, and it builds your path there: what to learn first, in what order, and where to learn it before the talk starts. It remembers what you've learned as you move through the event, and every answer is traced through the graph to its source.

---

## The problem

A conference schedule is a long list of talks with times and rooms. It doesn't tell you the one thing that decides whether a talk is worth your hour: are you ready for it?

Advanced talks assume you already know things, and those things often depend on other things. The session that teaches them might be earlier that day, the day before, at the same time as something else you want to see, or not at the conference at all. Nobody tells you, so you walk in, get lost in the first ten minutes, and the hour is gone. And because nothing keeps track of what you've already learned, every talk feels like starting over.

Organizers have the mirror-image problem: they can't easily see which concepts many talks assume but no talk teaches.

We demonstrate on GitHub Universe 2026 (October 28–29), whose full schedule of 100+ sessions is already published.

## What Throughline does

1. **Pick a talk you care about.** Throughline unfolds everything it assumes, in order: to follow this talk you need B, and to understand B you need C. If the talk assumes nothing you're missing, it says so: **"You're ready."**
2. **Tell it what you already know.** It asks only about the handful of concepts on that talk's path. Your path skips what you know.
3. **Get your day plan.** For each step, the best place to learn it given the clock: an earlier talk you can attend, today or tomorrow morning before a day-2 talk, or a short explainer to watch in a gap. Clashes are flagged with a substitute.
4. **Talk to it as the day goes on.** "I just came out of the MCP security talk." "I'm free at 2. What should I do before the 3:30 agents talk?" Throughline updates what you know, moves the clock to the end of that talk, and re-plans.
5. **It remembers you.** Come back on day 2 with your code and your progress is still there.
6. **Click any answer to see why:** the agent's tool calls, the path through the graph, the exact phrase that justifies each link, the source, and when it was checked.

**For organizers:** a view of the concepts that many talks assume and no talk teaches.

## How it works

### The graph (FalkorDB)

- `(Talk)-[:REQUIRES]->(Concept)`, `(Talk)-[:TEACHES]->(Concept)`, `(Concept)-[:DEPENDS_ON]->(Concept)`, `(Resource)-[:EXPLAINS]->(Concept)`, `(Talk)-[:IN_SLOT]->(TimeSlot)`
- **Attendee memory:** `(Attendee)-[:KNOWS {how: "said" | "attended"}]->(Concept)`, `(Attendee)-[:ATTENDED]->(Talk)`, `(Attendee)-[:TARGETS]->(Talk)`
- Every knowledge edge stores its evidence phrase, source link, confidence and when it was checked.

**Where `DEPENDS_ON` comes from.** If a talk `TEACHES` concept B and its abstract `REQUIRES` concept C, that talk is evidence that B depends on C. The edge stores which talk it came from and both abstract phrases, so it's checked word for word like every other edge. When several talks agree, confidence goes up. If two talks point in opposite directions, we keep the direction with more support. Paths stop at 3 steps, which also prevents loops.

Core queries:

- **Learning path:** variable-length traversal over `DEPENDS_ON` (up to 3 steps) from the target talk's required concepts, minus everything the attendee `KNOWS`, in dependency order. An empty path is a real answer: "You're ready."
- **Mark attended:** one multi-hop update. Attending a talk adds `KNOWS {how: "attended"}` for every concept that talk `TEACHES`, and moves the clock to the end of that talk, so the next path and plan update automatically.
- **Day plan:** walk the path in order. For each concept, pick the earliest teaching talk that starts after the clock, ends before the next step and the target talk, and doesn't clash with steps already planned; otherwise use an outside explainer. A simple greedy plan, chosen on purpose so it's fast and easy to explain.
- **Organizer view:** concepts with many `REQUIRES` edges and no `TEACHES` edge.

### The agent (OpenAI)

An OpenAI model is the conversational layer. It can only answer by calling graph tools:

| Tool | What it does |
|---|---|
| `get_learning_path(talk)` | Ordered concepts still to learn for this attendee |
| `find_where_to_learn(concept, after, before)` | Teaching talks in free slots, or outside explainers |
| `plan_day(target_talk)` | The full greedy plan with clashes flagged |
| `mark_attended(talk)` / `mark_known(concept)` | Updates the attendee's memory in the graph and moves the clock |
| `explain_step(step)` | The graph path, evidence phrase and source behind one answer |

If no tool returns an answer, the agent says it doesn't know. It never answers from its own knowledge. A trace panel shows every tool call and the graph path it returned.

OpenAI is also used offline to build the concept list and to propose edges with evidence. The concept list includes aliases, so "RAG" and "retrieval-augmented generation" become one node, and "memory," "context mechanics" and "token bloat" don't split one idea three ways.

### The data (Bright Data)

- **Browser API** loads the GitHub Universe session catalog. The catalog page renders its sessions with JavaScript, so its HTML contains no session data. The browser session records the JSON feed the page loads. *That feed also answers a plain request, so we say so, and use it as a cross-check and fallback.*
- **SERP API** finds short outside explainers for concepts the conference doesn't teach, live when the agent needs one.
- **When a scrape goes wrong:** if the catalog returns far fewer sessions than the last run, or required fields (title, time, abstract) are missing, we keep the last good snapshot and flag it on screen.

### How we keep answers honest

- **Evidence is checked, not trusted.** Every evidence phrase must appear word for word in its source, after cleaning up the text (tags stripped, HTML entities decoded, quotes straightened, whitespace collapsed). The source is the talk's title and abstract for `REQUIRES`, `TEACHES` and `DEPENDS_ON`. If the phrase isn't there, the edge is discarded. For `EXPLAINS`, the evidence is the explainer's search-result snippet from Bright Data; we don't fetch the page itself, so explainers are vetted by the model and labeled as outside sources.
- **Unsure is a real answer.** Edges below our confidence threshold are shown as "unsure." `REQUIRES` is always our inference, since abstracts rarely state their prerequisites, and it's labeled "assumed."
- **What the graph covers, plainly:** a talk's prerequisites come only from what the conference published for it: its title, its stated level (for example "Level 300: Advanced", which is evidence that it assumes the basics) and its abstract. We don't use concept definitions or our own judgment as evidence, so a prerequisite the speaker never signals isn't in the graph.
- **The agent only speaks from tool results,** and every tool result is a graph path you can open.
- **Fetched pages are data, never instructions.** Text on explainer pages is never followed as a command.
- **Explainers must pass a filter:** under 10 minutes to watch or read, from documentation or established educational sources, and checked by the model against the concept's definition.

## Measured quality

*Numbers we measured on the day from the live graph, not estimates.*

- Talks: 125 · Concepts: 70 · Edges: 419 (83 `REQUIRES`, 277 `TEACHES`, 46 `DEPENDS_ON`, 13 `EXPLAINS`)
- Coverage: 100% of required concepts have a teaching talk or an outside explainer. Talks assume 15 distinct concepts; 14 are taught by at least one talk, and the last one is covered by an outside explainer only.
- Accuracy: 20 randomly chosen `REQUIRES`/`TEACHES` edges (fixed seed) were checked against each talk's abstract; 15 were correct, 4 were only partly right (the phrase is real but the concept is a side mention, not what the talk teaches or assumes), and 1 was wrong (a migration story marked as teaching GitHub Actions workflows). This check was done by an AI reviewer, not a person, and should be spot-checked by one. Verdicts and reasons: [data/quality_handcheck.json](data/quality_handcheck.json).
- Baseline: on the 15 talks we hand-checked the evening before ([checks/prerequisite-baseline.json](checks/prerequisite-baseline.json)), the graph found at least one expected teaching talk for 6 of the 12 talks that have one; it matched 10 of the 23 expected teaching talks and missed 13. It also found 102 other earlier teaching talks the hand check didn't list (41 distinct talks); we have not checked those by hand yet, so we don't count them as right or wrong. The one talk that needs nothing first correctly says "You're ready."
- Evidence check: 0% of model-proposed edges were discarded for failing the word-for-word check (0 of 360). The model was asked to copy phrases exactly, and every phrase it gave was found in the talk's title or abstract.
- Edges marked "unsure" (confidence below 0.6): 10
- Orphan concepts (assumed by talks, taught by none): 1, "Browser-based agent testing" (it has an outside explainer)

To recompute every number here: `uv run python -m throughline.quality` (prints the report and writes `data/quality.json`).

## Demo plan (3 minutes)

1. A judge picks any talk from the schedule. If nothing is missing, Throughline says "You're ready."
2. We tell the agent which concepts the judge already knows; the path shrinks.
3. The agent shows the ordered path and day plan, including one clash and its substitute. The trace panel shows the tool calls.
4. We say, "I just came out of [an earlier talk]." The agent marks it attended, the clock moves to the end of that talk, and the path shrinks again.
5. We click one step and show the graph path, the evidence phrase and the source.
6. We close the tab and reopen with the same code: the memory is still there.
7. We close on the organizer view: the concepts this conference assumes but never teaches.

### What's live and what's prepared

| Part | Status |
|---|---|
| Schedule and abstracts | Scraped on the morning of the hackathon; last good snapshot kept as fallback |
| Concept list and knowledge graph | Built during the hackathon, loaded before the demo |
| Agent answers, path, plan and memory updates | Live, for whatever the judge picks |
| Explainer for an uncovered concept | Fetched live; a cached copy is used if the network is slow, and labeled "cached" on screen |
| Clock | Starts at Wednesday 8:30 AM (day 1, before the first talk), shown on screen, and moves forward when a talk is marked attended |
| Fallback | If the agent misbehaves, the same graph queries run from plain buttons, without the model |

## Build timeline

| Time | Work |
|---|---|
| 10:00–11:00 | *(During the workshops)* Repo created; FalkorDB running; all talks and time slots loaded from the snapshot; empty app with the clock and talk list |
| 11:00–12:00 | Scrape the schedule through Bright Data (snapshot as fallback); generate the concept list with aliases |
| 12:00–12:30 | Propose edges with evidence; derive `DEPENDS_ON`; run the word-for-word check |
| 12:30–1:00 | Lunch |
| 1:00–2:30 | Path, plan and mark-attended queries; plain button interface; "You're ready" screen; click-to-explain view |
| 2:30–3:30 | Agent with graph tools and trace panel; attendee memory |
| 3:30–4:15 | Live explainer fetch with fallback; organizer view |
| 4:00–4:15 | Hand-check edges; compare with the baseline; fill in measured quality |
| 4:15–4:30 | **Freeze features.** Rehearse the demo once |
| 4:30–5:00 | **Record the demo video** (screen recording, following the demo plan); upload it and check the link opens without logging in |
| 5:00–5:30 | Submit (repo link, video link, this document); rehearse the stage demo, once with the network off |

**Rule:** the plain button interface must work by 2:30. The agent is built on top of it, never instead of it.

## Scope

**Must ship:** everything in the timeline above.

**Stretch:** recordings of past talks as a third catch-up option, planning for several target talks at once, loading a second conference.

## Team

We're two.

- [Name]: data, concept extraction and evidence checks (Bright Data, OpenAI)
- [Name]: graph model, queries, memory, agent, interface and demo (FalkorDB, OpenAI)

The chat stays in scope. The plain buttons come first (the 2:30 rule), so the chat is always built on top of working features and never something they depend on.

## Our principles

- **Evidence for every answer.** Every link in the graph carries the text that justifies it, checked against the source.
- **Say when we're unsure,** and be honest about scheduling conflicts rather than hiding them.
- **Minimal attendee data.** Attendees get an anonymous code, not an account. We store only which concepts they know and which talks they attended, and they can delete it with one button.
- **Public data only** for everything else: public schedules, abstracts and explainer pages.

## If we're ahead or behind on time

**If we're ahead (in this order):**

1. Recordings of past talks as a third catch-up option, between "earlier talk" and "outside explainer."
2. Planning for two or three target talks at once, sharing prerequisites between them.
3. "Re-plan from here" when the attendee skips a planned step.
4. Loading a second conference to show the approach isn't tied to one schedule.

**If we're behind (cut in this order, and update this document to match):**

1. **The agent's chat.** Keep the same graph tools as plain buttons. Memory and mark-attended still work.
2. **The live explainer fetch.** Use explainers fetched earlier in the day, labeled "fetched at [time]."
3. **Reopening a session with a code.** Keep memory within the session only.
4. **The measured quality sample.** Shrink it to 15 edges, but never skip it.
5. **Last resort:** drop `DEPENDS_ON` and show one level of prerequisites. This removes the multi-hop path, so avoid it if at all possible. It should rarely be needed, because `DEPENDS_ON` comes from abstracts we already check.

**Never cut:** the evidence check, the click-to-explain view, the "You're ready" answer, the on-screen clock, or the model-free fallback.

---

## Before submitting (delete this section from the final version)

**The submission itself** *(the event website doesn't say; ask the organizers)*

- [ ] Where and how to submit, and the exact deadline (submission is during 2:00–5:30 PM)
- [x] A demo video is required on the submission page
- [ ] Demo video is 3–5 minutes, on YouTube (unlisted) or Google Drive ("anyone with the link"), submitted by 5:30 PM
- [ ] Whether a public repo is required, and how long each team's stage demo is

**The document**

- [ ] Every [N] and [X] in "Measured quality" is a number we actually measured
- [ ] The team section has real names, and the roles match our team size
- [ ] Anything we cut is removed from "What Throughline does," the demo plan and the timeline
- [ ] The data section is honest about the Browser API: the catalog page needs JavaScript, and the feed behind it also answers a plain request
- [ ] The repo is public, and the repo link and any demo video link open without logging in
- [ ] The track is stated as FalkorDB

**The data**

- [ ] The number of scraped sessions roughly matches the published schedule (100+)
- [ ] A random handful of talks have the right times, rooms and abstracts
- [ ] No concept appears twice under different names

**The demo**

- [ ] The on-screen clock starts at Wednesday 8:30 AM and moves when a talk is marked attended
- [ ] We've tested one talk of each kind from the baseline: a strong chain, a clash, a partial chain, one covered only later, one needing an outside explainer, and one that should say "You're ready"
- [ ] Mark-attended visibly shrinks the path
- [ ] Reopening with the code restores memory, and the delete button works
- [ ] The full demo runs with the network off, using the cached fallback
- [ ] The demo fits in 3 minutes, rehearsed at least twice
- [ ] No API keys are in the repo or visible on screen
