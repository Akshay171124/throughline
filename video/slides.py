"""Slides for the demo video, rendered to 1920x1080 PNGs in video/out/slides/.

  uv run python video/slides.py

Graph and data numbers are read from data/quality.json and data/briefings.json so the
slides stay true. Timings were measured on the hosted FalkorDB lab (see TIMINGS).
"""

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "video" / "out" / "slides"

# Measured on the hosted FalkorDB lab on Oct 24, 2026 (network included).
TIMINGS = {"multihop_ms": 66, "path_s": "0.3", "dayplan_s": "1.6", "flow_s": "0.8"}
FLOW_LINKS = 227  # "prepares you for" links, as the talk flow reports ("the 47 strongest of 227 links")

LOGO = """<svg viewBox="0 0 40 40"><rect x="1" y="1" width="38" height="38" rx="10" fill="#2f5bd3"/>
<path d="M8 27 C 14 27, 14 13, 20 13 S 26 27, 32 27" fill="none" stroke="white" stroke-width="3" stroke-linecap="round"/>
<circle cx="8" cy="27" r="3.2" fill="white"/><circle cx="20" cy="13" r="3.2" fill="white"/><circle cx="32" cy="27" r="3.2" fill="#ffc400"/></svg>"""

CSS = """
  html, body { margin: 0; width: 1920px; height: 1080px; }
  body { background: radial-gradient(1200px 700px at 30% 20%, #23408f 0%, #0d1530 60%, #070b1a 100%);
    color: #fff; font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; }
  .center { height: 100%; display: flex; align-items: center; justify-content: center; text-align: center; }
  .title svg { width: 140px; height: 140px; margin-bottom: 26px; }
  .title h1 { font-size: 120px; margin: 0 0 18px; letter-spacing: -2px; }
  .title .tag { font-size: 50px; font-weight: 500; color: #dfe7ff; margin: 0 0 56px; }
  .title .meta { font-size: 40px; color: #dfe7ff; margin: 12px 0; }
  .title .meta.dim { color: #aebde8; font-size: 36px; }

  .section .n { font-size: 34px; letter-spacing: 6px; color: #8fb0ff; font-weight: 800; text-transform: uppercase; }
  .section h1 { font-size: 110px; margin: 20px 0 22px; letter-spacing: -2px; }
  .section p { font-size: 40px; color: #c9d6f7; margin: 0; }
  .section .bar { width: 160px; height: 8px; border-radius: 4px; background: #ffc400; margin: 34px auto 0; }

  .slide { box-sizing: border-box; height: 100%; padding: 80px 110px 70px; display: flex; flex-direction: column; }
  .head { display: flex; align-items: center; gap: 28px; }
  .head svg { width: 72px; height: 72px; flex: none; }
  .kicker { font-size: 26px; letter-spacing: 3px; text-transform: uppercase; color: #8fb0ff; font-weight: 700; }
  h2 { font-size: 66px; margin: 6px 0 0; letter-spacing: -1px; }
  .grid { margin-top: 48px; display: grid; gap: 26px; }
  .cols2 { grid-template-columns: 1fr 1fr; }
  .cols3 { grid-template-columns: 1fr 1fr 1fr; }
  .card { background: rgba(255,255,255,0.06); border: 1px solid rgba(160,185,255,0.22); border-radius: 22px;
    padding: 28px 34px; }
  .card b { display: block; font-size: 36px; margin-bottom: 10px; }
  .card span { font-size: 29px; line-height: 1.4; color: #d3ddf7; }
  .num { display: inline-flex; width: 46px; height: 46px; border-radius: 50%; background: #2f5bd3; color: #fff;
    align-items: center; justify-content: center; font-size: 26px; font-weight: 800; margin-right: 14px; vertical-align: 2px; }
  code { font-family: ui-monospace, Menlo, monospace; font-size: 0.92em; color: #ffd76a; }
  .powered { margin-top: auto; font-size: 36px; color: #eaf0ff; text-align: center; padding-top: 30px; }
  .powered strong { color: #ffd76a; }

  .big { font-size: 54px; font-weight: 800; color: #ffd76a; display: block; line-height: 1.05; }
  .tile { background: rgba(255,255,255,0.06); border: 1px solid rgba(160,185,255,0.22); border-radius: 22px; padding: 18px 26px; }
  .tile span { font-size: 26px; color: #d3ddf7; line-height: 1.35; display: block; margin-top: 8px; }
  .rowlabel { font-size: 26px; letter-spacing: 3px; text-transform: uppercase; color: #8fb0ff; font-weight: 700; margin: 26px 0 -30px; }

  .vs { display: grid; grid-template-columns: 1fr 1fr; gap: 30px; margin-top: 40px; }
  .vs .card b { font-size: 34px; }
  pre.q { font-family: ui-monospace, Menlo, monospace; font-size: 25px; line-height: 1.45; color: #ffd76a; margin: 8px 0 0;
    white-space: pre-wrap; }

  .pipe { margin-top: 56px; display: flex; flex-direction: column; gap: 46px; }
  .prow { display: flex; align-items: stretch; }
  .pbox { border-radius: 16px; padding: 20px 22px; font-size: 29px; line-height: 1.3; background: rgba(255,255,255,0.07);
    border: 1px solid rgba(160,185,255,0.3); display: flex; align-items: center; flex: 1; }
  .pbox.src { background: #0b5f6b; border-color: #66d9e8; font-weight: 800; flex: 0 0 210px; justify-content: center; text-align: center; }
  .pbox.db { background: #5a2d91; border-color: #c4a8ff; font-weight: 800; }
  .pbox.app { background: #1c2f66; border-color: #8fb0ff; font-weight: 800; flex: 0 0 170px; justify-content: center; text-align: center; }
  .bdres .card { padding: 40px 40px; }
  .bdres .card b { font-size: 44px; margin-bottom: 18px; }
  .bdres .card span { font-size: 35px; line-height: 1.45; }
  .arr { flex: 0 0 46px; display: flex; align-items: center; justify-content: center; color: #ffd76a; font-size: 34px; font-weight: 800; }
"""


def numbers() -> dict:
    q = json.loads((ROOT / "data" / "quality.json").read_text())
    briefings = json.loads((ROOT / "data" / "briefings.json").read_text())
    return {
        "talks": q["talks"], "concepts": q["concepts"], "edges": q["edges"]["total"],
        "depends": q["edges"]["DEPENDS_ON"], "explains": q["edges"]["EXPLAINS"],
        "kept": q["evidence_check"]["kept"], "proposed": q["evidence_check"]["proposed"],
        "briefed": len(briefings),
        "readings": sum(len(b.get("readings") or []) for b in briefings.values()),
    }


def head(kicker: str, title: str) -> str:
    return f'<div class="head">{LOGO}<div><div class="kicker">{kicker}</div><h2>{title}</h2></div></div>'


def section(n: int, title: str, sub: str) -> str:
    return f"""<div class="center section"><div><div class="n">Part {n}</div><h1>{title}</h1><p>{sub}</p><div class="bar"></div></div></div>"""


def schema_svg() -> str:
    # Node boxes: (x, y, w, h, label, kind)
    nodes = {
        "talk": (60, 150, 260, 90, "Talk", "talk"),
        "c1": (640, 150, 260, 90, "Concept", "concept"),
        "c2": (1220, 150, 260, 90, "Concept", "concept"),
        "teach": (1220, 420, 260, 90, "Earlier talk", "talk"),
        "slot": (60, 420, 260, 90, "TimeSlot", "slot"),
        "res": (640, 420, 260, 90, "Resource", "res"),
        "att": (1440, 10, 260, 80, "Attendee", "person"),
    }
    fill = {"talk": "#1c2f66", "concept": "#2f5bd3", "slot": "#24344f", "res": "#0b5f6b", "person": "#3a2a10"}
    stroke = {"talk": "#8fb0ff", "concept": "#b9ccff", "slot": "#8fa3c8", "res": "#66d9e8", "person": "#ffc400"}

    def box(k):
        x, y, w, h, label, kind = nodes[k]
        return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="18" fill="{fill[kind]}" stroke="{stroke[kind]}" stroke-width="3"/>'
                f'<text x="{x + w / 2}" y="{y + h / 2 + 11}" text-anchor="middle" font-size="32" font-weight="800" fill="#fff">{label}</text>')

    def edge(x1, y1, x2, y2, label, lx, ly, color="#ffd76a"):
        anchor = "end" if label == "KNOWS" else "middle"
        return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="4" marker-end="url(#a)"/>'
                f'<text x="{lx}" y="{ly}" text-anchor="{anchor}" font-size="24" font-weight="800" fill="{color}" '
                f'font-family="ui-monospace, Menlo, monospace">{label}</text>')

    edges = [
        edge(320, 195, 632, 195, "REQUIRES", 476, 182),
        edge(900, 195, 1212, 195, "DEPENDS_ON ×1..3", 1056, 182),
        edge(1350, 420, 1350, 248, "TEACHES", 1420, 340),
        edge(190, 240, 190, 412, "IN_SLOT", 250, 335),
        edge(770, 420, 770, 248, "EXPLAINS", 840, 340),
        edge(640, 465, 320, 225, "READ_BEFORE", 440, 380, "#7ee0ec"),
        edge(1570, 90, 1482, 158, "KNOWS", 1495, 122, "#ffc400"),
        edge(1640, 90, 1480, 440, "ATTENDED", 1660, 300, "#ffc400"),
        edge(1440, 50, 300, 146, "TARGETS (saved)", 860, 78, "#ffc400"),
    ]
    return f"""<svg viewBox="0 0 1720 530" width="1700" height="524" style="display:block;margin:34px auto 0;font-family:-apple-system,Helvetica,Arial,sans-serif">
      <defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M0 0L10 5L0 10z" fill="context-stroke"/></marker></defs>
      {''.join(edges)}{''.join(box(k) for k in nodes)}
    </svg>"""


def slides(n: dict) -> dict[str, str]:
    s = {}
    s["01_title"] = f"""<div class="center title"><div>{LOGO}<h1>Throughline</h1>
      <p class="tag">Know what to learn before each talk</p>
      <p class="meta">Team Git Lost: Vasudha Jain and Akshay Prajapati</p>
      <p class="meta dim">FalkorDB &nbsp;·&nbsp; Bright Data</p>
      <p class="meta" style="margin-top:36px;color:#ffd76a">Try it live: throughline-lisi.onrender.com</p></div></div>"""

    s["02_section_solution"] = section(2, "Our solution", "What Throughline does for you")
    s["02_solution"] = f"""<div class="slide">
      {head("Our solution", "Your path to every talk")}
      <div class="grid cols2">
        <div class="card"><b><span class="num">1</span>Find your conference</b><span>Type a city and see the conferences happening near you.</span></div>
        <div class="card"><b><span class="num">2</span>Say your goal</b><span>In your own words: "I'm new to MCP and want to build my first server."</span></div>
        <div class="card"><b><span class="num">3</span>Get your path</b><span>What to learn first, in what order, and where to learn it before the talk starts.</span></div>
        <div class="card"><b><span class="num">4</span>It remembers you</b><span>What you know and what you attended. The path shrinks until "You're ready."</span></div>
      </div>
      <div class="grid"><div class="card"><b><span class="num">5</span>Every answer is explained</b><span>See the path, the exact quote behind each step, and the queries that found it.</span></div></div>
      <div class="powered">Powered by a <strong>FalkorDB</strong> knowledge graph and live web data from <strong>Bright Data</strong></div>
    </div>"""

    s["03_section_demo"] = section(3, "Live demo", "The real app, recorded as it ran")

    s["04_section_falkordb"] = section(4, "What we achieved with FalkorDB", "Why a graph, how we built it, what it does")
    s["04_falkordb_why"] = f"""<div class="slide">
      {head("FalkorDB · why a graph", "Our data is connections, our questions are paths")}
      <div class="grid cols3">
        <div class="card"><b>Connections</b><span>Talks require and teach concepts. Concepts depend on other concepts. Attendees know concepts and attend talks.</span></div>
        <div class="card"><b>Paths</b><span>"What do I need before this talk, and what do those need?" That's prerequisites of prerequisites.</span></div>
        <div class="card"><b>Time rules</b><span>Learn it at a talk that ends before yours starts, and doesn't clash with the rest of your plan.</span></div>
      </div>
      <div class="vs">
        <div class="card"><b>In tables</b><span>Recursive joins across talks, concepts and attendees, rebuilt for every question.</span></div>
        <div class="card"><b>In FalkorDB: one traversal</b>
          <pre class="q">MATCH (:Talk {{code: $talk}})-[:REQUIRES]->(root:Concept)
MATCH p = (root)-[:DEPENDS_ON*1..3]->(:Concept)
UNWIND relationships(p) AS d
WITH DISTINCT d RETURN ...</pre>
          <span style="font-size:22px;color:#9fb0dd">The prerequisite query from our planner; what you already know is then subtracted.</span></div>
      </div>
    </div>"""
    s["04_falkordb_how"] = f"""<div class="slide">
      {head("FalkorDB · how we built it", "The graph schema")}
      {schema_svg()}
      <div class="grid cols2" style="margin-top:18px;gap:18px">
        <div class="card" style="padding:18px 26px"><span><code>DEPENDS_ON</code> is derived: a talk that teaches concept B and requires concept C is evidence that B depends on C.</span></div>
        <div class="card" style="padding:18px 26px"><span>"Prepares you for": <code>Talk→TEACHES→Concept←REQUIRES←Talk</code>, where the first talk ends before the second starts.</span></div>
        <div class="card" style="padding:18px 26px"><span>The agent answers only through <b style="display:inline;font-size:inherit">13 graph tools</b>.</span></div>
        <div class="card" style="padding:18px 26px"><span>Its free-form Cypher is read-only, on a copy of the graph with no attendee data.</span></div>
      </div>
    </div>"""
    s["04_falkordb_results"] = f"""<div class="slide">
      {head("FalkorDB · results", "Fast, personal, explainable")}
      <div class="rowlabel">The graph</div>
      <div class="grid" style="grid-template-columns:repeat(5,1fr)">
        <div class="tile"><b class="big">{n['talks']}</b><span>talks</span></div>
        <div class="tile"><b class="big">{n['concepts']}</b><span>concepts</span></div>
        <div class="tile"><b class="big">{n['edges']}</b><span>relationships</span></div>
        <div class="tile"><b class="big">{n['depends']}</b><span>DEPENDS_ON links</span></div>
        <div class="tile"><b class="big">{FLOW_LINKS}</b><span>prepares-you-for links</span></div>
      </div>
      <div class="rowlabel">Speed on the hosted FalkorDB lab, network included</div>
      <div class="grid" style="grid-template-columns:repeat(4,1fr)">
        <div class="tile"><b class="big">{TIMINGS['multihop_ms']} ms</b><span>multi-hop <code>DEPENDS_ON*1..3</code> query</span></div>
        <div class="tile"><b class="big">~{TIMINGS['path_s']} s</b><span>a learning path</span></div>
        <div class="tile"><b class="big">~{TIMINGS['dayplan_s']} s</b><span>a full day plan</span></div>
        <div class="tile"><b class="big">~{TIMINGS['flow_s']} s</b><span>the whole-conference flow</span></div>
      </div>
      <div class="rowlabel">Personal and explainable</div>
      <div class="grid cols3">
        <div class="tile"><b class="big">4 → 1</b><span>steps for the same talk: newcomer vs. some experience, from memory in the graph</span></div>
        <div class="tile"><b class="big">Path · quote · Cypher</b><span>behind every answer</span></div>
        <div class="tile"><b class="big">{n['kept']} / {n['proposed']}</b><span>extracted links passed the word-for-word evidence check</span></div>
      </div>
    </div>"""

    s["05_section_brightdata"] = section(5, "How we used Bright Data", "Why live web data, how it flows, what it gave us")
    s["05_brightdata_why"] = f"""<div class="slide">
      {head("Bright Data · why", "The data we need is live and hard to reach")}
      <div class="grid cols2" style="margin-top:60px">
        <div class="card"><b>The schedule renders with JavaScript</b><span>The session catalog page builds its list in the browser. A plain fetch of the page returns no session data.</span></div>
        <div class="card"><b>Search results change every day</b><span>Conferences near you and good readings need live Google results, which a basic script can't reliably get.</span></div>
      </div>
      <div class="grid cols2">
        <div class="card"><b>Browser API</b><span>A real remote browser loads the catalog and records the data feed the page uses.</span></div>
        <div class="card"><b>SERP API</b><span>Live search results for conferences near you, outside readings and explainers.</span></div>
      </div>
    </div>"""
    arr = '<div class="arr">→</div>'
    s["05_brightdata_how"] = f"""<div class="slide">
      {head("Bright Data · how it flows", "The data pipeline")}
      <div class="pipe">
        <div class="prow"><div class="pbox src">Browser API</div>{arr}<div class="pbox">Schedule: {n['talks']} talks, from the recorded data feed</div>{arr}
          <div class="pbox">OpenAI extraction, word-for-word evidence</div>{arr}<div class="pbox db">FalkorDB graph</div>{arr}<div class="pbox app">App</div></div>
        <div class="prow"><div class="pbox src">SERP API</div>{arr}<div class="pbox">3 parallel searches for your city</div>{arr}
          <div class="pbox">OpenAI keeps only conferences from returned URLs</div>{arr}<div class="pbox">Dates checked in code</div>{arr}<div class="pbox">Merged cache, 48 h</div>{arr}<div class="pbox app">Near you</div></div>
        <div class="prow"><div class="pbox src">SERP API</div>{arr}<div class="pbox">Readings and explainers for every talk and concept</div>{arr}
          <div class="pbox">OpenAI vetting; conference and social pages excluded</div>{arr}<div class="pbox db">(Resource) nodes in FalkorDB</div>{arr}<div class="pbox app">About this talk · Your day</div></div>
      </div>
      <div class="powered" style="font-size:32px">Grounded in what the search returned &nbsp;·&nbsp; checked in code &nbsp;·&nbsp; stored with its source and check time</div>
    </div>"""
    s["05_brightdata_results"] = f"""<div class="slide">
      {head("Bright Data · results", "Fresh, complete, checked")}
      <div class="grid cols3 bdres" style="margin-top:70px">
        <div class="card"><b>Freshness</b><span>A live re-scrape on the hackathon morning found <b style="display:inline;font-size:inherit">2 dropped talks, 2 new talks and 1 corrected abstract</b>. The graph was updated the same morning.</span></div>
        <div class="card"><b>Scale</b><span>All {n['talks']} talks. Readings for all {n['briefed']} talks: {n['readings']} vetted links stored, top 3 shown. {n['explains']} explainer links. 4 conferences found near San Francisco, plus Universe.</span></div>
        <div class="card"><b>Quality</b><span>Only URLs the search returned. Dates checked in code. Last good snapshot kept if a scrape looks broken. Every item keeps its source and when it was checked.</span></div>
      </div>
    </div>"""
    s["06_end"] = f"""<div class="center title"><div>{LOGO}
      <p class="tag" style="margin-bottom:30px;font-weight:700;font-size:60px;color:#fff">Built on FalkorDB, with live data from Bright Data</p>
      <p class="meta">Agent and extraction by OpenAI</p>
      <p class="meta" style="color:#ffd76a">Try it live: throughline-lisi.onrender.com</p>
      <p class="meta">github.com/Akshay171124/throughline</p>
      <p class="meta dim">Team Git Lost: Vasudha Jain and Akshay Prajapati</p>
      <p class="meta dim" style="font-size:30px;margin-top:44px">Narration is AI-generated; the footage is the live app, recorded as it ran.<br>Only the agent's waiting time was shortened.</p></div></div>"""
    return s


def render() -> list[Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    paths = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        pg = b.new_page(viewport={"width": 1920, "height": 1080})
        for name, html in slides(numbers()).items():
            pg.set_content(f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{html}</body></html>")
            path = OUT / f"slide_{name}.png"
            pg.screenshot(path=str(path))
            paths.append(path)
        b.close()
    return paths


if __name__ == "__main__":
    for path in render():
        print(path)
