const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const CODE_KEY = "throughline.attendee";
const TALK_KEY = "throughline.talk";
const AUTO_ALTS_MAX_NODES = 12; // show faded alternatives by default only on small graphs

let allTalks = [];
let attendee = null;
let history = []; // earlier user/assistant text for the agent

// What the right-hand panel is showing.
const view = {
  talk: null,       // target talk code
  plan: null,       // GET /api/plan result
  graph: null,      // GET /api/graph result
  showAlts: null,   // null = automatic
  wasReady: null,
  version: 0,       // drops stale responses
  known: [],        // attendee's known concepts
  attended: [],     // attended talk titles
  rankDir: "LR",    // graph direction chosen for this talk
};
let cy = null;      // the Cytoscape instance, when the library loaded
let graphTurn = 0;  // cancels a pending fade when a newer redraw starts
let dialogCtx = null;

// ---- helpers ---------------------------------------------------------------

// Feed data and model output are untrusted: escape everything, including quotes for attributes.
function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function safeUrl(url) {
  return /^https:\/\//.test(url || "") ? escapeHtml(url) : "#";
}

function formatTime(hhmm) {
  if (!hhmm || !/^\d{1,2}:\d{2}/.test(hhmm)) return "";
  const [h, m] = hhmm.split(":").map(Number);
  return `${((h + 11) % 12) + 1}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
}

// "2026-10-28T08:30" is conference wall-clock time; format it without timezone shifts.
function formatClock(iso) {
  const [date, time] = iso.split("T");
  const [y, mo, d] = date.split("-").map(Number);
  const weekday = DAYS[new Date(Date.UTC(y, mo - 1, d)).getUTCDay()];
  return `${weekday} ${MONTHS[mo - 1]} ${d} · ${formatTime(time)}`;
}

function dayShort(day) {
  return String(day || "").slice(0, 3);
}

function levelBadge(levelNum) {
  const n = Number(levelNum);
  return [100, 200, 300].includes(n) ? `<span class="level l${n}">${n}</span>` : "";
}

// Minimal formatting for agent replies: escape, then **bold** and line breaks.
function formatReply(text) {
  return escapeHtml(text).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/\n/g, "<br>");
}

// Long catalog titles: keep the part before the colon when it stands on its own, then cap.
function shortTitle(title, max = 54) {
  let t = String(title || "").replace(/\s*\(Sponsored\)\s*$/i, "");
  const colon = t.indexOf(": ");
  if (colon >= 14) t = t.slice(0, colon);
  return t.length > max ? `${t.slice(0, max - 1).trimEnd()}…` : t;
}

function storageGet(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
function storageSet(key, value) {
  try { value === null ? localStorage.removeItem(key) : localStorage.setItem(key, value); } catch { /* private mode */ }
}

async function api(path, options = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.json();
}

function findTalk(code) {
  return allTalks.find((t) => t.code === code);
}

function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

// ---- attendee memory -------------------------------------------------------

async function refreshAttendee() {
  const state = await api(`/api/attendees/${encodeURIComponent(attendee)}`);
  document.getElementById("attendee-code").textContent = attendee;
  const clock = document.getElementById("clock");
  const next = state.clock ? state.clock.replace(",", " ·") : "--";
  if (clock.textContent !== next) {
    clock.textContent = next;
    clock.classList.remove("tick");
    void clock.offsetWidth; // restart the highlight animation
    clock.classList.add("tick");
  }
  view.known = state.known || [];
  view.attended = state.attended || [];
  return state;
}

async function startAttendee() {
  const saved = storageGet(CODE_KEY);
  if (saved) {
    try {
      attendee = saved;
      await refreshAttendee();
      return;
    } catch { /* code expired or deleted: make a new one */ }
  }
  attendee = (await api("/api/attendees", { method: "POST" })).code;
  storageSet(CODE_KEY, attendee);
  await refreshAttendee();
}

// After anything that changes what the attendee knows: clock, schedule marks, plan, graph.
async function refreshAll() {
  await refreshAttendee();
  if (view.talk) await loadTalkView(view.talk);
  else renderTalks(currentTalkList());
}

// ---- schedule --------------------------------------------------------------

function planTalkCodes() {
  const codes = new Set();
  for (const s of (view.plan && view.plan.plan) || []) {
    if (s.learn_at && s.learn_at.kind === "talk") codes.add(s.learn_at.code);
  }
  return codes;
}

function renderTalks(talks) {
  const inPlan = planTalkCodes();
  const attended = new Set(view.attended);
  let html = "";
  let currentDay = null;
  for (const t of talks) {
    if (t.day !== currentDay) {
      currentDay = t.day;
      html += `<h2 class="day">${escapeHtml(t.day)}</h2>`;
    }
    const classes = ["talk"];
    let badge = "";
    if (t.code === view.talk) { classes.push("is-target"); badge = `<span class="badge target">Your talk</span>`; }
    else if (inPlan.has(t.code)) { classes.push("in-plan"); badge = `<span class="badge plan">In your plan</span>`; }
    if (attended.has(t.title)) { classes.push("attended"); badge += `<span class="badge done">✓ Attended</span>`; }
    html += `
      <div class="${classes.join(" ")}" data-code="${escapeHtml(t.code)}" tabindex="0" role="button" aria-label="Talk details">
        <span class="when">${formatTime(t.start)}</span>
        <span class="what">
          <span class="title">${escapeHtml(t.title)}</span>
          <span class="meta">${levelBadge(t.level_num)}${escapeHtml(t.type)} · ${escapeHtml(t.room)} ${badge}</span>
          <span class="actions">
            <button class="chip" data-action="ask">Get me ready</button>
            <button class="chip ghost" data-action="plan" title="Same graph queries, no AI">Plan without AI</button>
            <button class="chip ghost" data-action="attended">I attended this</button>
          </span>
        </span>
      </div>`;
  }
  const box = document.getElementById("talks");
  const scroll = box.scrollTop;
  box.innerHTML = html || `<p class="muted pad">No talks match.</p>`;
  box.scrollTop = scroll;
}

function filterTalks(query) {
  const q = query.trim().toLowerCase();
  if (!q) return allTalks;
  return allTalks.filter((t) =>
    [t.title, t.code, t.room, t.type, ...(t.speakers || []), ...(t.topics || [])].join(" ").toLowerCase().includes(q)
  );
}

function currentTalkList() {
  return filterTalks(document.getElementById("search").value);
}

// ---- chat and trace --------------------------------------------------------

function addMessage(role, html) {
  const box = document.getElementById("messages");
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.innerHTML = html;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
  return div;
}

function renderTrace(trace) {
  const list = document.getElementById("trace");
  const count = document.getElementById("how-count");
  if (!trace.length) {
    list.innerHTML = `<p class="muted pad">No tools were called for this answer.</p>`;
    count.textContent = "";
    return;
  }
  const queries = trace.reduce((n, s) => n + (s.cypher || []).length, 0);
  openHow();
  count.textContent = `${plural(trace.length, "tool call", "tool calls")} · ${plural(queries, "Cypher query", "Cypher queries")}`;
  list.innerHTML = trace.map((step, i) => `
    <details class="step" ${i === trace.length - 1 ? "open" : ""}>
      <summary><span class="step-n">${i + 1}</span> <code>${escapeHtml(step.tool)}</code>
        <span class="muted">${escapeHtml(JSON.stringify(step.args))}</span></summary>
      ${(step.cypher || []).map((c) => `<pre class="cypher">${escapeHtml(c)}</pre>`).join("")}
      <pre class="result">${escapeHtml(JSON.stringify(step.result, null, 2).slice(0, 4000))}</pre>
    </details>`).join("");
}

function setBusy(busy) {
  const input = document.getElementById("input");
  const send = document.querySelector("#composer button");
  input.disabled = busy;
  send.disabled = busy;
  send.textContent = busy ? "Thinking…" : "Send";
  if (!busy) input.focus();
}

let asking = false;
async function ask(message) {
  if (asking) return;
  asking = true;
  setBusy(true);
  addMessage("user", `<p>${escapeHtml(message)}</p>`);
  const pending = addMessage("agent pending", `<p>Walking the graph<span class="dots"><span>.</span><span>.</span><span>.</span></span></p>`);
  try {
    const turn = await api("/api/agent", {
      method: "POST",
      body: JSON.stringify({ attendee, message, history }),
    });
    pending.classList.remove("pending");
    pending.innerHTML = `<p>${formatReply(turn.reply || "")}</p>`;
    history.push({ role: "user", content: message }, { role: "assistant", content: turn.reply || "" });
    renderTrace(turn.trace || []);
    await refreshAttendee();
    const target = turn.view && turn.view.talk;
    if (target) await loadTalkView(target);
    else if (view.talk) await loadTalkView(view.talk);
  } catch (err) {
    pending.classList.remove("pending");
    pending.innerHTML = `<p class="error">The agent failed: ${escapeHtml(err.message)}. Use “Plan without AI” on the talk instead.</p>`;
  } finally {
    asking = false;
    setBusy(false);
  }
}

function openHow() {
  const how = document.getElementById("how");
  if (how) how.open = true;
}

// The model-free fallback: the same graph queries, rendered directly.
async function planWithoutAI(code) {
  const talk = findTalk(code);
  try {
    const plan = await loadTalkView(code, { trace: true });
    if (!plan) return;
    const steps = plan.plan.length;
    addMessage("agent card", plan.ready
      ? `<p><strong>You're ready</strong> for ${escapeHtml(plan.talk_title)}. Nothing on its path is missing.</p><p class="muted">Model-free plan from the graph.</p>`
      : `<p>Your path to <strong>${escapeHtml(plan.talk_title)}</strong> has ${plural(steps, "step", "steps")}. The graph and your day are on the right.</p><p class="muted">Model-free plan from the graph.</p>`);
  } catch (err) {
    addMessage("agent card", `<p class="error">Couldn't plan ${escapeHtml(talk ? talk.title : code)}: ${escapeHtml(err.message)}</p>`);
  }
}

async function attendedTalk(code) {
  try {
    const result = await api(`/api/attendees/${encodeURIComponent(attendee)}/attended`, {
      method: "POST", body: JSON.stringify({ talk: code }),
    });
    const talk = findTalk(code);
    await refreshAll();
    const learned = (result.learned || []).map((id) => {
      const k = view.known.find((x) => x.concept === id);
      return k && k.name ? k.name : id;
    });
    addMessage("agent card", `<p>Marked <strong>${escapeHtml(talk ? talk.title : code)}</strong> as attended. Learned: ${
      learned.length ? learned.map(escapeHtml).join(", ") : "nothing new"}. Clock moved to ${escapeHtml(result.clock)}.</p>`);
  } catch (err) {
    addMessage("agent card", `<p class="error">Couldn't record that: ${escapeHtml(err.message)}</p>`);
  }
}

async function markKnown(concept, name) {
  try {
    await api(`/api/attendees/${encodeURIComponent(attendee)}/known`, {
      method: "POST", body: JSON.stringify({ concept }),
    });
    addMessage("agent card", `<p>Noted: you already know <strong>${escapeHtml(name || concept)}</strong>. I took it off your path.</p>`);
    await refreshAll();
  } catch (err) {
    addMessage("agent card", `<p class="error">Couldn't save that: ${escapeHtml(err.message)}</p>`);
  }
}

// ---- the readiness panel ----------------------------------------------------

async function loadTalkView(code, { trace = false } = {}) {
  const version = ++view.version;
  const sameTalk = view.talk === code;
  const wrap = document.getElementById("graph-wrap");
  if (!sameTalk) wrap.classList.add("loading");
  try {
    const q = `?attendee=${encodeURIComponent(attendee)}`;
    const [plan, graph] = await Promise.all([
      api(`/api/plan/${encodeURIComponent(code)}${q}`),
      api(`/api/graph/${encodeURIComponent(code)}${q}`),
    ]);
    if (version !== view.version) return null; // a newer request won
    if (!sameTalk) { view.showAlts = null; view.wasReady = null; }
    view.talk = code;
    view.plan = plan;
    view.graph = graph;
    storageSet(TALK_KEY, code);
    renderHead(sameTalk);
    renderGraph(sameTalk);
    renderDayPlan();
    renderTalks(currentTalkList());
    if (trace) {
      renderTrace([{ tool: "plan_day (no AI)", args: { talk: code }, cypher: plan.queries || [], result: { steps: plan.plan.length, ready: plan.ready } }]);
    }
    view.wasReady = plan.ready;
    return plan;
  } finally {
    if (version === view.version) wrap.classList.remove("loading");
  }
}

function knownHow(how) {
  return how === "attended" ? "learned at a talk you attended" : "you told me you know it";
}

function conceptName(id) {
  const n = view.graph && view.graph.nodes.find((x) => x.id === `concept:${id}`);
  if (n) return n.label;
  const k = view.known.find((x) => x.concept === id);
  return k ? k.name : id;
}

function renderHead(sameTalk) {
  const head = document.getElementById("ready-head");
  const plan = view.plan;
  if (!plan) {
    head.innerHTML = `<div class="empty-head"><h2>Your path</h2><p class="muted">Pick a talk on the left, or ask in the chat. I'll draw what it assumes, where to learn each piece, and in what order.</p></div>`;
    return;
  }
  const t = findTalk(plan.talk);
  const when = t ? `${escapeHtml(t.day)} ${formatTime(t.start)} · ${escapeHtml(t.room)}` : "";
  const learned = (plan.already_known || []).length;
  const total = learned + plan.plan.length;
  const pct = total ? Math.round((learned / total) * 100) : 100;
  let status;
  if (plan.ready) {
    const known = (plan.already_known || []).map((k) => `<li><span class="tick-mark">✓</span> ${escapeHtml(conceptName(k.concept))} <span class="muted">(${knownHow(k.how)})</span></li>`).join("");
    const celebrate = sameTalk && view.wasReady === false ? " celebrate" : "";
    status = `<div class="ready-banner${celebrate}">
        <span class="big-check" aria-hidden="true">✓</span>
        <div><strong>You're ready.</strong>
          <div>${known ? "Everything this talk assumes is covered:" : "This talk doesn't assume anything you'd need to learn first."}</div>
          ${known ? `<ul class="known-list">${known}</ul>` : ""}
        </div>
      </div>`;
  } else {
    status = `<div class="progress" aria-label="Progress">
        <div class="bar"><span style="width:${pct}%"></span></div>
        <span class="progress-text"><strong>${learned} of ${total}</strong> ${total === 1 ? "step" : "steps"} learned · ${plural(plan.plan.length, "to go", "to go")}</span>
      </div>`;
  }
  head.innerHTML = `
    <span class="label">Your path to</span>
    <button class="head-title" data-open-talk="1">${escapeHtml(plan.talk_title)}</button>
    <div class="muted">${when}</div>
    ${status}`;
}

// ---- the graph ---------------------------------------------------------------

function cssVar(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

function graphStyle() {
  const c = {
    ink: cssVar("--ink", "#1d1d1b"), muted: cssVar("--muted", "#6b6a65"), line: cssVar("--edge", "#c9c6bc"),
    panel: cssVar("--panel", "#ffffff"), accent: cssVar("--accent", "#2f5bd3"), accentSoft: cssVar("--accent-soft", "#e8eefc"),
    ok: cssVar("--ok", "#2e7d4f"), okSoft: cssVar("--ok-soft", "#e6f4ec"), onAccent: cssVar("--on-accent", "#ffffff"),
  };
  const font = '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
  return [
    { selector: "node", style: {
      shape: "round-rectangle", width: 190, height: 60, label: "data(label)",
      "text-wrap": "wrap", "text-max-width": 174, "text-valign": "center", "text-halign": "center",
      "font-family": font, "font-size": 12, color: c.ink, "line-height": 1.25,
      "background-color": c.panel, "border-width": 1.5, "border-color": c.line,
      "transition-property": "opacity, background-color, border-color, border-width", "transition-duration": "400ms",
    } },
    { selector: "node.talk.chosen, node.explainer.chosen", style: { "border-color": c.accent, "border-width": 2 } },
    { selector: "node.explainer", style: { "border-style": "dashed" } },
    { selector: "node.target", style: {
      width: 200, height: 72, "background-color": c.accent, "border-color": c.accent,
      color: c.onAccent, "font-weight": 700, "font-size": 13,
    } },
    { selector: "node.concept", style: {
      width: 172, height: 48, "background-color": c.accentSoft, "border-color": c.accent, "border-width": 2,
      "font-weight": 600, "font-size": 13, "text-max-width": 158,
    } },
    { selector: "node.concept.known", style: { "background-color": c.okSoft, "border-color": c.ok, color: c.ok } },
    { selector: "node.alt", style: { opacity: 0.45 } },
    { selector: "node.hover", style: { "border-width": 3.5, "border-color": c.accent } },
    { selector: "edge", style: {
      width: 1.5, "line-color": c.line, "target-arrow-color": c.line, "target-arrow-shape": "triangle",
      "curve-style": "bezier", "arrow-scale": 1,
      "transition-property": "opacity, line-color, width", "transition-duration": "400ms",
    } },
    { selector: "edge.chosen", style: {
      width: 2.5, "line-color": c.accent, "target-arrow-color": c.accent,
      label: "data(label)", "font-family": font, "font-size": 10, color: c.muted,
      "text-background-color": c.panel, "text-background-opacity": 1, "text-background-padding": 2,
      "text-background-shape": "roundrectangle",
    } },
    { selector: "edge.alt", style: { opacity: 0.4, "line-style": "dashed" } },
    { selector: "edge.done", style: { "line-color": c.ok, "target-arrow-color": c.ok, width: 2 } },
    { selector: "edge.unsure", style: { "line-style": "dashed" } },
  ];
}

// Turn the API graph into drawable elements. Arrows point the way you learn:
// where to learn -> concept -> what it's needed for -> your talk.
function graphElements(graph, showAlts) {
  const steps = new Map(((view.plan && view.plan.plan) || []).map((s, i) => [s.concept, i + 1]));
  const chosenTeachers = new Set(graph.edges.filter((e) => (e.type === "TEACHES" || e.type === "EXPLAINS") && e.chosen).map((e) => e.source));
  const knownConcepts = new Set(graph.nodes.filter((n) => n.type === "concept" && n.data && n.data.known).map((n) => n.id));
  const kept = new Set();
  const els = [];
  for (const n of graph.nodes) {
    const d = n.data || {};
    const classes = [n.type];
    let label = n.label;
    if (n.type === "target") {
      label = `YOUR TALK · ${dayShort(d.day)} ${formatTime(d.start)}\n${shortTitle(n.label, 48)}`;
    } else if (n.type === "talk") {
      const chosen = chosenTeachers.has(n.id);
      if (!chosen && !showAlts) continue;
      classes.push(chosen ? "chosen" : "alt");
      label = `${dayShort(d.day)} ${formatTime(d.start)}${d.sponsor ? " · Sponsored" : ""}\n${shortTitle(n.label)}`;
    } else if (n.type === "explainer") {
      classes.push(chosenTeachers.has(n.id) ? "chosen" : "alt");
      label = `Read · outside explainer\n${shortTitle(n.label)}`;
    } else if (n.type === "concept") {
      if (d.known) { classes.push("known"); label = `✓ ${n.label}`; }
      else label = steps.has(d.concept) ? `${steps.get(d.concept)}. ${n.label}` : n.label;
    }
    kept.add(n.id);
    els.push({ group: "nodes", data: { id: n.id, label }, classes: classes.join(" ") });
  }
  const labels = { TEACHES: "teaches", EXPLAINS: "explains", REQUIRES: "assumed by", DEPENDS_ON: "needed for" };
  for (const e of graph.edges) {
    if (!kept.has(e.source) || !kept.has(e.target)) continue;
    // REQUIRES and DEPENDS_ON point from the needer to the prerequisite; flip them for reading order.
    const flip = e.type === "REQUIRES" || e.type === "DEPENDS_ON";
    const source = flip ? e.target : e.source;
    const target = flip ? e.source : e.target;
    const classes = [e.type.toLowerCase()];
    const conceptEnd = e.type === "REQUIRES" ? e.target : null;
    if (conceptEnd && knownConcepts.has(conceptEnd)) classes.push("done");
    else if (e.type === "DEPENDS_ON" && (knownConcepts.has(e.source) || knownConcepts.has(e.target))) classes.push("done");
    else classes.push(e.chosen ? "chosen" : "alt");
    if (e.status === "unsure") classes.push("unsure");
    els.push({
      group: "edges",
      data: { id: `${e.type}|${e.source}|${e.target}`, source, target, label: labels[e.type] || "" },
      classes: classes.join(" "),
    });
  }
  return els;
}

function graphAvailable() {
  return typeof window.cytoscape === "function" && typeof window.dagre === "object";
}

function layoutOptions(animate, rankDir = view.rankDir || "LR") {
  return {
    name: "dagre", rankDir, nodeSep: rankDir === "LR" ? 18 : 22, rankSep: rankDir === "LR" ? 70 : 46, edgeSep: 12,
    fit: false, animate, animationDuration: 450, animationEasing: "ease-in-out-cubic",
  };
}

const GRAPH_PAD = 18;
const GRAPH_MIN_H = 240;
const GRAPH_MAX_H = 520;

// How large the laid-out graph would be drawn in the panel (1 = full size).
function drawnZoom() {
  const bb = cy.elements().boundingBox();
  const width = document.getElementById("graph").clientWidth || 600;
  return Math.min(1.05, (width - 2 * GRAPH_PAD) / Math.max(bb.w, 1), (GRAPH_MAX_H - 2 * GRAPH_PAD) / Math.max(bb.h, 1));
}

// Left-to-right reads best, but deep chains get tiny; switch to top-down when that is clearly larger.
function layoutBest() {
  cy.layout(layoutOptions(false, "LR")).run();
  const lr = drawnZoom();
  view.rankDir = "LR";
  if (lr >= 0.85) return;
  cy.layout(layoutOptions(false, "TB")).run();
  if (drawnZoom() > lr + 0.05) { view.rankDir = "TB"; return; }
  cy.layout(layoutOptions(false, "LR")).run();
}

// Size the canvas so the graph reads at ~100% when it fits the width, then fit it.
function sizeAndFit(animate) {
  const box = document.getElementById("graph");
  const bb = cy.elements().boundingBox();
  const width = box.clientWidth || 600;
  const zoom = Math.min(1.05, (width - 2 * GRAPH_PAD) / Math.max(bb.w, 1));
  const want = Math.round(Math.min(GRAPH_MAX_H, Math.max(GRAPH_MIN_H, bb.h * zoom + 2 * GRAPH_PAD)));
  if (Math.abs(box.clientHeight - want) > 4) {
    box.style.height = `${want}px`;
    cy.resize();
  }
  if (animate) cy.animate({ fit: { eles: cy.elements(), padding: GRAPH_PAD } }, { duration: 300 });
  else cy.fit(cy.elements(), GRAPH_PAD);
}

function destroyGraph() {
  graphTurn++;
  if (cy) { try { cy.destroy(); } catch { /* ignore */ } }
  cy = null;
}

function createGraph(els) {
  destroyGraph();
  const box = document.getElementById("graph");
  cy = window.cytoscape({
    container: box, elements: els, style: graphStyle(), layout: { name: "preset" },
    minZoom: 0.3, maxZoom: 1.05, userZoomingEnabled: false, userPanningEnabled: false,
    boxSelectionEnabled: false, autoungrabify: true, autounselectify: true,
  });
  cy.on("tap", "node", (evt) => openNode(evt.target.id()));
  cy.on("tap", "edge", (evt) => {
    const e = evt.target;
    const concept = [e.source().id(), e.target().id()].find((id) => id.startsWith("concept:"));
    if (concept) openNode(concept);
  });
  cy.on("mouseover", "node", (evt) => { evt.target.addClass("hover"); box.style.cursor = "pointer"; });
  cy.on("mouseout", "node", (evt) => { evt.target.removeClass("hover"); box.style.cursor = ""; });
  layoutBest();
  sizeAndFit(false);
}

// Same talk, new state: fade out what left the path, restyle what changed, glide to the new layout.
function updateGraph(els) {
  const ids = new Set(els.map((e) => e.data.id));
  const leaving = cy.elements().filter((e) => !ids.has(e.id()));
  const myTurn = ++graphTurn;
  // Restyle what stays right away (e.g. a concept turning green), so the change reads first.
  const fresh = [];
  cy.batch(() => {
    for (const el of els) {
      const existing = cy.getElementById(el.data.id);
      if (existing && existing.length) {
        existing.data("label", el.data.label);
        existing.classes(el.classes);
      } else {
        fresh.push(el);
      }
    }
  });
  const apply = () => {
    if (!cy || myTurn !== graphTurn) return;
    cy.batch(() => {
      leaving.remove();
      for (const el of fresh) cy.add(el);
    });
    const layout = cy.layout(layoutOptions(true));
    layout.one("layoutstop", () => { if (cy) sizeAndFit(true); });
    layout.run();
  };
  if (leaving.length) {
    leaving.style("opacity", 0); // the style transition fades them out
    setTimeout(apply, 380);
  } else {
    apply();
  }
}

function renderGraph(sameTalk) {
  const box = document.getElementById("graph");
  const fallback = document.getElementById("path");
  const toggle = document.getElementById("toggle-alts");
  const graph = view.graph;
  const alternatives = graph.nodes.filter((n) => n.type === "talk" && !graph.edges.some((e) => e.source === n.id && e.chosen)).length;
  if (view.showAlts === null) view.showAlts = graph.nodes.length <= AUTO_ALTS_MAX_NODES;
  toggle.hidden = alternatives === 0;
  toggle.textContent = view.showAlts ? `Hide other options (${alternatives})` : `Show other options (${alternatives})`;
  document.getElementById("legend").hidden = graph.nodes.length <= 1;
  document.getElementById("legend-faded").hidden = alternatives === 0 || !view.showAlts;

  if (graph.nodes.length <= 1) {
    destroyGraph();
    box.hidden = true;
    fallback.innerHTML = `<div class="graph-empty"><span class="big-check small" aria-hidden="true">✓</span> This talk's abstract doesn't assume any concept from the graph, so there's nothing to learn first.</div>`;
    return;
  }
  if (!graphAvailable()) {
    destroyGraph();
    box.hidden = true;
    toggle.hidden = true;
    document.getElementById("legend").hidden = true;
    renderPath({ kind: "plan", ...view.plan });
    return;
  }
  fallback.innerHTML = "";
  box.hidden = false;
  try {
    const els = graphElements(graph, view.showAlts);
    if (cy && sameTalk) updateGraph(els);
    else createGraph(els);
  } catch (err) {
    console.error("graph drawing failed, showing the text path", err);
    destroyGraph();
    box.hidden = true;
    toggle.hidden = true;
    document.getElementById("legend").hidden = true;
    renderPath({ kind: "plan", ...view.plan });
  }
}

// Text fallback when the graph library can't load: your talk -> what it assumes (with the
// abstract quote) -> where to learn it (with that talk's quote).
function talkLabel(code) {
  const t = findTalk(code);
  return t ? `${dayShort(t.day)} ${formatTime(t.start)} · ${t.title}` : code;
}

function renderPath(plan) {
  const box = document.getElementById("path");
  if (!plan) { box.innerHTML = ""; return; }
  const steps = plan.plan || [];
  const target = talkLabel(plan.talk);
  const known = (plan.already_known || []).map((k) => conceptName(k.concept));
  if (plan.ready || !steps.length) {
    box.innerHTML = `<div class="node target"><span class="label">Your talk</span>${escapeHtml(target)}</div>
      <div class="node ready"><strong>You're ready.</strong> Nothing it assumes is missing${
        known.length ? ` (you already know ${known.map(escapeHtml).join(", ")})` : ""}.</div>`;
    return;
  }
  const neededFor = {};
  for (const s of steps) for (const d of s.depends_on || []) (neededFor[d.concept] ||= []).push({ name: s.name, via: d.via || [] });
  const cards = steps.map((s, i) => {
    const why = [];
    if (s.required_by_talk) {
      why.push(`Your talk assumes it: <q>${escapeHtml(s.required_by_talk.evidence)}</q>${
        s.required_by_talk.status === "unsure" ? ` <span class="unsure">unsure</span>` : ""}`);
    }
    for (const n of neededFor[s.concept] || []) {
      why.push(`Needed for <strong>${escapeHtml(n.name)}</strong>, because ${n.via.map((c) => escapeHtml(talkLabel(c))).join("; ")} teaches that and assumes this`);
    }
    const at = s.learn_at;
    let where = "";
    if (at && at.kind === "talk") {
      where = `<div class="learn">Learn it at <strong>${escapeHtml(dayShort(at.day))} ${formatTime(at.start)}</strong> · ${escapeHtml(at.title)}<br><q>${escapeHtml(at.evidence)}</q></div>`;
    } else if (at && at.kind === "explainer") {
      where = `<div class="learn">Learn it from <a href="${safeUrl(at.url)}" target="_blank" rel="noopener">${escapeHtml(at.title)}</a> <span class="muted">(explainer, fetched ${escapeHtml(at.fetched_at || "")})</span></div>`;
    } else if (at) {
      where = `<div class="learn muted">No talk teaches this before your talk starts.</div>`;
    }
    return `<div class="node step"><span class="step-n">${i + 1}</span> <strong>${escapeHtml(s.name)}</strong>
      ${why.map((w) => `<div class="why">${w}</div>`).join("")}${where}${s.note ? `<div class="note">${escapeHtml(s.note)}</div>` : ""}</div>`;
  }).join(`<div class="arrow">↓</div>`);
  box.innerHTML = `${cards}<div class="arrow">↓</div>
    <div class="node target"><span class="label">Your talk</span>${escapeHtml(target)}</div>${
    known.length ? `<p class="muted">Skipped because you know them: ${known.map(escapeHtml).join(", ")}</p>` : ""}`;
}

// ---- the day plan ------------------------------------------------------------

function renderDayPlan() {
  const box = document.getElementById("dayplan");
  const plan = view.plan;
  if (!plan || plan.ready || !plan.plan.length) { box.innerHTML = ""; return; }
  const groups = new Map();
  plan.plan.forEach((s, i) => {
    const at = s.learn_at || { kind: "needs_explainer" };
    const key = at.kind === "talk" ? `t|${at.code}` : at.kind === "explainer" ? `x|${at.url}` : `n|${s.concept}`;
    if (!groups.has(key)) {
      const order = at.kind === "talk" ? Number(at.start_min) || 0 : at.kind === "explainer" ? -1 : -2;
      groups.set(key, { at, order, steps: [], notes: [] });
    }
    const g = groups.get(key);
    g.steps.push({ n: i + 1, name: s.name });
    if (s.note && !g.notes.includes(s.note)) g.notes.push(s.note);
  });
  const rows = [...groups.values()].sort((a, b) => a.order - b.order).map((g) => {
    const covers = g.steps.map((s) => `<span class="cover">Step ${s.n} · ${escapeHtml(s.name)}</span>`).join("");
    const clash = g.notes.some((n) => /clash/i.test(n));
    const notes = g.notes.map((n) => `<div class="row-note${/clash/i.test(n) ? " clash" : ""}">${/clash/i.test(n) ? "⚠ " : ""}${escapeHtml(n)}</div>`).join("");
    const at = g.at;
    if (at.kind === "talk") {
      return `<li class="row${clash ? " has-clash" : ""}">
        <div class="row-time"><span>${escapeHtml(dayShort(at.day))}</span><strong>${formatTime(at.start)}</strong></div>
        <div class="row-what">
          <button class="row-title" data-code="${escapeHtml(at.code)}">${escapeHtml(at.title)}</button>
          <div class="muted">${escapeHtml(at.room)} · until ${formatTime(at.end)}</div>
          <div class="covers">${covers}</div>${notes}
        </div></li>`;
    }
    if (at.kind === "explainer") {
      return `<li class="row explainer">
        <div class="row-time"><span>Any time</span><strong>before</strong></div>
        <div class="row-what">
          <a class="row-title" href="${safeUrl(at.url)}" target="_blank" rel="noopener">${escapeHtml(at.title || at.url)} ↗</a>
          <div class="muted">Outside explainer · no talk teaches this in time</div>
          <div class="covers">${covers}</div>
        </div></li>`;
    }
    return `<li class="row gap">
      <div class="row-time"><span>Gap</span><strong>—</strong></div>
      <div class="row-what"><div class="row-title plain">No talk teaches this before your talk</div>
        <div class="covers">${covers}</div>${notes}</div></li>`;
  });
  const t = findTalk(plan.talk);
  rows.push(`<li class="row final">
    <div class="row-time"><span>${escapeHtml(dayShort(t ? t.day : ""))}</span><strong>${t ? formatTime(t.start) : ""}</strong></div>
    <div class="row-what"><button class="row-title" data-code="${escapeHtml(plan.talk)}">${escapeHtml(plan.talk_title)}</button>
      <div class="muted">Your talk${t ? ` · ${escapeHtml(t.room)}` : ""}</div></div></li>`);
  box.innerHTML = `<h3>Your day</h3><ol class="timeline">${rows.join("")}</ol>`;
}

// ---- details dialog ----------------------------------------------------------

function openDialog(html, ctx) {
  const dlg = document.getElementById("detail");
  dialogCtx = ctx;
  document.getElementById("detail-body").innerHTML = html;
  if (!dlg.open) {
    if (typeof dlg.showModal === "function") dlg.showModal();
    else dlg.setAttribute("open", "");
  }
}

function closeDialog() {
  const dlg = document.getElementById("detail");
  if (dlg.open) { if (typeof dlg.close === "function") dlg.close(); else dlg.removeAttribute("open"); }
  dialogCtx = null;
}

function graphNode(id) {
  return view.graph ? view.graph.nodes.find((n) => n.id === id) : null;
}

function nodeWhen(node) {
  const d = (node && node.data) || {};
  return `${dayShort(d.day)} ${formatTime(d.start)}`;
}

function openNode(id) {
  const node = graphNode(id);
  if (!node) return;
  if (node.type === "concept") openConcept(node);
  else if (node.type === "explainer") openExplainer(node);
  else if (node.data && node.data.code) openTalk(node.data.code);
}

function openConcept(node) {
  const g = view.graph;
  const d = node.data || {};
  const stepIdx = (view.plan.plan || []).findIndex((s) => s.concept === d.concept);
  const step = stepIdx >= 0 ? view.plan.plan[stepIdx] : null;
  const known = (view.plan.already_known || []).find((k) => k.concept === d.concept);
  const why = [];
  for (const e of g.edges) {
    if (e.type === "REQUIRES" && e.target === node.id) {
      why.push(`<li>Your talk's abstract assumes it: <q>${escapeHtml(e.evidence)}</q>${e.status === "unsure" ? ` <span class="unsure">unsure</span>` : ""}</li>`);
    }
    if (e.type === "DEPENDS_ON" && e.target === node.id) {
      const other = graphNode(e.source);
      why.push(`<li>Needed for <strong>${escapeHtml(other ? other.label : e.source)}</strong>${e.evidence ? `: <q>${escapeHtml(e.evidence)}</q>` : ""}</li>`);
    }
    if (e.type === "DEPENDS_ON" && e.source === node.id) {
      const other = graphNode(e.target);
      why.push(`<li>Builds on <strong>${escapeHtml(other ? other.label : e.target)}</strong></li>`);
    }
  }
  const where = g.edges
    .filter((e) => (e.type === "TEACHES" || e.type === "EXPLAINS") && e.target === node.id)
    .sort((a, b) => Number(b.chosen) - Number(a.chosen))
    .map((e) => {
      const src = graphNode(e.source);
      if (!src) return "";
      const title = src.type === "explainer"
        ? `<a href="${safeUrl(src.data && src.data.url)}" target="_blank" rel="noopener">${escapeHtml(src.label)} ↗</a> <span class="muted">(outside explainer)</span>`
        : `<strong>${escapeHtml(nodeWhen(src))}</strong> · ${escapeHtml(src.label)}`;
      return `<li class="${e.chosen ? "chosen" : "alt"}">${e.chosen ? `<span class="pill">In your plan</span> ` : ""}${title}${
        e.evidence ? `<br><q>${escapeHtml(e.evidence)}</q>` : ""}</li>`;
    }).join("");
  const status = known
    ? `<span class="pill ok">✓ Known · ${knownHow(known.how)}</span>`
    : step ? `<span class="pill">Step ${stepIdx + 1} of ${view.plan.plan.length}</span>` : "";
  const html = `
    <span class="label">Concept</span>
    <h2>${escapeHtml(node.label)}</h2>
    ${status}
    <p class="definition">${escapeHtml(d.definition || "")}</p>
    ${why.length ? `<h3>Why it's on your path</h3><ul class="evidence">${why.join("")}</ul>` : ""}
    ${where ? `<h3>Where to learn it</h3><ul class="evidence">${where}</ul>` : ""}
    ${step && step.note ? `<p class="row-note${/clash/i.test(step.note) ? " clash" : ""}">${escapeHtml(step.note)}</p>` : ""}
    <p class="muted small">Quotes are taken word for word from the talk abstracts; they are the evidence on each graph edge.</p>
    <div class="dialog-actions">
      ${known ? "" : `<button class="primary" data-act="known">I already know this</button>`}
      <button class="secondary" data-act="where">Where can I learn it? (ask the agent)</button>
    </div>`;
  openDialog(html, { kind: "concept", concept: d.concept, name: node.label });
}

function openExplainer(node) {
  const d = node.data || {};
  const edge = view.graph.edges.find((e) => e.source === node.id);
  const concept = edge ? graphNode(edge.target) : null;
  const html = `
    <span class="label">Outside explainer</span>
    <h2>${escapeHtml(node.label)}</h2>
    <p>No talk teaches ${concept ? `<strong>${escapeHtml(concept.label)}</strong>` : "this"} before your talk starts, so I found a short read instead.</p>
    ${edge && edge.evidence ? `<ul class="evidence"><li><q>${escapeHtml(edge.evidence)}</q></li></ul>` : ""}
    <p class="muted small">Fetched ${escapeHtml(d.fetched_at || "")}</p>
    <div class="dialog-actions"><a class="primary" href="${safeUrl(d.url)}" target="_blank" rel="noopener">Open the explainer ↗</a></div>`;
  openDialog(html, { kind: "explainer" });
}

async function openTalk(code) {
  const basic = findTalk(code);
  openDialog(`<span class="label">Talk</span><h2>${escapeHtml(basic ? basic.title : code)}</h2><p class="muted">Loading details…</p>`, { kind: "talk", code });
  let t = basic;
  try { t = await api(`/api/talks/${encodeURIComponent(code)}`); } catch { /* fall back to the list entry */ }
  if (!dialogCtx || dialogCtx.kind !== "talk" || dialogCtx.code !== code || !t) return;
  // If this talk is on the current path, show what it teaches there and the quote.
  const teaches = view.graph ? view.graph.edges.filter((e) => e.source === `talk:${code}` && e.type === "TEACHES") : [];
  const onPath = teaches.map((e) => {
    const c = graphNode(e.target);
    return `<li>${e.chosen ? `<span class="pill">In your plan</span> ` : ""}Teaches <strong>${escapeHtml(c ? c.label : e.target)}</strong>${
      e.evidence ? `: <q>${escapeHtml(e.evidence)}</q>` : ""}</li>`;
  }).join("");
  const isTarget = view.talk === code;
  const attended = view.attended.includes(t.title);
  const html = `
    <span class="label">${isTarget ? "Your talk" : "Talk"} · ${escapeHtml(t.code)}</span>
    <h2>${escapeHtml(t.title)}</h2>
    <div class="facts">
      <span><strong>${escapeHtml(t.day)}</strong> ${formatTime(t.start)}–${formatTime(t.end)}</span>
      <span>${escapeHtml(t.room)}</span>
      <span>${levelBadge(t.level_num)}${escapeHtml(t.level || t.type || "")}</span>
      ${t.sponsor ? `<span class="pill">Sponsored</span>` : ""}
      ${attended ? `<span class="pill ok">✓ Attended</span>` : ""}
    </div>
    ${(t.speakers || []).length ? `<p><span class="muted">Speakers:</span> ${t.speakers.map(escapeHtml).join(", ")}</p>` : ""}
    ${t.abstract ? `<p class="abstract">${escapeHtml(t.abstract)}</p>` : ""}
    ${onPath ? `<h3>On your path</h3><ul class="evidence">${onPath}</ul>` : ""}
    ${(t.topics || []).length ? `<div class="topics">${t.topics.map((x) => `<span class="topic">${escapeHtml(x)}</span>`).join("")}</div>` : ""}
    ${t.url ? `<p class="small"><a href="${safeUrl(t.url)}" target="_blank" rel="noopener">Session page ↗</a></p>` : ""}
    <div class="dialog-actions">
      <button class="primary" data-act="ready">Get me ready</button>
      <button class="secondary" data-act="plan">Plan without AI</button>
      ${attended ? "" : `<button class="secondary" data-act="attended">I attended this</button>`}
    </div>`;
  document.getElementById("detail-body").innerHTML = html;
}

async function onDialogAction(act) {
  const ctx = dialogCtx;
  if (!ctx) return;
  closeDialog();
  if (ctx.kind === "talk") {
    const talk = findTalk(ctx.code);
    if (act === "ready") ask(`Get me ready for "${talk ? talk.title : ctx.code}" (${ctx.code}).`);
    if (act === "plan") planWithoutAI(ctx.code);
    if (act === "attended") attendedTalk(ctx.code);
  } else if (ctx.kind === "concept") {
    if (act === "known") markKnown(ctx.concept, ctx.name);
    if (act === "where") {
      const title = view.plan ? view.plan.talk_title : "my talk";
      ask(`Where can I learn "${ctx.name}" before "${title}"?`);
    }
  }
}

// ---- wiring ----------------------------------------------------------------

async function init() {
  const [clock, talks, health] = await Promise.all([api("/api/clock"), api("/api/talks"), api("/api/health")]);
  document.getElementById("conference").textContent = clock.conference;
  document.getElementById("clock").textContent = formatClock(clock.now);
  document.getElementById("status").textContent = `${health.talks} talks · graph “${health.graph}” on ${health.backend}${
    graphAvailable() ? "" : " · graph drawing unavailable, showing text path"}`;
  allTalks = talks;
  renderTalks(allTalks);
  renderHead(false);
  await startAttendee();
  renderTalks(allTalks);

  const talksBox = document.getElementById("talks");
  talksBox.addEventListener("click", (e) => {
    const button = e.target.closest("button[data-action]");
    const row = e.target.closest(".talk");
    if (!row) return;
    const code = row.dataset.code;
    const talk = findTalk(code);
    if (!talk) return;
    if (!button) return openTalk(code);
    if (button.dataset.action === "ask") ask(`Get me ready for "${talk.title}" (${code}).`);
    if (button.dataset.action === "plan") planWithoutAI(code);
    if (button.dataset.action === "attended") attendedTalk(code);
  });
  talksBox.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || e.target.closest("button")) return;
    const row = e.target.closest(".talk");
    if (row) openTalk(row.dataset.code);
  });
  document.getElementById("search").addEventListener("input", () => renderTalks(currentTalkList()));
  document.getElementById("composer").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = document.getElementById("input");
    const text = input.value.trim();
    if (!text || asking) return;
    input.value = "";
    ask(text);
  });

  // Right panel: talk title, timeline rows and the alternatives toggle.
  document.getElementById("ready-head").addEventListener("click", (e) => {
    if (e.target.closest("[data-open-talk]") && view.talk) openTalk(view.talk);
  });
  document.getElementById("dayplan").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-code]");
    if (b) openTalk(b.dataset.code);
  });
  document.getElementById("toggle-alts").addEventListener("click", () => {
    if (!view.graph) return;
    view.showAlts = !view.showAlts;
    renderGraph(false); // fresh layout: the best direction can change with more boxes
  });

  const dlg = document.getElementById("detail");
  dlg.addEventListener("click", (e) => {
    if (e.target === dlg || e.target.closest("[data-close]")) return closeDialog();
    const b = e.target.closest("button[data-act]");
    if (b) onDialogAction(b.dataset.act);
  });
  dlg.addEventListener("close", () => { dialogCtx = null; });

  window.addEventListener("resize", () => { if (cy) { cy.resize(); sizeAndFit(false); } });
  try {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { if (cy) cy.style(graphStyle()); });
  } catch { /* old browsers */ }

  document.getElementById("forget").addEventListener("click", async () => {
    if (!confirm("Delete everything Throughline remembers about you?")) return;
    await api(`/api/attendees/${encodeURIComponent(attendee)}`, { method: "DELETE" });
    storageSet(CODE_KEY, null);
    history = [];
    await startAttendee();
    addMessage("agent card", `<p>Forgotten. You have a fresh code: <strong>${escapeHtml(attendee)}</strong>.</p>`);
    await refreshAll();
  });
  document.getElementById("switch-code").addEventListener("click", async () => {
    // Accept the code with or without dashes or spaces: "k7qf m2xa 9plr" -> "K7QF-M2XA-9PLR".
    const raw = (prompt("Enter your Throughline code") || "").toUpperCase().replace(/[^0-9A-Z]/g, "");
    if (!raw) return;
    const code = raw.length === 12 ? raw.match(/.{4}/g).join("-") : raw;
    const previous = attendee;
    try {
      attendee = code;
      const state = await refreshAttendee();
      storageSet(CODE_KEY, code);
      history = [];
      addMessage("agent card", `<p>Welcome back. You know ${state.known.length} concept(s) and attended ${state.attended.length} talk(s).</p>`);
      await refreshAll();
    } catch {
      attendee = previous;
      await refreshAttendee();
      alert("That code isn't known.");
    }
  });

  // Come back to the talk you were looking at.
  const saved = storageGet(TALK_KEY);
  if (saved && findTalk(saved)) {
    loadTalkView(saved, { trace: true }).catch(() => storageSet(TALK_KEY, null));
  }
}

init().catch((err) => {
  document.getElementById("status").textContent = `Couldn't load: ${err.message}`;
});
