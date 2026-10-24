# Throughline demo video script (target 4:30, allowed 3–5 minutes)

For judges who are engineers but haven't seen the project. It follows the "Demo plan" in [THROUGHLINE_SUBMISSION.md](../THROUGHLINE_SUBMISSION.md). Every talk, time and number below was checked against the graph on Oct 24 at about 2:10 PM (plans computed for a temporary attendee that was deleted afterwards).

**The facts the script relies on**

- "San Francisco, CA" is in the nearby cache (searched 1:27 PM, kept 48 hours), so the search is instant. It shows 4 conferences, none loaded: QCon San Francisco 2026 (Nov 16), AI Engineer Code Summit 2026 (Nov 10), AI Engineer Conference (Nov 10), AI Dev 26 x SF (no date). GitHub Universe is under **Ready now**. Type the city exactly as `San Francisco, CA`: "San Francisco, California" is a different cache entry with only 2 results.
- Target talk: **"Own your Copilot: Advanced customization for developers and platform teams"** (BLD1428W), Thursday 11:30 AM–1:00 PM, Workshops @ Gateway Pavilion, Level 1, **Level 300: Advanced**.
- It requires *GitHub Copilot basics* (quote: **"You know how to use GitHub Copilot."**) and *Copilot customization* (quote from the title: "Advanced customization for developers and platform teams").
- **Newcomer (no profile, or "New to this"): 4 steps.** Command-line basics (talk BLD1491D, Wed 3:25 PM), Git and pull request basics (explainer, GitHub Docs "Pull requests", 5 min), GitHub Copilot basics (explainer, Microsoft Learn "Introduction to GitHub Copilot", 10 min), Copilot customization. The first three come in through `DEPENDS_ON`: Copilot customization depends on Copilot basics (8 talks agree), Git basics (2) and command-line basics (2).
- **"Some experience": 1 step.** Copilot customization, learned at **"Building a developer knowledge base for GitHub Copilot"** (LDR1716W), **Wednesday 1:00–2:30 PM**, Workshops @ Gateway Pavilion, Level 1. The three basics show as already known "from your profile".
- **Mark LDR1716W attended:** the clock moves from Wed 8:30 AM to **Wed 2:30 PM**, and BLD1428W says **"You're ready."**
- "About this talk" for BLD1428W: an AI summary ("This workshop is about the different ways to customize GitHub Copilot across the app, web, and CLI…") and 3 readings shown (4 stored), e.g. GitHub Docs "Add custom instructions for Copilot".
- Accuracy: 400 of 401 proposed links passed the word-for-word check; an AI review of 20 random links found 15 correct, 5 partly right, 0 wrong; 18 links are flagged "unsure".

---

## The script

| Time | On screen | Click / type | Voice-over |
|---|---|---|---|
| **0:00–0:20** | Landing page: "Find the conference you're going to". | Nothing. | "A conference schedule tells you when and where. It doesn't tell you whether you're ready. Advanced talks assume things you might not know, and the session that teaches them might be earlier, at the same time, or nowhere. Throughline answers: what should I learn before this talk, and where?" |
| **0:20–0:45** | "Near you" fills with 4 conferences, each marked "Schedule not loaded". "Ready now" shows GitHub Universe. | Click the city box, type `San Francisco, CA`, click **Search**. Click **Details** on QCon San Francisco for one second, then **← All conferences**. | "Start by finding your conference. This is a live web search through Bright Data, and OpenAI picks out real conferences, only from links the search returned, and we check the dates in code. Conferences we haven't loaded say so honestly. GitHub Universe, next week, is loaded." |
| **0:45–1:10** | GitHub Universe card → the Talk flow map. | Click **Open the map →** on GitHub Universe. Hover one talk with arrows to light its chain. | "This is the whole conference as a graph. Talks run left to right in time. An arrow means this talk prepares you for that one: it teaches something the later talk assumes, and ends before it starts. Hover a talk and its chain lights up." |
| **1:10–1:45** | "Ask the graph" panel: the agent's reply, talks highlighted on the map, suggestion cards. | Click the example chip **I'm new to MCP and want to build my first server** (or type it and click **Send**). Wait for the answer. Point at the highlighted talks and one card. Open **Why this answer?** for a second. | "Tell it your goal in your own words. The agent maps the goal onto the graph's concepts, finds the talks that teach them, and plans the main one. The picks light up on the map. It can only answer through graph tools: here's every step it took." |
| **1:45–2:15** | Talk page for "Own your Copilot". "About this talk" opened: summary, key concepts, 3 readings. | Click **Calendar**, then Thursday 11:30 **Own your Copilot** (or open `localhost:8000/talk.html?code=BLD1428W`). If a "New here?" card appears, click **Not now**. Click **About this talk** to open it. | "Now a single talk: an advanced Copilot workshop on Thursday. 'About this talk' is an AI summary of the abstract, the concepts it assumes and teaches, and a few outside readings Bright Data found and OpenAI vetted, never the conference's own pages." |
| **2:15–2:45** | Path graph: 4 concepts leading to the talk; the day plan beside it. | If the path isn't drawn yet, click **Plan without AI**. Point at the 4 concept boxes, then the day plan. | "For a newcomer, the graph unfolds four steps. The talk says 'you know how to use GitHub Copilot', and Copilot customization in turn depends on Copilot basics, Git and the command line. That's one multi-hop query: up to three DEPENDS_ON links. The day plan says where to learn each: a Wednesday talk, or a short explainer." |
| **2:45–3:00** | Concept detail for *GitHub Copilot basics*: the quote "You know how to use GitHub Copilot." | Click the **GitHub Copilot basics** box. | "Click any step for the evidence. This is the exact sentence from the abstract. Every link is checked word for word against the talk's title, level and abstract, or it's thrown out." |
| **3:00–3:20** | Path shrinks to 1 step: Copilot customization, learn it Wed 1:00 PM at "Building a developer knowledge base for GitHub Copilot". | Click **Set up profile** (top right), Experience **Some experience**, **Save profile**, close the dialog. | "Tell it about yourself. With some experience, the basics are skipped. Same talk, one step: a Wednesday workshop that teaches Copilot customization." |
| **3:20–3:40** | Clock jumps from Wed 8:30 AM to Wed 2:30 PM. The path empties: **"You're ready."** | Click the **Building a developer knowledge base** box in the path (or that talk in the schedule), then **I attended this**. | "It's Wednesday afternoon and I went. Everything that workshop teaches now counts as learned, the clock moves to the end of the talk, and the plan re-runs: you're ready. That memory lives in the graph, so it's there tomorrow, and Forget me deletes it." |
| **3:40–4:15** | Back to the path graph (or the map). | Nothing. | "How it's built. FalkorDB is the core: multi-hop prerequisite paths, the prepares-you-for flow, and each attendee's memory, profile and chat, all in the graph. The agent can also write its own read-only Cypher, but only against a copy of the graph with no attendee data. Bright Data brings in the hard-to-reach data: the JavaScript-rendered catalog, nearby conferences, explainers and readings. OpenAI extracted the concepts with word-for-word evidence, and runs the agent, which only answers through graph tools." |
| **4:15–4:30** | Same screen. | Nothing. | "Honestly measured: 400 of 401 proposed links passed the word-for-word check. An AI review of 20 random links found 15 correct, 5 partly right and none wrong, and we flag 18 links as unsure. Throughline: find your conference, tell it your goal, and walk in ready." |

**If the agent is slow or fails on camera (1:10 beat):** skip to the talk page; the rest of the script uses only graph queries ("Plan without AI", profile, I attended this), no model.

**If you're over time:** drop the QCon detail card (0:20 beat) and the "Why this answer?" glance. Never cut the 4 → 1 steps beat, the evidence click or "You're ready."

---

## Pre-recording checklist

- [ ] Server is running on port 8000 and `uv run python -m throughline.check_setup` passes.
- [ ] **Fresh browser profile or a private window**, so you get a new attendee code with no profile, the clock at **Wed Oct 28, 8:30 AM** and no saved city. (Or click **Forget me** on the talk page.)
- [ ] **Warm the nearby search** with the exact text `San Francisco, CA` once before recording; it should come back instantly.
- [ ] Rehearse once and confirm: BLD1428W shows 4 steps with no profile; 1 step after "Some experience"; attending LDR1716W moves the clock to Wed 2:30 PM and says "You're ready". Then start again in a fresh private window.
- [ ] Hard refresh (Cmd+Shift+R) so the newest page code is loaded.
- [ ] Browser zoom set so the map, path graph and chat are readable at 1080p (try 110 to 125%). Drag the talk page panels so the path graph has room.
- [ ] Close other tabs, notifications off (Do Not Disturb), no terminal showing `.env` or API keys, bookmarks bar hidden.
- [ ] Network check: the agent and the FalkorDB lab need a connection.
- [ ] Typed lines copied somewhere off-screen so you can paste them without typos.
- [ ] Quiet room, phone on silent.

## Recording on macOS

1. Press **Cmd+Shift+5**.
2. Pick **Record Selected Portion** and drag the box around the browser window only.
3. **Options** → Microphone → pick your mic (built-in is fine in a quiet room). Turn on "Show Mouse Clicks" if offered.
4. Click **Record**. Wait two seconds before speaking.
5. To stop, click the stop button in the menu bar, or press **Cmd+Control+Esc**. The file lands on the Desktop as a `.mov`.
6. Watch it once all the way through with sound. Check it's between 3 and 5 minutes.

## Upload

- **YouTube (unlisted):** youtube.com → Create → Upload video → pick the `.mov` → under Visibility choose **Unlisted** → Save. Copy the link.
- **Or Google Drive:** upload the file → right-click → Share → General access → **Anyone with the link** (Viewer) → Copy link.
- **Check the link in a private window** (Cmd+Shift+N in Chrome) while logged out. It must play without signing in. Drive needs a few minutes to process a video before it plays.
- Paste the link into the submission form before 5:30 PM.
