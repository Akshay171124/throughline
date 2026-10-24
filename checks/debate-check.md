# Debate check (Friday, October 23)

**Question:** can we find at least 3 clear, sourced pairs of Universe speakers who take different positions on the same question?

**Verdict: narrow GO.** We found 3 pairs: 1 high confidence, 2 medium. Every quote passed a word-for-word check. Two passed only after the page text was cleaned up or against YouTube's automatic captions, as noted below. All speakers are confirmed on the Universe 2026 schedule.

## Pair 1: How should open source projects treat outside code now that agents write it? **(high)**

| | Speaker A | Speaker B |
|---|---|---|
| **Who** | Adam Jacob (Swamp Club) | William Woodruff (OpenAI; primary maintainer of zizmor) |
| **Universe talk** | *Write-only code: What happens to peer review when agents write the diffs* (Thu 10:00) | *Security by default: a maintainer's wishlist for GitHub Actions v2* (Wed 16:30) |
| **Own words** | "So no, you will never, and Swamp will never accept a pull request from anyone ever." | "The zizmor project welcomes AI contributions. However, AI contributions are required to have demonstrated human effort behind them." |
| **Source** | [Changelog & Friends #130 transcript](https://podscripts.co/podcasts/the-changelog-software-development-open-source/automation-at-the-speed-of-swamp-friends), May 13, 2026 | [zizmor AI_POLICY.md](https://github.com/zizmorcore/.github/blob/main/AI_POLICY.md), created Mar 9, 2026, updated Sep 4, 2026 |
| **Evidence type** | Podcast transcript made by a third party; the official transcript isn't out yet. The Swamp CONTRIBUTING.md backs it up. | Project policy he wrote; all commits are his. |
| **Word-for-word check** | Passed | Passed after joining line breaks |

Franck Nijhof's policy (Pair 2) takes a similar line to Woodruff's, so a fourth pair on this question is possible.

## Pair 2: Does someone need to read and understand AI-written code before it ships? **(medium)**

| | Speaker A | Speaker B |
|---|---|---|
| **Who** | Kent C. Dodds (kody.codes) | Franck Nijhof (Open Home Foundation) |
| **Universe talk** | *What's worth building when AI can build anything?* (Thu 9:50, main stage) | *Code is the easy part: Building Home Assistant in the open* (Wed 14:10) |
| **Own words** | "I didn't read that diff line by line. I read the outcome: does it do what we decided it should do, and did the gates I trust pass?" | "You must understand and be able to explain every change you submit, in your own words." |
| **Source** | [kentcdodds.com: You own the outcome](https://kentcdodds.com/blog/you-own-the-outcome), Sep 24, 2026 | [Home Assistant AI policy](https://developers.home-assistant.io/blog/2026/07/20/ai-policy/), Jul 20, 2026 |
| **Word-for-word check** | Passed after cleanup (HTML entities) | Passed |

**Why medium:** the contexts differ. Kent is describing his own product, with gates he trusts. Franck is setting a rule for outside contributors. Dylan Ratcliffe takes Kent's side: "the vast majority of the code that we ship to production today is not read by anyone, including the author," from DevOpsDays London, Sep 21, 2026, auto-captions only.

## Pair 3: Is generative AI good or bad for accessibility right now? **(medium)**

Both speakers are on the same Universe panel: *Accelerate accessibility with AI and automation* (Wed 13:30).

| | Speaker A | Speaker B |
|---|---|---|
| **Who** | Ed Summers (GitHub) | Eric Bailey |
| **Own words** | "I think we have a renaissance coming. A renaissance of accomplishment for the disability community thanks to tools like GitHub Copilot." | "How something is built is just as important as the results it produces—reference LLMs' bias towards producing inaccessible code as an immediate concern." |
| **Source** | [Ability Summit 2026 keynote](https://www.youtube.com/watch?v=Db_AC115Cw0), Jun 3, 2026 | [ericwbailey.website](https://ericwbailey.website/published/evolved-antennas-llm-generated-code-and-a-potential-antifuture/), May 11, 2026 |
| **Word-for-word check** | Passed **against auto-captions only**. Check against the audio before showing. | Passed after cleanup (inline link) |

**Why medium:** their overall stances clearly differ, but each emphasizes a different part of the question.

## What didn't produce a pair

- **Adam Jacob vs. Dylan Ratcliffe:** their shared abstract says they disagree "hard," but their public words mostly agree. Lesson: **don't trust an abstract's claim of disagreement.**
- **Many specialized agents vs. deterministic coordination:** quotes exist, but one side calls their work a deliberately extreme experiment. Low confidence.
- **Specs as contracts vs. hypotheses:** both sides are abstracts only, so it's weak.
- **Measuring output vs. outcomes:** everyone agrees outcomes matter.
- **Agents merging without a human:** GitHub's counter-position is product marketing in the same post that launches "Agent Merge," so it isn't a clean opposite.

**Where real disagreement lives:** among independents and open source maintainers. GitHub, Microsoft and sponsor "positions" were mostly product framing.

## Lessons for the pipeline

- **Clean text before the word-for-word check.** A plain search missed real quotes about a third of the time because of inline links, HTML entities (`&#39;`, `&#8217;`), curly quotes and line-wrapped markdown. Strip tags, decode entities, straighten quotes and collapse whitespace first. YouTube descriptions sit inside JSON in the raw HTML.
- **YouTube captions:** free downloads got rate-limited (HTTP 429) after about two videos. Use Bright Data for these on Saturday.
- **Name and company variants are everywhere.** Two matching signals per source is the right rule. Examples:
  - Adam Jacob appears under three company names.
  - Baruch Sadogursky is listed at three companies.
  - Eric Bailey is listed as "Independent," but his bio says he works at GitHub.
  - Several look-alike sources were written by someone else: a colleague's post, an organizer's page, a similar name on a podcast.
- **Fetched pages contained hidden instructions aimed at AI tools**, such as "Ignore all previous instructions…". Our OpenAI steps must treat page text strictly as data.
- **Time per speaker:** about 10–15 minutes by hand for someone with a public footprint, about 5 to rule someone out. About 14 speakers were checked.
- **What worked best:** personal blogs and project policy files, which are bylined, dated and checkable through commit history. Also YouTube search with the video description read for speaker names.
