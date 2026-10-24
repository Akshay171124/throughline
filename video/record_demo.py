"""Record a real, scripted run of the live Throughline app (http://localhost:8000).

Writes video/out/raw/*.webm and video/out/timeline.json (seconds since recording start).
Each beat is held at least as long as its narration (video/out/audio/durations.json).
Usage: uv run python video/record_demo.py [--no-agent]
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000"
HERE = Path(__file__).parent
OUT = HERE / "out"
RAW = OUT / "raw"
NO_AGENT = "--no-agent" in sys.argv
GOAL = "I'm new to MCP and want to build my first server"
TARGET = "BLD1428W"

BEATS = {b["id"]: b for b in json.loads((HERE / "narration.json").read_text())}
try:
    DURS = json.loads((OUT / "audio" / "durations.json").read_text())
except FileNotFoundError:
    DURS = {}

OVERLAY_JS = r"""
(() => {
  if (window.__ovl) return;
  const css = `
  
  #__cur { position: fixed; inset: auto; right: auto; bottom: auto; left: 0; top: 0; margin: 0;
    width: 30px; height: 30px; border-radius: 50%; padding: 0; overflow: visible;
    background: rgba(255, 196, 0, .55); border: 3px solid rgba(20, 20, 20, .85);
    box-shadow: 0 0 0 3px rgba(255,255,255,.85), 0 2px 10px rgba(0,0,0,.35);
    pointer-events: none; z-index: 2147483647; transform: translate(-50%, -50%);
    transition: left .7s cubic-bezier(.4,0,.2,1), top .7s cubic-bezier(.4,0,.2,1); display: block; }
  #__cur.pulse::after { content: ""; position: absolute; left: 50%; top: 50%; width: 30px; height: 30px;
    margin: -18px 0 0 -18px; border-radius: 50%; border: 3px solid rgba(255,170,0,.95);
    animation: __pulse .6s ease-out forwards; }
  @keyframes __pulse { from { transform: scale(1); opacity: 1; } to { transform: scale(2.6); opacity: 0; } }
  #__cap { position: fixed; inset: auto; left: 50%; bottom: 22px; top: auto; right: auto; margin: 0;
    transform: translateX(-50%); max-width: 1560px; width: max-content; padding: 14px 32px; border-radius: 16px;
    background: rgba(12, 18, 34, .9); color: #fff; border: 0; overflow: visible;
    font: 600 31px/1.25 -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; letter-spacing: .1px;
    text-align: center; box-shadow: 0 6px 24px rgba(0,0,0,.35); pointer-events: none;
    z-index: 2147483646; transition: opacity .35s; display: block; white-space: normal; }
  #__cap.off { opacity: 0; }
  `;
  function mk() {
    const st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);
    const cur = document.createElement("div"); cur.id = "__cur"; cur.setAttribute("popover", "manual");
    const cap = document.createElement("div"); cap.id = "__cap"; cap.setAttribute("popover", "manual"); cap.className = "off";
    document.body.append(cap, cur);
    let pos = { x: 960, y: 600 };
    try { pos = JSON.parse(sessionStorage.getItem("__curpos")) || pos; } catch {}
    cur.style.transition = "none"; cur.style.left = pos.x + "px"; cur.style.top = pos.y + "px";
    requestAnimationFrame(() => { cur.style.transition = ""; });
    const raise = () => {
      for (const el of [cap, cur]) {
        try { if (el.matches(":popover-open")) el.hidePopover(); el.showPopover(); } catch {}
      }
    };
    raise();
    window.__ovl = {
      raise,
      move(x, y, ms) {
        cur.style.transitionDuration = (ms / 1000) + "s";
        cur.style.left = x + "px"; cur.style.top = y + "px";
        try { sessionStorage.setItem("__curpos", JSON.stringify({ x, y })); } catch {}
      },
      pulse() { cur.classList.remove("pulse"); void cur.offsetWidth; cur.classList.add("pulse"); },
      caption(text) {
        if (!text) { cap.classList.add("off"); return; }
        cap.textContent = text; cap.classList.remove("off"); raise();
      },
    };
    // Keep the overlay above modal dialogs (they live in the top layer).
    new MutationObserver(() => raise()).observe(document.body, { subtree: true, attributes: true, attributeFilter: ["open"] });
    const lastCap = sessionStorage.getItem("__cap");
    if (lastCap) window.__ovl.caption(lastCap);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mk); else mk();
})();
"""


class Rec:
    def __init__(self, page):
        self.page = page
        self.t0 = time.monotonic()
        self.events = []
        self.beat_started = None
        self.beat_id = None

    def now(self):
        return round(time.monotonic() - self.t0, 3)

    def mark(self, kind, **kw):
        self.events.append({"t": self.now(), "kind": kind, **kw})
        print(f"[{self.now():7.2f}] {kind} {kw}", flush=True)

    def caption(self, text):
        self.page.evaluate("(t) => { try { sessionStorage.setItem('__cap', t || ''); } catch {} ; window.__ovl && window.__ovl.caption(t); }", text)

    def beat(self, beat_id):
        """Finish the previous beat (hold for its narration), then start this one."""
        self.hold_rest()
        self.beat_id = beat_id
        self.beat_started = time.monotonic()
        self.mark("beat", id=beat_id)
        self.caption(BEATS[beat_id]["caption"] if beat_id in BEATS else "")

    def hold_rest(self, extra=0.9):
        if not self.beat_id:
            return
        need = DURS.get(self.beat_id, 0) + 0.3 + extra
        spent = time.monotonic() - self.beat_started - self.excluded
        if need > spent:
            self.page.wait_for_timeout(int((need - spent) * 1000))
        self.excluded = 0.0

    excluded = 0.0  # seconds of the current beat that the edit cuts (agent wait)

    def pause(self, s):
        self.page.wait_for_timeout(int(s * 1000))

    # ---- cursor -------------------------------------------------------------
    def move_to(self, x, y, ms=700):
        self.page.evaluate("([x, y, ms]) => window.__ovl && window.__ovl.move(x, y, ms)", [x, y, ms])
        self.page.mouse.move(x, y, steps=8)
        self.page.wait_for_timeout(ms + 80)

    def box_center(self, locator):
        locator.scroll_into_view_if_needed()
        b = locator.bounding_box()
        return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2

    def click(self, locator, pause_after=0.5):
        locator.wait_for(state="visible")
        x, y = self.box_center(locator)
        self.move_to(x, y)
        self.page.evaluate("() => window.__ovl && window.__ovl.pulse()")
        self.page.mouse.click(x, y)
        self.pause(pause_after)

    def click_xy(self, x, y, pause_after=0.5):
        self.move_to(x, y)
        self.page.evaluate("() => window.__ovl && window.__ovl.pulse()")
        self.page.mouse.click(x, y)
        self.pause(pause_after)

    def hover(self, locator, pause_after=0.8):
        x, y = self.box_center(locator)
        self.move_to(x, y)
        self.pause(pause_after)

    def type_into(self, locator, text, delay=45):
        self.click(locator, pause_after=0.2)
        self.page.keyboard.type(text, delay=delay)


def cy_node_xy(page, node_id):
    return page.evaluate(
        """(id) => {
            if (typeof cy === 'undefined' || !cy) return null;
            const n = cy.getElementById(id);
            if (!n || n.empty()) return null;
            const p = n.renderedPosition(); const r = cy.container().getBoundingClientRect();
            const x = r.left + p.x, y = r.top + p.y;
            if (x < r.left + 10 || x > r.right - 10 || y < r.top + 10 || y > r.bottom - 10) return null;
            return { x, y };
        }""", node_id)


def best_chain_node(page):
    return page.evaluate(
        """() => {
            const r = cy.container().getBoundingClientRect();
            let best = null, score = -1;
            cy.nodes('.talk').forEach((n) => {
                const p = n.renderedPosition(); const x = r.left + p.x, y = r.top + p.y;
                if (x < r.left + 120 || x > r.right - 340 || y < r.top + 60 || y > r.bottom - 60) return;
                const s = n.predecessors().nodes().length + n.successors().nodes().length;
                if (s > score) { score = s; best = { id: n.id(), x, y, s }; }
            });
            return best;
        }""")


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    for old in RAW.glob("*.webm"):
        old.unlink()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(
            viewport={"width": 1920, "height": 1080}, device_scale_factor=1,
            record_video_dir=str(RAW), record_video_size={"width": 1920, "height": 1080},
        )
        ctx.add_init_script(OVERLAY_JS)
        page = ctx.new_page()
        page.set_default_timeout(30000)
        r = Rec(page)
        code = None
        try:
            run(page, r)
        except Exception as e:  # keep the timeline so a failure can be inspected
            r.mark("error", message=str(e)[:300])
            page.screenshot(path=str(OUT / "error.png"))
            raise
        finally:
            try:
                code = page.evaluate("() => localStorage.getItem('throughline.attendee')")
            except Exception:
                pass
            r.mark("end")
            (OUT / "timeline.json").write_text(json.dumps({"events": r.events, "no_agent": NO_AGENT}, indent=2))
            video = page.video
            ctx.close()
            browser.close()
            if video:
                print("raw video:", video.path())
            if code:
                req = urllib.request.Request(f"{BASE}/api/attendees/{code}", method="DELETE")
                try:
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        print("deleted attendee", code, resp.status)
                except Exception as e:
                    print("could not delete attendee", code, e)


def run(page, r: Rec):
    page.goto(BASE + "/")
    page.locator("#pk-ready .pk-card.ready").first.wait_for()
    page.locator("#status").wait_for(state="attached")

    # 1 - the problem
    r.beat("01_problem")
    r.pause(1.0)
    r.hover(page.locator("#pk-title"), pause_after=1.0)
    r.hover(page.locator("#pk-place"), pause_after=0.5)

    # 2 - find the conference
    r.beat("02_find")
    r.type_into(page.locator("#pk-place"), "San Francisco, CA", delay=60)
    r.pause(0.3)
    r.click(page.locator("#pk-form button[type=submit]"))
    page.locator("#pk-results .pk-card").first.wait_for(timeout=60000)
    r.pause(0.8)
    near = page.locator("#pk-near")
    near.scroll_into_view_if_needed()
    first_near = page.locator("#pk-results .pk-card").first
    r.hover(first_near, pause_after=1.2)
    r.hover(page.locator("#pk-results .pk-card .pill.plain").first, pause_after=1.2)
    ready_card = page.locator("#pk-ready .pk-card.ready", has_text="Universe").first
    r.hover(ready_card, pause_after=1.0)

    # 3 - the map
    r.beat("03_map")
    r.click(ready_card.locator("button.primary"), pause_after=0.5)
    page.locator("#mapview").wait_for(state="visible")
    page.wait_for_function("() => typeof cy !== 'undefined' && cy && cy.nodes('.talk').length > 5", timeout=30000)
    page.locator("#flow-state").wait_for(state="hidden", timeout=30000) if page.locator("#flow-state").is_visible() else None
    r.pause(1.5)
    node = best_chain_node(page)
    r.mark("hover_node", node=node)
    if node:
        r.move_to(node["x"], node["y"], ms=900)
        page.locator("#flow-card").wait_for(state="visible", timeout=5000)
        r.pause(3.5)
    r.move_to(1500, 160, ms=600)  # off the canvas nodes to clear the highlight
    page.mouse.move(1500, 130)

    # 4 - ask the graph (live agent)
    r.beat("04_ask")
    box = page.locator("#chat-input")
    r.type_into(box, GOAL, delay=38)
    r.pause(0.5)
    if NO_AGENT:
        r.mark("agent_skipped")
        page.fill("#chat-input", "")
    else:
        attempts = 0
        while True:
            attempts += 1
            r.click(page.locator("#chat-send"), pause_after=0.1)
            r.mark("agent_wait_start", attempt=attempts)
            w0 = time.monotonic()
            page.locator("#chat-log .msg.pending").wait_for(state="attached", timeout=5000)
            page.wait_for_function("() => !document.querySelector('#chat-log .msg.pending')", timeout=120000, polling=200)
            r.mark("agent_wait_end", attempt=attempts)
            r.excluded += time.monotonic() - w0
            err = page.locator("#chat-log .msg.agent.error")
            if err.count() and attempts < 2:
                r.mark("agent_error_retry", text=err.last.inner_text()[:200])
                continue
            break
        r.pause(0.6)

    # 5 - the answer
    r.beat("05_answer")
    if not NO_AGENT:
        last = page.locator("#chat-log .msg.agent").last
        r.pause(1.0)
        cards = last.locator(".sugg, .card, article, li")
        if cards.count():
            r.hover(cards.first, pause_after=1.2)
        # point at a highlighted talk on the map
        hl = page.evaluate("() => (typeof activeHighlight !== 'undefined' && activeHighlight) || []")
        for c in (hl or [])[:2]:
            xy = cy_node_xy(page, c)
            if xy:
                r.move_to(xy["x"], xy["y"], ms=800)
                r.pause(1.6)
        how = last.locator("details.how > summary")
        if how.count():
            r.click(how.first, pause_after=1.8)
            tech = last.locator("details.why-tech > summary")
            if tech.count():
                r.click(tech.first, pause_after=2.2)

    # 6 - the talk page
    r.beat("06_talk")
    xy = cy_node_xy(page, TARGET)
    r.mark("target_on_map", xy=xy)
    if xy:
        r.click_xy(xy["x"], xy["y"], pause_after=0.2)
        page.wait_for_url("**/talk.html**", timeout=15000)
    else:
        page.goto(f"{BASE}/talk.html?code={TARGET}")
    page.locator("#ready-head .head-title").wait_for(timeout=30000)
    page.wait_for_function("() => !document.getElementById('graph-wrap').classList.contains('loading')", timeout=30000)
    r.pause(0.8)
    skip = page.locator("[data-prompt=skip]")
    if skip.count() and skip.first.is_visible():
        r.click(skip.first, pause_after=0.4)
    exp = page.evaluate(
        "async () => { const c = localStorage.getItem('throughline.attendee'); const s = await (await fetch('/api/attendees/' + encodeURIComponent(c))).json(); return (s.profile || {}).experience || ''; }")
    r.mark("profile_experience", experience=exp)
    page.locator("#about:not([hidden])").wait_for(timeout=30000)
    toggle = page.locator("#about-toggle")
    if toggle.get_attribute("aria-expanded") != "true":
        r.click(toggle, pause_after=0.6)
    page.locator("#about-body .about-summary").wait_for(timeout=30000)
    r.hover(page.locator("#about-body .about-summary"), pause_after=2.0)
    if page.locator("#about-body .about-concepts").count():
        r.hover(page.locator("#about-body .about-concepts"), pause_after=1.5)
    if page.locator("#about-body .readings li").count():
        r.hover(page.locator("#about-body .readings li").first, pause_after=1.5)

    # make sure we're planning as a newcomer: if the agent set "some"/"experienced", set "new" visibly
    if exp not in ("", "new"):
        set_experience(page, r, "new")

    # 7 - the path for a newcomer
    r.beat("07_path")
    if toggle.get_attribute("aria-expanded") == "true":
        r.click(toggle, pause_after=0.8)  # collapse About so the path has room
    page.locator("#graph:not([hidden])").wait_for(timeout=15000)
    steps = page.evaluate("() => view.plan ? view.plan.plan.length : null")
    r.mark("path_steps", steps=steps)
    r.hover(page.locator("#ready-head .progress"), pause_after=1.2)
    for cid in page.evaluate("() => view.plan.plan.map((s) => 'concept:' + s.concept)")[:4]:
        xy = cy_node_xy(page, cid)
        if xy:
            r.move_to(xy["x"], xy["y"], ms=650)
            r.pause(1.0)
    dp = page.locator("#dayplan .timeline")
    if dp.count():
        dp.scroll_into_view_if_needed()
        for row in dp.locator("li.row").all()[:4]:
            r.hover(row, pause_after=0.9)

    # 8 - profile: some experience
    r.beat("08_profile")
    set_experience(page, r, "some")
    steps = page.evaluate("() => view.plan ? view.plan.plan.length : null")
    r.mark("path_steps_after_profile", steps=steps)
    page.locator("#ready-head").scroll_into_view_if_needed()
    r.hover(page.locator("#ready-head .progress, #ready-head .ready-banner").first, pause_after=1.0)
    if page.locator("#ready-head .profile-skip").count():
        r.hover(page.locator("#ready-head .profile-skip"), pause_after=1.0)

    # 9 - evidence for the remaining concept
    r.beat("09_evidence")
    remaining = page.evaluate("() => view.plan.plan.map((s) => s.concept)")
    teach = page.evaluate("() => { const s = view.plan.plan[0]; return s && s.learn_at && s.learn_at.kind === 'talk' ? s.learn_at.code : null; }")
    r.mark("remaining", concepts=remaining, teaching_talk=teach)
    page.locator("#graph-wrap").scroll_into_view_if_needed()
    page.wait_for_timeout(700)  # graph glides to its new layout
    xy = cy_node_xy(page, f"concept:{remaining[0]}") if remaining else None
    if xy:
        r.click_xy(xy["x"], xy["y"], pause_after=0.6)
        dlg = page.locator("dialog#detail")
        dlg.wait_for(state="visible")
        ev = dlg.locator("ul.evidence q")
        if ev.count():
            r.hover(ev.first, pause_after=2.0)
        if ev.count() > 1:
            r.hover(ev.nth(1), pause_after=2.0)
        r.pause(1.0)
        r.click(dlg.locator("button.close"), pause_after=0.5)

    # 10 - I attended this
    r.beat("10_attend")
    clock_before = page.locator("#clock").inner_text()
    r.hover(page.locator("#clock"), pause_after=1.0)
    row = page.locator(f"#dayplan button.row-title[data-code='{teach}']")
    r.click(row, pause_after=0.6)
    dlg = page.locator("dialog#detail")
    att = dlg.locator("button[data-act=attended]")
    att.wait_for(timeout=15000)
    r.pause(1.2)
    r.click(att, pause_after=0.3)
    page.locator("#ready-head .ready-banner").wait_for(timeout=30000)
    page.wait_for_function("(b) => document.getElementById('clock').textContent !== b", arg=clock_before, timeout=15000)
    r.mark("clock", before=clock_before, after=page.locator("#clock").inner_text())
    r.pause(0.5)
    r.hover(page.locator("#clock"), pause_after=1.5)
    r.hover(page.locator("#ready-head .ready-banner"), pause_after=2.0)

    # 11 - how it's built (back to the map)
    r.beat("11_built")
    r.click(page.locator("a.back-link"), pause_after=0.2)
    page.locator("#mapview").wait_for(state="visible", timeout=30000)
    page.wait_for_function("() => typeof cy !== 'undefined' && cy && cy.nodes('.talk').length > 5", timeout=30000)
    r.pause(2.0)
    r.hover(page.locator("#status"), pause_after=2.0)
    node = best_chain_node(page)
    if node:
        r.move_to(node["x"], node["y"], ms=1200)
        r.pause(5.0)
        r.move_to(1500, 130, ms=800)

    # 12 - close
    r.beat("12_close")
    r.pause(1.0)
    r.hold_rest(extra=1.5)
    r.beat_id = None


def set_experience(page, r: Rec, value):
    r.click(page.locator("#profile-btn"), pause_after=0.6)
    dlg = page.locator("dialog#profile")
    dlg.wait_for(state="visible")
    seg = dlg.locator(f"label.seg:has(input[value='{value}'])")
    r.click(seg, pause_after=0.6)
    r.click(dlg.locator("button[type=submit]"), pause_after=0.2)
    dlg.locator("#pf-status", has_text="Saved").wait_for(timeout=15000)
    r.pause(0.8)
    r.click(dlg.locator("button.close"), pause_after=0.4)
    # Saving doesn't re-plan by itself: re-plan with the graph (no AI) from the talk's dialog.
    before = page.evaluate("() => view.plan ? view.plan.plan.length : null")
    r.click(page.locator("#ready-head .head-title"), pause_after=0.4)
    d = page.locator("dialog#detail")
    plan_btn = d.locator("button[data-act=plan]")
    plan_btn.wait_for(timeout=15000)
    r.pause(0.6)
    r.click(plan_btn, pause_after=0.3)
    page.wait_for_function("(b) => view.plan && view.plan.plan.length !== b", arg=before, timeout=15000)
    page.wait_for_function("() => !document.getElementById('graph-wrap').classList.contains('loading')", timeout=15000)
    r.pause(1.2)


if __name__ == "__main__":
    main()
