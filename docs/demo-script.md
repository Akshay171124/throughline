# Throughline demo video script (target 4:00)

For judges who are engineers but haven't seen the project. It follows the "Demo plan" in [THROUGHLINE_SUBMISSION.md](../THROUGHLINE_SUBMISSION.md). Every talk, time and number below is real data from the graph on Oct 24. The page is being redesigned, so the beats name what to click by what it does ("the talk's node", "the trace panel"), not where it sits on screen.

**The demo story.** One attendee, one fresh code, clock at **Wed Oct 28, 8:30 AM**.

1. Target: **"Own your Copilot: Advanced customization for developers and platform teams"** (BLD1428W, Thu 11:30, Workshops @ Gateway Pavilion, Level 1). Path: *AI coding agents* and *Copilot customization layers*, both taught Thu 9:00 at **"Stop prompting, start delegating: Configure Copilot to own the work"** (BLD1072S, 9:00 to 9:45).
2. After marking BLD1072S attended, BLD1428W says **"You're ready."**
3. The clash: after also attending **"What's worth building when AI can build anything?"** (BLD1886M, Thu 9:50 to 10:20, Main Stage), the clock is Thu 10:20. Target: **"Discover, install, and manage agent skills from your terminal with gh skill"** (TRU1452D, Thu 12:55). Its plan:
   - *Agent skills*: "Plugins and engines: Extending GitHub Copilot live" (LDR1185D, 12:25 to 12:40)
   - *GitHub Actions workflows*: "AI, Actions, and tooling: Coinbase's move to GitHub…" (LDR1765B, 11:00 to 11:40). **The talk's abstract never mentions Actions.** It's on the path because the graph has *Agentic workflows* DEPENDS_ON *GitHub Actions workflows*, backed by 5 other talks' abstracts.
   - *Agentic workflows*: **clash flagged.** The only talk that teaches it in time, "The night shift" (LDR1684B, 12:00 to 12:40), overlaps "Plugins and engines", so the plan sends you to an outside explainer instead.

   This is the only clash in the current graph. With the clock at 8:30 no plan has one; it shows up only once the morning is used up. That makes it a good story, not a staged one.

---

## The script

| Time | On screen | Click / type | Voice-over |
|---|---|---|---|
| **0:00–0:20** | Throughline home. Clock reads Wed Oct 28, 8:30 AM. Schedule of 125 GitHub Universe talks. | Nothing. Slowly scroll the talk list. | "A conference schedule tells you when and where. It doesn't tell you whether you're ready. Advanced talks assume things you might not know, and the session that teaches them might be earlier, at the same time, or nowhere. Throughline answers one question: am I ready for this talk, and if not, what do I do before it starts?" |
| **0:20–0:35** | Same screen. | Nothing. | "Under the hood is a FalkorDB graph. Talks point to the concepts they **require** and the concepts they **teach**, and concepts point to the concepts they **depend on**. Every link carries the exact phrase from the abstract that justifies it." |
| **0:35–1:00** | Search box, then the talk's detail and its path graph. | Type `Own your Copilot` in search. Click the talk. Click **Get me ready**. | "Say a judge picks the expert Copilot workshop on Thursday at 11:30. Its abstract opens with 'You know how to use GitHub Copilot', so it assumes two things: AI coding agents, and Copilot's customization layers." |
| **1:00–1:20** | Path graph: two concept nodes, then one. | Click the **AI coding agents** node, then **I already know this**. (Or type: `I already know how AI coding agents work.`) | "Tell it what you already know. It only asks about the concepts on this path, and the path shrinks." |
| **1:20–1:45** | The day plan: Thu 9:00, "Stop prompting, start delegating", Fort Mason Building C. Trace panel lists the tool calls and their Cypher. | Point at the day plan, then at the trace panel. | "Here's the plan. Thursday at nine, well before the workshop, there's a 45-minute sandbox that teaches exactly this. On the right is every tool the agent called and the graph query it ran. The agent can't answer from its own knowledge, only from the graph." |
| **1:45–2:10** | Clock jumps to Thu Oct 29, 9:45 AM. The path empties: **"You're ready."** | Type: `I just came out of Stop prompting, start delegating.` | "It's Thursday morning and I just came out of that session. It's marked attended, the clock moves to the end of the talk, and everything that talk teaches counts as learned. The path is empty: you're ready." |
| **2:10–2:35** | Clock jumps to Thu 10:20. New target's plan, with a clash note on *Agentic workflows*. | Type: `I also just came out of What's worth building when AI can build anything?` then `Get me ready for the gh skill talk at 12:55.` | "Now a harder one. It's 10:20, and I want the agent-skills demo at 12:55. Three things to learn. The only session left that teaches agentic workflows overlaps the one I need for agent skills, so Throughline says so and sends me to a short outside explainer instead of hiding the conflict." |
| **2:35–3:00** | Path graph: the *Agentic workflows* node with an arrow to *GitHub Actions workflows*. Trace panel open on the `DEPENDS_ON*1..3` query. | Click the trace step for the learning path so its Cypher shows. Point at `[:DEPENDS_ON*1..3]`. | "This is where the graph does real work. This talk never mentions GitHub Actions. But five other talks teach agentic workflows and assume Actions, so the graph has a link: agentic workflows depend on Actions. One variable-length query walks up to three of those links, which is how a prerequisite you'd never guess ends up on your path." |
| **3:00–3:20** | The evidence view for that link: the two quoted phrases, the talk they came from, the source link, and when it was checked. | Click the **Agentic workflows → GitHub Actions workflows** link (or that step). | "Click any step to see why. This link comes from 'The night shift' talk, which teaches 'putting Copilot agents to work on your own platform maintenance' and requires 'self-hosted GitHub Actions infrastructure'. Both phrases are checked word for word against the abstract, with a link to the source." |
| **3:20–3:35** | New tab, same page. Same code, clock still Thu 10:20, the attended talks still there. | Copy the code shown on screen. Close the tab. Open `localhost:8000` again (if it starts fresh, click **Use another** and paste the code). | "Close the tab and come back with your code. No account; the code is all it keeps, and Forget me deletes it. Your progress is still there." |
| **3:35–3:50** | Optional: organizer view listing *Browser-based agent testing*. If there's no organizer view, show the terminal output of `uv run python -m throughline.quality`. | Open the organizer view (or switch to the terminal window). | "For organizers, the mirror image: concepts the talks assume and no talk teaches. Here there's one, browser-based agent testing. On accuracy: every one of the 360 links the model proposed passed the word-for-word check. An AI review of 20 random links found 15 correct, 4 partly right and 1 wrong, and we flag 10 links as 'unsure' on screen." |
| **3:50–4:00** | Back to the "You're ready" screen. | Nothing. | "Throughline: pick the talk you care about, and walk in ready. Every answer traced through the graph to its source." |

**If the agent misbehaves on camera:** use **Plan without AI** on the talk. It runs the same graph queries with no model, so beats 3 to 8 still work. Mark talks attended with **I attended this** on the talk itself.

**If you're over time:** shorten the 1:00–1:20 beat (skip "I already know this") and cut the organizer view. Never cut the trace / `DEPENDS_ON` beat or the evidence click.

---

## Pre-recording checklist

- [ ] Server is running on port 8000 and `uv run python -m throughline.check_setup` passes.
- [ ] **Fresh attendee code:** click **Forget me**. The clock should read **Wed Oct 28, 8:30 AM** and the code should be new.
- [ ] Rehearse the whole story once and confirm: BLD1428W's plan points to BLD1072S at Thu 9:00; after attending it, BLD1428W says "You're ready"; after attending BLD1886M, the TRU1452D plan shows the clash note on *Agentic workflows*. Then click **Forget me** again before recording.
- [ ] Check what the clash step offers: an outside explainer, or "needs an explainer" if none is cached. Match the voice-over line to what's on screen.
- [ ] Browser zoom set so the path graph and trace panel are readable at 1080p (try 110 to 125%).
- [ ] Close other tabs, notifications off (Do Not Disturb), no terminal showing `.env` or API keys, no bookmarks bar with personal links.
- [ ] Network check: load one page on a site you don't usually visit; the agent and the FalkorDB lab need a connection. If the network is flaky, record with **Plan without AI**.
- [ ] Typed lines copied somewhere off-screen so you can paste them without typos.
- [ ] Water nearby, quiet room, phone on silent.

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
