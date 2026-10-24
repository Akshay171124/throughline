# Prerequisite test (Friday, October 23)

**Question:** do GitHub Universe 2026 abstracts support "what you need to know first, and which earlier talk teaches it," with chains worth showing?

**Verdict: GO.** Of 15 talks checked by hand, 8 have a strong chain and 3 more have a usable one. The other 4 are useful cases too: they test whether the pipeline knows when to say "later," "outside explainer" or "nothing needed."

**How we tested:**
- **The 10 advanced talks:** all 10 Level 300 talks.
- **5 intermediate talks**, picked by a fixed rule (every 15th Level 200 talk by start time) so we didn't choose easy ones.
- For each, we listed what the talk assumes you already know, then searched every earlier talk at any level for one that teaches it. The extraction was done by hand, reading the abstracts the way our OpenAI prompt will.

This tests whether the *data* supports the feature, not how well the prompt works. The machine-readable version for Saturday's comparison is [prerequisite-baseline.json](prerequisite-baseline.json).

> **Correction to the first pass:** we had marked *How GitHub taught Copilot to remember* as having no earlier teacher. *Shut the context window!* (Wed 10:30) teaches exactly what it builds on, "a mental model of context mechanics." Our keyword search missed it because that abstract never says "memory." Two counts in the first write-up were also wrong and are fixed below.

## Results

### Strong chains (8)

| Talk | What it assumes | Earlier talks that teach it |
|---|---|---|
| **Own your Copilot: Advanced customization** (Thu 11:30, L300 workshop) | Copilot customization layers. The abstract says so outright: "You know how to use GitHub Copilot… No beginner basics." | Thu 9:00 *Stop prompting, start delegating* (L100), then Thu 10:15 *Turn repeated workflows into Copilot CLI skills* (L100). Same morning, no overlap. |
| **The 2am RCA agent** (Thu 9:30, L300) | On-call agents, alert triage | Wed 11:30 *Four primitives… on-call agent's autonomy* (L200); Wed 13:30 *Alert to pull request in minutes* (L200); Wed 14:05 *Copilot Automations* (L100) |
| **17 agents, one SDLC: Levi Strauss** (Thu 12:15, L300) | Custom agents, several agents reviewing each PR, MCP | Wed 16:05 *What Copilot code review catches*, which builds "a custom agent… with focused sub-agents" (L200); Wed 13:00 *Developer knowledge base*, an MCP server workshop (L100) |
| **We shipped governance** (Thu 11:00, L300) | Policy as code, rulesets | Thu 9:35 *When a prototype becomes critical* (L100); Thu 9:00 *Admin readiness for AI usage management* (L200). **These two overlap**, so the planner has to pick one. |
| **Automating PR quality with Copilot CLI and Actions** (Thu 10:40, L300) | Copilot CLI | Wed 15:25 *Rediscover the command line* (L100); Wed 11:20 *Octolamp: Copilot CLI hooks* (L100) |
| **How GitHub taught Copilot to remember** (Wed 11:30, L300) | How Copilot builds context | Wed 10:30 *Shut the context window!* (L200) |
| **What happens between pressing Enter and getting a response** (Wed 15:30, L200 workshop) | Context windows, token cost ("What are AI credits…?") | Wed 10:30 *Shut the context window!* (L200); Wed 11:40 *Real ways we cut token costs* (L200) |
| **The night shift: Copilot agents that maintain their own runners** (Thu 12:00, L200) | Cloud agents, autonomy based on risk, policy gates | Wed 12:20 *Low Orbit Agentic Cannon*, on routing tickets to cloud agents (L200); Wed 11:30 *Four primitives…*, which promotes and demotes "autonomy… per decision class" (L200); Thu 9:35 *When a prototype becomes critical*, on rulesets (L100) |

### Usable chains (3): the link is real but general

| Talk | Earlier talks |
|---|---|
| **Beyond pass or fail: How agents verify AI code** (Thu 9:00, L300) | Wed 14:25 *Self-validating agentic loop* (L300), which builds on Wed 11:15 *Agents close the loop* (L100). A 3-step chain. |
| **Build a self-validating agentic loop** (Wed 14:25, L300) | Wed 11:15 *Agents close the loop* (L100) |
| **Building Copilot in the cloud** (Wed 15:40, L300) | Wed 12:20 *Low Orbit Agentic Cannon* (L200) |

### The other 4: what the pipeline should say when there's no chain

| Talk | What the right answer is |
|---|---|
| **The O(1) patch: Nix supply chain** (Wed 13:40, L300) | **Partial.** Supply chain basics are covered earlier: Wed 11:10 *Package Firewall* and Wed 11:50 *JFrog supply chain controls*. Reproducible builds are only covered later, at Wed 16:40 *Bluefin CI/CD*. |
| **Four primitives to evaluate your on-call agent's autonomy** (Wed 11:30, L200) | **Later only.** Nothing earlier covers on-call work. Wed 13:30 *Alert to pull request* and Wed 14:05 *Copilot Automations* cover it afterwards. |
| **Auth for agents: auth.md** (Wed 13:50, L200) | **Outside explainer.** It assumes you know API keys, OAuth and short-lived credentials, and no Universe talk teaches those. Later related talks: Wed 15:40 *Building Copilot in the cloud* and Wed 16:30 *Connecting Copilot*. |
| **The view from the labs** (Thu 9:00, L200 main-stage panel) | **No prerequisites needed.** It's a forward-looking panel. The pipeline should return nothing here, and inventing prerequisites counts as an error. |

## What this changes in the plan

1. **Allow "earlier in the conference," not just "earlier today."** 5 of the 11 chains need a talk from an earlier day. *(The first write-up said "6 of 8"; that was wrong. The real number for those 8 was 4.)*
2. **Don't limit "teaches" to introductory talks.** In 6 of the 8 strong chains, at least one key teacher is an intermediate talk. Use the level as a weak hint, not a filter.
3. **"Needs" is always our inference.** Only 1 of 15 abstracts states its prerequisites. Label those links "assumed."
4. **The same concept goes by different names.** "Memory," "context mechanics" and "token bloat" describe one idea. The merged concept list has to catch synonyms, or the graph will miss teachers, just as our keyword search did.
5. **Compare against the baseline in three buckets, not two.** On Saturday, every pipeline answer is *matched*, *missed*, or *new*. A *new* teacher isn't automatically wrong, because our hand check missed one too. Check those by hand before counting them.
6. **The pipeline must be allowed to say "nothing."** One of the 15 needs no prerequisites, one needs an outside explainer, and one has teachers only later in the day.
7. **"Advanced" often means *deep on one thing*.** 6 of the 10 advanced talks are 15-minute show-and-tells or product demos. *(The first write-up said 7.)*
8. **Talks that clash make a good demo.** The governance talk's two teachers overlap, which shows the time rule doing real work.

## Best demo chains

- **"Plan my Thursday morning" for *Own your Copilot*:** 9:00 then 10:15 then 11:30. The prerequisite is stated outright, it's all on the same day with no clashes, and every step is a real Universe session.
- **"Lost at 9:30" for *The 2am RCA agent*:** two Wednesday talks prepared you for it.
- **"Chains cross topic tags" for *The night shift*:** it pulls together a sponsored on-call demo, a cloud-agents show-and-tell and a policy demo, each under different tags.

## Bonus: talks that take different approaches

Reading the abstracts turned up talks that solve the same problem *differently*. These are contrasts in approach, taken from the session descriptions, not personal positions:
- **Incident response:** NeuBird's "multi-agent incident resolution" (Wed 13:30) vs. the 2am RCA agent, where "the LLM only handles 4 of 10 nodes… fully deterministic" (Thu 9:30).
- **Supply chain:** JFrog's approach is to "replace… vulnerable dependencies with patched versions" (Wed 11:50). The O(1) patch talk argues that "scanning… node-by-node… is an O(n) problem: by the time you know… you're already too late" (Wed 13:40).
