// Throughline landing page: the talk flow graph, "Don't miss", the calendar and a small profile dialog.
// All feed data and model text is untrusted: everything going into innerHTML goes through escapeHtml.

const CODE_KEY = "throughline.attendee"; // shared with the attendee page (talk.html)
const EXPERIENCE = { new: "New to this", some: "Some experience", experienced: "Experienced" };
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// Flow graph geometry (graph units; Cytoscape zooms the whole thing).
const NODE_W = 142;
const NODE_H = 58;
const LANE_GAP = 10;
const COL_GAP = 28;
const DAY_GAP = 56;
const HEAD_H = 64; // room above the boxes for the day name and slot times

let attendee = null;
const me = { profile: null, targets: [] };
let allTalks = null;   // GET /api/talks, loaded when the calendar first opens
let flowData = null;
let cy = null;
let clockNow = null;   // "2026-10-28T08:30"
let clockConference = ""; // the conference name /api/clock reports, used until /api/conferences answers
let conferences = null;   // GET /api/conferences
let activeHighlight = null; // talk codes the chat picked, lit up on the flow graph
const PLACE_KEY = "throughline.place";

// ---- helpers (copied from app.js) ---------------------------------------------

function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function safeUrl(url) {
  return /^https:\/\//.test(url || "") ? escapeHtml(url) : "#";
}

// Minimal formatting for agent replies: escape, then **bold** and line breaks.
function formatReply(text) {
  return escapeHtml(text).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/\n/g, "<br>");
}

function formatTime(hhmm) {
  if (!hhmm || !/^\d{1,2}:\d{2}/.test(hhmm)) return "";
  const [h, m] = hhmm.split(":").map(Number);
  return `${((h + 11) % 12) + 1}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
}

function minutesOfDay(hhmm) {
  if (!hhmm || !/^\d{1,2}:\d{2}/.test(hhmm)) return null;
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
}

function hourLabel(h) {
  return `${((h + 11) % 12) + 1} ${h < 12 ? "AM" : "PM"}`;
}

function dayShort(day) {
  return String(day || "").slice(0, 3);
}

function dateLabel(date) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date || "");
  return m ? `${MONTHS[Number(m[2]) - 1]} ${Number(m[3])}` : "";
}

function levelClass(levelNum) {
  const n = Number(levelNum);
  return [100, 200, 300].includes(n) ? `l${n}` : "l0";
}

function levelBadge(levelNum) {
  const n = Number(levelNum);
  return [100, 200, 300].includes(n) ? `<span class="level l${n}">${n}</span>` : "";
}

function shortTitle(title, max = 54) {
  let t = String(title || "").replace(/\s*\(Sponsored\)\s*$/i, "");
  const colon = t.indexOf(": ");
  if (colon >= 14) t = t.slice(0, colon);
  return t.length > max ? `${t.slice(0, max - 1).trimEnd()}…` : t;
}

function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

function talkHref(code) {
  return `/talk.html?code=${encodeURIComponent(code)}`;
}

function storageGet(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
function storageSet(key, value) {
  try { value === null ? localStorage.removeItem(key) : localStorage.setItem(key, value); } catch { /* private mode */ }
}

async function api(path, options = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  if (!res.ok) {
    const err = new Error((await res.json().catch(() => ({}))).detail || res.statusText);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

function cssVar(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

function attendeeQuery() {
  return attendee ? `?attendee=${encodeURIComponent(attendee)}` : "";
}

// ---- attendee + profile -----------------------------------------------------------

async function loadAttendee() {
  const state = await api(`/api/attendees/${encodeURIComponent(attendee)}`);
  me.profile = state.profile && typeof state.profile === "object" ? state.profile : {};
  me.targets = Array.isArray(state.targets) ? state.targets : [];
  renderProfileButton();
  return state;
}

async function startAttendee() {
  const saved = storageGet(CODE_KEY);
  if (saved) {
    try {
      attendee = saved;
      await loadAttendee();
      return;
    } catch { /* code expired or deleted: make a new one */ }
  }
  attendee = (await api("/api/attendees", { method: "POST" })).code;
  storageSet(CODE_KEY, attendee);
  await loadAttendee();
}

function profileIsSet(p) {
  return Boolean(p && (p.updated_at || p.role || p.experience || (p.interests || []).length));
}

function profileSummary(p) {
  if (!p) return "";
  const parts = [p.role, EXPERIENCE[p.experience]].filter(Boolean);
  if (!parts.length && (p.interests || []).length) parts.push(p.interests.slice(0, 2).join(", "));
  return parts.join(" · ");
}

function renderProfileButton() {
  const label = profileSummary(me.profile) || (profileIsSet(me.profile) ? "Edit profile" : "Set up profile");
  document.getElementById("profile-label").textContent = label;
  document.getElementById("open-profile").title = attendee ? `Your profile · code ${attendee}` : "Your profile";
}

const draft = { interests: [] };

function openProfile() {
  const dlg = document.getElementById("profile");
  clearHighlight();
  const p = me.profile || {};
  draft.interests = [...(p.interests || [])];
  const exp = ["", "new", "some", "experienced"].map((v) => `
    <label class="seg"><input type="radio" name="experience" value="${v}" ${(p.experience || "") === v ? "checked" : ""}>
      <span>${v ? escapeHtml(EXPERIENCE[v]) : "Not saying"}</span></label>`).join("");
  document.getElementById("profile-body").innerHTML = `
    <span class="label">Your profile · ${escapeHtml(attendee || "")}</span>
    <h2 id="pf-title">About you</h2>
    <p class="muted">Throughline uses this to mark the talks you're already ready for (✓) and to pick what you shouldn't miss.</p>
    <form id="profile-form" class="profile-form">
      <label class="field"><span>Role</span>
        <input id="pf-role" list="role-options" maxlength="60" placeholder="e.g. Developer" value="${escapeHtml(p.role || "")}"></label>
      <fieldset class="field"><legend>Experience</legend><div class="segs">${exp}</div></fieldset>
      <div class="field"><span>Interests</span>
        <div class="tags" id="pf-tags"></div>
        <input id="pf-interest" maxlength="40" placeholder="Type a topic, press Enter (e.g. agents, security)"></div>
      <div class="dialog-actions">
        <button class="primary" type="submit">Save profile</button>
        <span id="pf-status" class="muted" role="status"></span>
      </div>
      <p class="muted small">Saved talks and the concepts you already know live on the <a href="/talk.html">attendee page</a>.</p>
    </form>`;
  renderTags();
  if (!dlg.open) {
    if (typeof dlg.showModal === "function") dlg.showModal();
    else dlg.setAttribute("open", "");
  }
}

function closeDialog(dlg) {
  if (!dlg.open) return;
  if (typeof dlg.close === "function") dlg.close();
  else { dlg.removeAttribute("open"); dlg.dispatchEvent(new Event("close")); }
}

function renderTags() {
  const box = document.getElementById("pf-tags");
  if (!box) return;
  box.innerHTML = draft.interests.map((t, i) =>
    `<span class="tag">${escapeHtml(t)}<button type="button" data-untag="${i}" aria-label="Remove ${escapeHtml(t)}">×</button></span>`).join("");
}

function addInterest(raw) {
  for (const part of String(raw).split(",")) {
    const tag = part.trim().slice(0, 40);
    if (tag && !draft.interests.some((x) => x.toLowerCase() === tag.toLowerCase()) && draft.interests.length < 12) {
      draft.interests.push(tag);
    }
  }
  renderTags();
}

async function saveProfile() {
  const status = document.getElementById("pf-status");
  const pending = document.getElementById("pf-interest");
  if (pending && pending.value.trim()) { addInterest(pending.value); pending.value = ""; }
  const checked = document.querySelector('#profile-form input[name="experience"]:checked');
  const body = {
    role: document.getElementById("pf-role").value.trim(),
    experience: checked ? checked.value : "",
    interests: draft.interests,
  };
  status.textContent = "Saving…";
  try {
    const result = await api(`/api/attendees/${encodeURIComponent(attendee)}/profile`, { method: "PUT", body: JSON.stringify(body) });
    me.profile = (result && result.profile) || { ...body, updated_at: "now" };
    renderProfileButton();
    status.textContent = "Saved ✓ Updating the flow…";
    await Promise.allSettled([loadFlow(), loadFeatured()]);
    status.textContent = "Saved ✓";
  } catch (err) {
    status.textContent = `Couldn't save: ${err.message}`;
  }
}

function wireProfile() {
  const dlg = document.getElementById("profile");
  document.getElementById("open-profile").addEventListener("click", () => {
    if (!attendee) return;
    openProfile();
  });
  dlg.addEventListener("click", (e) => {
    if (e.target === dlg || e.target.closest("[data-close]")) return closeDialog(dlg);
    const untag = e.target.closest("[data-untag]");
    if (untag) { draft.interests.splice(Number(untag.dataset.untag), 1); renderTags(); }
  });
  dlg.addEventListener("submit", (e) => { e.preventDefault(); saveProfile(); });
  dlg.addEventListener("keydown", (e) => {
    if (e.target.id !== "pf-interest") return;
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addInterest(e.target.value);
      e.target.value = "";
    } else if (e.key === "Backspace" && !e.target.value && draft.interests.length) {
      draft.interests.pop();
      renderTags();
    }
  });
}

// ---- the talk flow graph ------------------------------------------------------------

function setFlowState(html, isError = false) {
  const el = document.getElementById("flow-state");
  el.hidden = !html;
  el.classList.toggle("error", isError);
  el.innerHTML = html || "";
}

async function loadFlow() {
  try {
    // include= asks the server to keep the chat's picks on the map even when they aren't among the most connected.
    const include = activeHighlight && activeHighlight.length
      ? `${attendee ? "&" : "?"}include=${encodeURIComponent(activeHighlight.join(","))}` : "";
    flowData = await api(`/api/flow${attendeeQuery()}${include}`);
  } catch (err) {
    if (!cy) {
      setFlowState(err.status === 404
        ? "The talk flow isn't available yet. Try again in a moment."
        : `Couldn't load the talk flow: ${escapeHtml(err.message)}`, true);
    }
    scheduleRetry(err);
    return;
  }
  const nodes = Array.isArray(flowData && flowData.nodes) ? flowData.nodes : [];
  if (!nodes.length) {
    destroyFlow();
    setFlowState("No talks to show yet.");
    return;
  }
  if (typeof window.cytoscape !== "function") {
    setFlowState("The graph library didn't load, so the flow can't be drawn. The talks are listed below.", true);
    return;
  }
  setFlowState("");
  drawFlow(flowData);
}

// While the backend endpoint is being deployed it 404s: poll gently until it appears.
let retryTimer = null;
function scheduleRetry(err) {
  if (retryTimer || err.status !== 404) return;
  retryTimer = setTimeout(() => { retryTimer = null; loadFlow(); }, 15000);
}

function flowStyle() {
  const c = {
    ink: cssVar("--ink", "#1d1d1b"), muted: cssVar("--muted", "#6b6a65"), edge: cssVar("--edge", "#c4c1b6"),
    line: cssVar("--line", "#e4e2db"), panel: cssVar("--panel", "#ffffff"), accent: cssVar("--accent", "#2f5bd3"),
    ok: cssVar("--ok", "#2e7d4f"), star: cssVar("--star", "#c08a00"), bg: cssVar("--bg", "#f7f6f2"),
    l100: cssVar("--l100", "#2e7d4f"), l200: cssVar("--l200", "#b26a00"), l300: cssVar("--l300", "#b3261e"), l0: cssVar("--l0", "#8a887f"),
  };
  const font = '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
  return [
    { selector: "node.talk", style: {
      shape: "round-rectangle", width: NODE_W, height: NODE_H, label: "data(label)",
      "text-wrap": "wrap", "text-max-width": NODE_W - 12, "text-valign": "center", "text-halign": "center",
      "font-family": font, "font-size": 13, "font-weight": 500, color: c.ink, "line-height": 1.2,
      "background-color": c.panel, "border-width": 1.5, "border-color": c.edge,
      "transition-property": "opacity, border-color, border-width", "transition-duration": "180ms",
    } },
    // Level shows as a coloured border; must-see gets a gold ring outside it.
    { selector: "node.talk.l100", style: { "border-color": c.l100, "border-width": 2.5 } },
    { selector: "node.talk.l200", style: { "border-color": c.l200, "border-width": 2.5 } },
    { selector: "node.talk.l300", style: { "border-color": c.l300, "border-width": 2.5 } },
    { selector: "node.talk.must", style: { "outline-width": 3, "outline-color": c.star, "outline-offset": 2, "font-weight": 700 } },
    { selector: "node.talk.ready", style: { "background-color": cssVar("--ok-soft", "#e4f3ea") } },
    { selector: "node.talk.lonely", style: { opacity: 0.55 } },
    // The chat's picks: glow and a thick accent border; everything else steps back.
    { selector: "node.talk.dimmed", style: { opacity: 0.16 } },
    { selector: "node.talk.picked", style: {
      opacity: 1, "border-color": c.accent, "border-width": 5, "font-weight": 700, "z-index": 15,
      "underlay-color": c.accent, "underlay-opacity": 0.28, "underlay-padding": 9, "underlay-shape": "round-rectangle",
    } },
    { selector: "node.talk.hover", style: { "border-color": c.accent, "border-width": 4, "z-index": 20 } },
    { selector: "node.talk.chain", style: { opacity: 1, "z-index": 10 } },
    { selector: "node.axis", style: {
      shape: "rectangle", width: 1, height: 1, "background-opacity": 0, label: "data(label)",
      "font-family": font, "font-size": 13, color: c.muted, "text-valign": "center", "text-halign": "right",
      events: "no",
    } },
    { selector: "node.dayname", style: { "font-size": 19, "font-weight": 700, color: c.ink } },
    { selector: "node.colhead", style: { "text-halign": "center", "font-size": 13, "font-weight": 600 } },
    { selector: "node.divider", style: {
      shape: "rectangle", width: 2, height: "data(h)", "background-color": c.edge, "background-opacity": 1, events: "no", "z-index": 0,
    } },
    { selector: "edge", style: {
      width: "mapData(weight, 1, 6, 1.4, 4)", "line-color": c.edge, "target-arrow-color": c.edge,
      "target-arrow-shape": "triangle", "arrow-scale": 0.9, "curve-style": "bezier", opacity: 0.85,
      "transition-property": "opacity, line-color, width", "transition-duration": "180ms",
    } },
    { selector: "edge.dimmed", style: { opacity: 0.07 } },
    { selector: "edge.picked", style: { "line-color": c.accent, "target-arrow-color": c.accent, width: 4.5, opacity: 1, "z-index": 14 } },
    { selector: "edge.chain", style: { "line-color": c.accent, "target-arrow-color": c.accent, opacity: 1, "z-index": 9 } },
    { selector: "edge.hover", style: {
      "line-color": c.accent, "target-arrow-color": c.accent, opacity: 1, width: 4, "z-index": 12,
      label: "data(label)", "font-family": font, "font-size": 11, color: c.ink, "text-wrap": "wrap", "text-max-width": 200,
      "text-background-color": c.panel, "text-background-opacity": 1, "text-background-padding": 3,
      "text-background-shape": "roundrectangle", "text-border-color": c.accent, "text-border-width": 1, "text-border-opacity": 1,
    } },
    { selector: ".faded", style: { opacity: 0.12 } },
  ];
}

// Talks go left to right in time order, packed into columns of time slots. A talk opens a new column
// when the current one is full, the day changes, or a talk in the current column prepares you for it,
// so every arrow points right. Several lane counts are tried; the one that reads biggest wins.
function packColumns(nodes, prereqs, lanes) {
  const cols = [];
  const colOf = new Map();
  for (const n of nodes) {
    let cur = cols[cols.length - 1];
    const blocked = (prereqs.get(n.code) || []).some((p) => colOf.get(p) === cols.length - 1);
    if (!cur || cur.date !== n.date || cur.nodes.length >= lanes || blocked) {
      cur = { date: n.date, day: n.day, nodes: [] };
      cols.push(cur);
    }
    cur.nodes.push(n);
    colOf.set(n.code, cols.length - 1);
  }
  return cols;
}

function timeRange(a, b) {
  if (!b || a === b) return formatTime(a);
  const fa = formatTime(a);
  const fb = formatTime(b);
  return fa.slice(-2) === fb.slice(-2) ? `${fa.slice(0, -3)}–${fb}` : `${fa}–${fb}`;
}

function flowElements(data, boxW, boxH) {
  const nodes = data.nodes
    .filter((n) => n && n.code && Number.isFinite(Number(n.start_min)))
    .sort((a, b) => Number(a.start_min) - Number(b.start_min) || String(a.code).localeCompare(String(b.code)));
  const codes = new Set(nodes.map((n) => n.code));
  const edges = (data.edges || []).filter((e) => e && codes.has(e.source) && codes.has(e.target) && e.source !== e.target);
  const prereqs = new Map();
  const linked = new Set();
  for (const e of edges) {
    if (!prereqs.has(e.target)) prereqs.set(e.target, []);
    prereqs.get(e.target).push(e.source);
    linked.add(e.source); linked.add(e.target);
  }
  const dates = [...new Set(nodes.map((n) => n.date))].sort();
  const colW = NODE_W + COL_GAP;
  const rowH = NODE_H + LANE_GAP;
  const sizeOf = (cols) => {
    const lanes = Math.max(...cols.map((c) => c.nodes.length));
    return { w: cols.length * colW - COL_GAP + (dates.length - 1) * DAY_GAP, h: lanes * rowH + HEAD_H };
  };
  let best = null;
  for (let lanes = 3; lanes <= 14; lanes++) {
    const cols = packColumns(nodes, prereqs, lanes);
    const s = sizeOf(cols);
    const zoom = Math.min(boxW / s.w, boxH / s.h, 1.4);
    if (!best || zoom > best.zoom + 0.01) best = { cols, zoom, ...s };
  }
  const cols = best.cols;
  const els = [];
  let dayIndex = -1;
  let lastDate = null;
  cols.forEach((col, i) => {
    if (col.date !== lastDate) { dayIndex++; lastDate = col.date; }
    const left = i * colW + dayIndex * DAY_GAP;
    const cx = left + NODE_W / 2;
    if (i === 0 || cols[i - 1].date !== col.date) {
      els.push({ group: "nodes", data: { id: `axis-day-${col.date}`, label: `${col.day || ""} · ${dateLabel(col.date)}` },
        position: { x: left, y: -HEAD_H + 12 }, classes: "axis dayname" });
      if (dayIndex > 0) {
        els.push({ group: "nodes", data: { id: `divider-${col.date}`, h: best.h + 10 },
          position: { x: left - (DAY_GAP + COL_GAP) / 2, y: best.h / 2 - HEAD_H + 2 }, classes: "divider" });
      }
    }
    const first = col.nodes[0].start;
    const last = col.nodes[col.nodes.length - 1].start;
    els.push({ group: "nodes", data: { id: `axis-col-${i}`, label: timeRange(first, last) },
      position: { x: cx, y: -16 }, classes: "axis colhead" });
    col.nodes.forEach((n, lane) => {
      const marks = `${n.must_see ? "★ " : ""}${n.ready ? "✓ " : ""}`;
      const classes = ["talk", levelClass(n.level_num)];
      if (n.must_see) classes.push("must");
      if (n.ready) classes.push("ready");
      if (!linked.has(n.code)) classes.push("lonely");
      els.push({
        group: "nodes",
        data: { id: n.code, label: `${marks}${shortTitle(n.short_title || n.title, 31 - marks.length * 2)}\n${formatTime(n.start)}` },
        position: { x: cx, y: lane * rowH + NODE_H / 2 },
        classes: classes.join(" "),
      });
    });
  });

  for (const e of edges) {
    const concepts = Array.isArray(e.concepts) ? e.concepts.map(String) : [];
    els.push({
      group: "edges",
      data: {
        id: `e-${e.source}-${e.target}`, source: e.source, target: e.target,
        weight: Math.max(1, Math.min(6, Number(e.weight) || concepts.length || 1)),
        label: concepts.length ? `Teaches: ${concepts.slice(0, 3).join(", ")}${concepts.length > 3 ? ` +${concepts.length - 3}` : ""}` : "",
      },
    });
  }
  return els;
}

function destroyFlow() {
  if (cy) { cy.destroy(); cy = null; }
  document.getElementById("flow-zoom").hidden = true;
  hideCard();
}

function talkNodes() {
  return cy.nodes(".talk");
}

// Fit the whole flow (width first; the column packing already matched the canvas shape) and centre it.
function fitWidth(animate = false) {
  if (!cy) return;
  const bb = talkNodes().union(cy.nodes(".axis")).boundingBox();
  const w = cy.width();
  const h = cy.height();
  const pad = 24;
  let zoom = Math.min((w - pad * 2) / Math.max(bb.w, 1), (h - pad * 2) / Math.max(bb.h, 1), 1.4);
  zoom = Math.max(0.2, zoom);
  const panX = (w - bb.w * zoom) / 2 - bb.x1 * zoom;
  const panY = (h - bb.h * zoom) / 2 - bb.y1 * zoom;
  const target = { zoom, pan: { x: panX, y: panY } };
  if (animate) cy.animate(target, { duration: 300 });
  else { cy.zoom(zoom); cy.pan(target.pan); }
}

function drawFlow(data) {
  const box = document.getElementById("flow");
  const els = flowElements(data, Math.max(box.clientWidth - 48, 300), Math.max(box.clientHeight - 48, 200));
  const byCode = new Map(data.nodes.map((n) => [n.code, n]));
  destroyFlow();
  cy = window.cytoscape({
    container: document.getElementById("flow"),
    elements: els,
    style: flowStyle(),
    layout: { name: "preset" },
    minZoom: 0.15,
    maxZoom: 2.5,
    boxSelectionEnabled: false,
    autoungrabify: true,
    autounselectify: true,
  });
  cy.scratch("_byCode", byCode);
  fitWidth(false);
  document.getElementById("flow-zoom").hidden = false;
  document.getElementById("legend-ready").hidden = !data.nodes.some((n) => n.ready);
  const stats = document.getElementById("flow-stats");
  const shown = (data.edges || []).length;
  stats.textContent = Number(data.links_total) > shown && Number(data.talks_total) > 0
    ? `${data.nodes.length} of ${data.talks_total} talks · the ${shown} strongest of ${data.links_total} links in the graph`
    : `${plural(data.nodes.length, "talk", "talks")} · ${plural(shown, "link", "links")}`;

  cy.on("mouseover", "node.talk", (evt) => highlightChain(evt.target));
  cy.on("mouseout", "node.talk", clearHighlight);
  cy.on("mouseover", "edge", (evt) => {
    if (cy.elements(".hover").nonempty()) return;
    const e = evt.target;
    cy.elements().addClass("faded");
    e.union(e.source()).union(e.target()).removeClass("faded").addClass("chain");
    e.addClass("hover");
  });
  cy.on("mouseout", "edge", () => {
    if (cy.nodes(".hover").nonempty()) return;
    cy.elements().removeClass("faded chain hover");
  });
  cy.on("tap", "node.talk", (evt) => { window.location.href = talkHref(evt.target.id()); });
  cy.on("pan zoom", hideCard);
  cy.container().addEventListener("mouseleave", clearHighlight);
  if (activeHighlight) applyHighlight(activeHighlight, { animate: false });
}

function highlightChain(node) {
  const up = node.predecessors();
  const down = node.successors();
  cy.elements().addClass("faded");
  node.union(up).union(down).removeClass("faded").addClass("chain");
  node.addClass("hover");
  document.getElementById("flow").style.cursor = "pointer";
  showCard(node, up.nodes().length, down.nodes().length);
}

function clearHighlight() {
  if (!cy) return;
  cy.elements().removeClass("faded chain hover");
  document.getElementById("flow").style.cursor = "";
  hideCard();
}

function showCard(node, upCount, downCount) {
  const n = cy.scratch("_byCode").get(node.id());
  if (!n) return;
  const card = document.getElementById("flow-card");
  const prepares = Number.isFinite(Number(n.prepares)) ? Number(n.prepares) : node.outgoers("edge").length;
  const builds = Number.isFinite(Number(n.builds_on)) ? Number(n.builds_on) : node.incomers("edge").length;
  const pills = [];
  if (n.must_see) pills.push(`<span class="pill star">★ Must-see</span>`);
  if (n.ready === true) pills.push(`<span class="pill ok">✓ You're ready</span>`);
  pills.push(`<span class="pill">Prepares you for ${plural(prepares, "talk", "talks")}</span>`);
  pills.push(`<span class="pill plain">Builds on ${plural(builds, "talk", "talks")}</span>`);
  const chain = upCount + downCount;
  card.innerHTML = `
    <div>${levelBadge(n.level_num)} <span class="muted">${escapeHtml(n.type || "")}${n.sponsor ? " · Sponsored" : ""}</span></div>
    <h3>${escapeHtml(n.title || n.short_title || n.code)}</h3>
    <div class="facts">${escapeHtml(n.day || "")} ${escapeHtml(formatTime(n.start))}–${escapeHtml(formatTime(n.end))} · ${escapeHtml(n.room || "")}</div>
    <div class="counts">${pills.join("")}</div>
    ${chain ? `<div class="muted small" style="margin-top:6px">Highlighted: ${plural(chain, "talk", "talks")} in its chain</div>` : ""}
    <div class="hint">Click to see what to learn first →</div>`;
  card.hidden = false;
  // Put the card beside the node, flipping to stay inside the canvas.
  const wrap = document.getElementById("flow-wrap");
  const pos = node.renderedPosition();
  const half = node.renderedWidth() / 2;
  const cw = card.offsetWidth;
  const ch = card.offsetHeight;
  let x = pos.x + half + 14;
  if (x + cw > wrap.clientWidth - 8) x = pos.x - half - 14 - cw;
  x = Math.max(8, Math.min(x, wrap.clientWidth - cw - 8));
  let y = pos.y - ch / 2;
  y = Math.max(8, Math.min(y, wrap.clientHeight - ch - 8));
  card.style.left = `${x}px`;
  card.style.top = `${y}px`;
}

function hideCard() {
  document.getElementById("flow-card").hidden = true;
}

function wireFlow() {
  document.getElementById("flow-zoom").addEventListener("click", (e) => {
    const b = e.target.closest("[data-zoom]");
    if (!b || !cy) return;
    if (b.dataset.zoom === "fit") return fitWidth(true);
    const factor = b.dataset.zoom === "in" ? 1.25 : 0.8;
    cy.animate({ zoom: { level: cy.zoom() * factor, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } } }, { duration: 200 });
  });
  let t = null;
  window.addEventListener("resize", () => {
    clearTimeout(t);
    t = setTimeout(() => { if (cy && flowData) drawFlow(flowData); }, 200);
  });
  try {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { if (cy) cy.style(flowStyle()); });
  } catch { /* old browsers */ }
}

// ---- don't miss ---------------------------------------------------------------------

async function loadFeatured() {
  const box = document.getElementById("featured");
  let list;
  try {
    list = await api(`/api/featured${attendeeQuery()}`);
  } catch (err) {
    box.innerHTML = `<div class="lp-cards-state error">${err.status === 404
      ? "The highlights aren't available yet. Try again in a moment."
      : `Couldn't load the highlights: ${escapeHtml(err.message)}`}</div>`;
    if (err.status === 404) setTimeout(loadFeatured, 15000);
    return;
  }
  list = Array.isArray(list) ? list.filter((t) => t && t.code).slice(0, 8) : [];
  if (!list.length) {
    box.innerHTML = `<div class="lp-cards-state">Nothing to highlight yet. Browse every talk on the <a href="/talk.html">attendee page</a>.</div>`;
    return;
  }
  box.innerHTML = list.map((t) => `
    <a class="ft ${levelClass(t.level_num)}" href="${escapeHtml(talkHref(t.code))}">
      <span class="ft-reason">
        ${t.reason ? `<span class="pill${/main stage|keynote/i.test(t.reason) ? " star" : ""}">${escapeHtml(t.reason)}</span>` : ""}
        ${t.ready === true ? `<span class="pill ok">✓ Ready</span>` : ""}
      </span>
      <span class="ft-title">${escapeHtml(t.title)}</span>
      <span class="ft-meta">${levelBadge(t.level_num)} ${escapeHtml(dayShort(t.day))} ${escapeHtml(formatTime(t.start))}–${escapeHtml(formatTime(t.end))} · ${escapeHtml(t.room || "")}</span>
    </a>`).join("");
}

// ---- calendar -----------------------------------------------------------------------

const CAL_PX_PER_MIN = 1.7;
const CAL_PAD = 12;

async function openCalendar() {
  const dlg = document.getElementById("calendar");
  clearHighlight();
  if (!dlg.open) {
    if (typeof dlg.showModal === "function") dlg.showModal();
    else dlg.setAttribute("open", "");
  }
  if (location.hash !== "#calendar") history.replaceState(null, "", "#calendar");
  await renderCalendar();
}

function onCalendarClosed() {
  if (location.hash === "#calendar") history.replaceState(null, "", location.pathname + location.search);
}

// Prep talks: for each saved talk, the plan's steps that are learned at another talk.
async function prepTalks(targets) {
  const prep = new Map(); // prep talk code -> [saved talk titles]
  const results = await Promise.allSettled(targets.slice(0, 12).map((t) =>
    api(`/api/plan/${encodeURIComponent(t.code)}${attendeeQuery()}`).then((plan) => ({ t, plan }))));
  for (const r of results) {
    if (r.status !== "fulfilled") continue;
    const { t, plan } = r.value;
    for (const step of (plan && Array.isArray(plan.plan) ? plan.plan : [])) {
      const at = step && step.learn_at;
      if (at && at.kind === "talk" && at.code && at.code !== t.code) {
        const list = prep.get(at.code) || [];
        if (!list.includes(t.title)) list.push(t.title);
        prep.set(at.code, list);
      }
    }
  }
  return prep;
}

// Overlapping talks share the column: each cluster of overlaps is split into side-by-side tracks.
function layoutDay(talks) {
  const sorted = [...talks].sort((a, b) => a.s - b.s || b.e - a.e);
  const out = [];
  let cluster = [];
  let clusterEnd = -1;
  const flush = () => {
    const tracks = [];
    for (const ev of cluster) {
      let i = tracks.findIndex((end) => end <= ev.s);
      if (i === -1) { i = tracks.length; tracks.push(0); }
      tracks[i] = ev.e;
      ev.track = i;
    }
    // Let each talk widen into the tracks to its right that are free for its whole time.
    for (const ev of cluster) {
      ev.tracks = tracks.length;
      ev.span = 1;
      for (let k = ev.track + 1; k < tracks.length; k++) {
        if (cluster.some((o) => o.track === k && o.s < ev.e && o.e > ev.s)) break;
        ev.span++;
      }
      out.push(ev);
    }
    cluster = [];
  };
  for (const ev of sorted) {
    if (cluster.length && ev.s >= clusterEnd) flush();
    cluster.push(ev);
    clusterEnd = Math.max(clusterEnd, ev.e);
  }
  if (cluster.length) flush();
  return out;
}

async function renderCalendar() {
  const body = document.getElementById("cal-body");
  const sub = document.getElementById("cal-sub");
  try {
    if (!allTalks) allTalks = await api("/api/talks");
    if (attendee) await loadAttendee().catch(() => {});
  } catch (err) {
    body.innerHTML = `<div class="lp-cards-state error">Couldn't load the schedule: ${escapeHtml(err.message)}</div>`;
    return;
  }
  const talks = (Array.isArray(allTalks) ? allTalks : []).map((t) => ({
    t, s: minutesOfDay(t.start), e: minutesOfDay(t.end),
  })).filter((x) => x.s !== null).map((x) => ({ ...x, e: x.e !== null && x.e > x.s ? x.e : x.s + 30 }));
  if (!talks.length) {
    body.innerHTML = `<div class="lp-cards-state">No talks in the schedule yet.</div>`;
    return;
  }
  const saved = new Set(me.targets.map((t) => t.code));
  let prep = new Map();
  if (me.targets.length) {
    sub.textContent = "Finding the prep talks for your saved talks…";
    prep = await prepTalks(me.targets);
  }
  sub.textContent = me.targets.length
    ? `${plural(me.targets.length, "saved talk", "saved talks")} · ${plural([...prep.keys()].filter((c) => !saved.has(c)).length, "prep talk", "prep talks")} that get you ready for them. Click any talk to plan for it.`
    : "Every talk, by time and room. Save talks on the attendee page to see them and their prep talks highlighted here.";

  const startH = Math.floor(Math.min(...talks.map((x) => x.s)) / 60);
  const endH = Math.ceil(Math.max(...talks.map((x) => x.e)) / 60);
  const top = startH * 60;
  const height = (endH - startH) * 60 * CAL_PX_PER_MIN + CAL_PAD * 2;
  const y = (min) => (min - top) * CAL_PX_PER_MIN + CAL_PAD;

  const dates = [...new Set(talks.map((x) => x.t.date))].sort();
  let lines = "";
  for (let h = startH; h <= endH; h++) {
    lines += `<div class="cal-line" style="top:${y(h * 60)}px"></div>`;
    if (h < endH) lines += `<div class="cal-line half" style="top:${y(h * 60 + 30)}px"></div>`;
  }
  const hours = [];
  for (let h = startH; h <= endH; h++) hours.push(`<div class="cal-hour" style="top:${y(h * 60)}px">${hourLabel(h)}</div>`);

  const [nowDate, nowTime] = String(clockNow || "").split("T");
  const nowMin = minutesOfDay(nowTime);

  const heads = dates.map((d) => {
    const day = (talks.find((x) => x.t.date === d) || {}).t.day || "";
    return `<div class="cal-dayhead">${escapeHtml(day)}<span class="muted">${escapeHtml(dateLabel(d))}</span></div>`;
  }).join("");
  const cols = dates.map((d) => {
    const evs = layoutDay(talks.filter((x) => x.t.date === d)).map((ev) => {
      const t = ev.t;
      const isSaved = saved.has(t.code);
      const prepFor = !isSaved ? prep.get(t.code) : null;
      const w = 100 / ev.tracks;
      const h = Math.max((ev.e - ev.s) * CAL_PX_PER_MIN - 2, 16);
      const tip = `${t.title}\n${formatTime(t.start)}–${formatTime(t.end)} · ${t.room || ""}${prepFor ? `\nPrepares you for: ${prepFor.join("; ")}` : ""}`;
      const cls = ["ev", levelClass(t.level_num), isSaved ? "saved" : "", prepFor ? "prep" : "", h < 40 ? "tiny" : ""].join(" ");
      return `<a class="${cls}" href="${escapeHtml(talkHref(t.code))}" title="${escapeHtml(tip)}"
          style="top:${y(ev.s)}px;height:${h}px;left:calc(${ev.track * w}% + 2px);width:calc(${w * ev.span}% - 4px)">
        <span class="ev-time">${escapeHtml(formatTime(t.start))}</span>
        <span class="ev-title">${escapeHtml(shortTitle(t.title, 60))}</span>
        ${isSaved ? `<span class="ev-tag">Saved</span>` : prepFor ? `<span class="ev-tag">Prep</span>` : ""}
        <span class="ev-room">${escapeHtml(t.room || "")}</span>
      </a>`;
    }).join("");
    const now = d === nowDate && nowMin !== null && nowMin >= top && nowMin <= endH * 60
      ? `<div class="cal-now" style="top:${y(nowMin)}px"><span>Now ${escapeHtml(formatTime(nowTime))}</span></div>` : "";
    return `<div class="cal-col" style="height:${height}px">${lines}${evs}${now}</div>`;
  }).join("");

  body.innerHTML = `<div class="cal-grid ${saved.size || prep.size ? "cal-dim" : ""}" style="grid-template-columns:64px repeat(${dates.length}, minmax(0, 1fr))">
      <div class="cal-dayhead"></div>${heads}
      <div class="cal-hours" style="height:${height}px">${hours.join("")}</div>${cols}
    </div>`;
}

function wireCalendar() {
  const dlg = document.getElementById("calendar");
  document.getElementById("open-calendar").addEventListener("click", openCalendar);
  dlg.addEventListener("click", (e) => {
    if (e.target.closest("[data-close]")) closeDialog(dlg);
  });
  dlg.addEventListener("close", onCalendarClosed);
  window.addEventListener("hashchange", () => {
    if (location.hash === "#calendar") openCalendar();
    else if (dlg.open) closeDialog(dlg);
  });
}

// ---- chat highlight on the flow graph ---------------------------------------------

function cleanCodes(codes) {
  return Array.isArray(codes) ? [...new Set(codes.map((c) => String(c || "").trim()).filter(Boolean))].slice(0, 40) : [];
}

// Zoom so the picked talks fill the canvas (capped so one talk doesn't fill the whole screen).
function fitTo(eles, animate = true) {
  if (!cy || eles.empty()) return;
  const bb = eles.boundingBox();
  const w = cy.width();
  const h = cy.height();
  const pad = 70;
  let zoom = Math.min((w - pad * 2) / Math.max(bb.w, 1), (h - pad * 2) / Math.max(bb.h, 1), 1.3);
  zoom = Math.max(0.2, zoom);
  // Centre a little low so the "Showing N talks" bar at the top doesn't cover them.
  const pan = { x: w / 2 - (bb.x1 + bb.w / 2) * zoom, y: h / 2 + 20 - (bb.y1 + bb.h / 2) * zoom };
  if (animate) cy.animate({ zoom, pan }, { duration: 450, easing: "ease-in-out-cubic" });
  else { cy.zoom(zoom); cy.pan(pan); }
}

function applyHighlight(codes, { animate = true } = {}) {
  const list = cleanCodes(codes);
  if (!list.length) return clearChatHighlight(false);
  activeHighlight = list;
  const bar = document.getElementById("flow-hl");
  const text = document.getElementById("flow-hl-text");
  bar.hidden = false;
  if (!cy) { text.textContent = `${plural(list.length, "talk", "talks")} picked in the chat`; return; }
  let picked = cy.collection();
  for (const code of list) {
    const n = cy.getElementById(code);
    if (n.nonempty() && n.hasClass("talk")) picked = picked.union(n);
  }
  cy.elements().removeClass("picked dimmed");
  const missing = list.length - picked.length;
  if (picked.empty()) {
    text.textContent = `The ${plural(list.length, "talk", "talks")} picked in the chat aren't on this map view`;
    return;
  }
  const links = picked.edgesWith(picked);
  talkNodes().not(picked).addClass("dimmed");
  cy.edges().not(links).addClass("dimmed");
  picked.addClass("picked");
  links.addClass("picked");
  text.textContent = `Showing ${plural(picked.length, "talk", "talks")} from the chat${missing > 0 ? ` · ${missing} more aren't drawn on this map` : ""}`;
  fitTo(picked, animate);
}

function clearChatHighlight(refit = true) {
  activeHighlight = null;
  document.getElementById("flow-hl").hidden = true;
  if (!cy) return;
  cy.elements().removeClass("picked dimmed");
  if (refit) fitWidth(true);
}

// ---- landing chat ---------------------------------------------------------------------

let chatBusy = false;
let talkIndex = null; // code -> talk, for cards rebuilt from stored messages

function chatLog() {
  return document.getElementById("chat-log");
}

function scrollChat() {
  const log = chatLog();
  log.scrollTop = log.scrollHeight;
}

function addChat(cls, html) {
  const div = document.createElement("div");
  div.className = `msg ${cls}`;
  div.innerHTML = html;
  chatLog().appendChild(div);
  scrollChat();
  return div;
}

function showExamples(show) {
  document.getElementById("chat-examples").hidden = !show;
}

function lookupTalk(code) {
  if (!talkIndex && Array.isArray(allTalks)) talkIndex = new Map(allTalks.map((t) => [t.code, t]));
  const fromFlow = flowData && Array.isArray(flowData.nodes) ? flowData.nodes.find((n) => n.code === code) : null;
  return (talkIndex && talkIndex.get(code)) || fromFlow || null;
}

function isSaved(code) {
  return me.targets.some((t) => t && t.code === code);
}

function suggestionCards(sugs) {
  const list = (Array.isArray(sugs) ? sugs : []).filter((s) => s && s.code).slice(0, 8);
  if (!list.length) return "";
  return `<div class="sugs">${list.map((s) => {
    const when = [dayShort(s.day), s.start ? `${formatTime(s.start)}${s.end ? `–${formatTime(s.end)}` : ""}` : ""].filter(Boolean).join(" ");
    const meta = [when, s.room].filter(Boolean).join(" · ");
    const saved = isSaved(s.code);
    return `<div class="sug">
      <a class="sug-title" href="${escapeHtml(talkHref(s.code))}">${escapeHtml(s.title || s.code)}</a>
      <button type="button" class="sug-save${saved ? " saved" : ""}" data-save="${escapeHtml(s.code)}" ${saved ? "disabled" : ""}>${saved ? "Saved ✓" : "Save"}</button>
      <span class="sug-meta">${escapeHtml(meta)}${s.ready === true ? ` · <span class="pill ok">✓ Ready</span>` : ""}</span>
      ${s.reason ? `<span class="sug-reason">${escapeHtml(s.reason)}</span>` : ""}
    </div>`;
  }).join("")}</div>`;
}

function traceHtml(trace) {
  const steps = (Array.isArray(trace) ? trace : []).filter((s) => s && s.tool);
  if (!steps.length) return "";
  const queries = steps.reduce((n, s) => n + (Array.isArray(s.cypher) ? s.cypher.length : 0), 0);
  return `<details class="how">
    <summary>How I got this · ${plural(steps.length, "tool call", "tool calls")}, ${plural(queries, "Cypher query", "Cypher queries")}</summary>
    ${steps.map((step, i) => `
      <details class="step">
        <summary><span class="step-n">${i + 1}</span> <code>${escapeHtml(step.tool)}</code>
          <span class="muted">${escapeHtml(JSON.stringify(step.args ?? {}))}</span></summary>
        ${(Array.isArray(step.cypher) ? step.cypher : []).map((c) => `<pre class="cypher">${escapeHtml(c)}</pre>`).join("")}
        ${step.result !== undefined ? `<pre class="result">${escapeHtml(JSON.stringify(step.result, null, 2).slice(0, 4000))}</pre>` : ""}
      </details>`).join("")}
  </details>`;
}

function agentHtml(m) {
  const highlight = cleanCodes(m.highlight);
  let sugs = m.suggestions;
  if ((!Array.isArray(sugs) || !sugs.length) && highlight.length) {
    // Stored turns keep only the codes: rebuild plain cards from the schedule.
    sugs = highlight.map((code) => {
      const t = lookupTalk(code);
      return t ? { code, title: t.title, day: t.day, start: t.start, end: t.end, room: t.room } : null;
    }).filter(Boolean);
  }
  const actions = [];
  if (highlight.length) actions.push(`<button type="button" class="linkbtn" data-highlight="${escapeHtml(highlight.join(","))}">Show ${plural(highlight.length, "talk", "talks")} on the map</button>`);
  if (m.talk) actions.push(`<a class="linkbtn" href="${escapeHtml(talkHref(m.talk))}">Open the plan for this talk →</a>`);
  return `<p>${formatReply(m.content || "")}</p>
    ${suggestionCards(sugs)}
    ${actions.length ? `<div class="msg-actions">${actions.join("")}</div>` : ""}
    ${traceHtml(m.trace)}`;
}

function lockChat(busy) {
  const input = document.getElementById("chat-input");
  const send = document.getElementById("chat-send");
  input.disabled = busy;
  send.disabled = busy;
  send.textContent = busy ? "Working…" : "Send";
  document.querySelectorAll("#chat-examples .chip").forEach((b) => { b.disabled = busy; });
  if (!busy) input.focus();
}

async function loadChat() {
  if (!attendee) return;
  let data;
  try {
    data = await api(`/api/attendees/${encodeURIComponent(attendee)}/chat`);
  } catch { return; } // no stored chat (or the endpoint is missing): keep the intro
  const msgs = (data && Array.isArray(data.messages) ? data.messages : [])
    .filter((m) => m && (m.role === "user" || m.role === "assistant") && m.content);
  if (!msgs.length) return;
  showExamples(false);
  for (const m of msgs.slice(-30)) {
    if (m.role === "user") addChat("user", `<p>${escapeHtml(m.content)}</p>`);
    else addChat("agent", agentHtml(m));
  }
  // Talk-page turns are about one talk; only a landing-page answer lights up the map.
  const last = [...msgs].reverse().find((m) => m.role === "assistant" && m.page === "landing");
  if (last && cleanCodes(last.highlight).length) applyHighlight(last.highlight);
}

async function sendGoal(raw) {
  const message = String(raw || "").trim().slice(0, 2000);
  if (!message || chatBusy) return;
  if (!attendee) {
    addChat("agent error", "<p>Your session didn't start, so the assistant can't answer. Reload the page to try again.</p>");
    return;
  }
  chatBusy = true;
  lockChat(true);
  showExamples(false);
  document.getElementById("chat-input").value = "";
  addChat("user", `<p>${escapeHtml(message)}</p>`);
  const pending = addChat("agent pending", `<span class="spinner"></span><span>Checking the graph… <span class="elapsed"></span></span>`);
  const started = Date.now();
  const tick = setInterval(() => {
    const el = pending.querySelector(".elapsed");
    if (el) el.textContent = `${Math.round((Date.now() - started) / 1000)} s`;
  }, 1000);
  try {
    const turn = await api("/api/agent", {
      method: "POST",
      body: JSON.stringify({ attendee, message, page: "landing" }),
    });
    clearInterval(tick);
    const highlight = cleanCodes(turn && turn.highlight);
    const view = (turn && turn.view) || {};
    // Saved talks or profile changes show up in the header and the ✓ marks on the flow.
    await loadAttendee().catch(() => {});
    pending.className = "msg agent";
    pending.innerHTML = agentHtml({
      content: (turn && turn.reply) || "", suggestions: turn && turn.suggestions, highlight,
      trace: turn && turn.trace, talk: view.talk,
    });
    // Show the start of the answer, not its end.
    chatLog().scrollTop = Math.max(0, pending.offsetTop - chatLog().offsetTop - 8);
    activeHighlight = highlight.length ? highlight : activeHighlight;
    await Promise.allSettled([loadFlow(), loadFeatured()]);
    if (highlight.length) applyHighlight(highlight);
  } catch (err) {
    clearInterval(tick);
    pending.className = "msg agent error";
    pending.innerHTML = `<p>${err.status === 404
      ? "The assistant isn't available on the landing page yet. Try again in a few minutes."
      : `The assistant couldn't answer: ${escapeHtml(err.message)}. Try again, or plan a talk directly on the <a href="/talk.html">attendee page</a>.`}</p>`;
  } finally {
    chatBusy = false;
    lockChat(false);
  }
}

async function saveSuggestion(btn) {
  const code = btn.dataset.save;
  if (!code || !attendee) return;
  btn.disabled = true;
  btn.textContent = "Saving…";
  try {
    const res = await api(`/api/attendees/${encodeURIComponent(attendee)}/targets`, { method: "POST", body: JSON.stringify({ talk: code }) });
    if (res && Array.isArray(res.targets)) me.targets = res.targets;
    else await loadAttendee().catch(() => {});
    document.querySelectorAll(`[data-save="${CSS.escape(code)}"]`).forEach((b) => {
      b.disabled = true; b.textContent = "Saved ✓"; b.classList.add("saved");
    });
    renderProfileButton();
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "Retry save";
    btn.title = `Couldn't save: ${err.message}`;
  }
}

function wireChat() {
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  form.addEventListener("submit", (e) => { e.preventDefault(); sendGoal(input.value); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendGoal(input.value); }
  });
  document.getElementById("chat").addEventListener("click", (e) => {
    const chip = e.target.closest("[data-goal]");
    if (chip && !chip.disabled) return sendGoal(chip.dataset.goal);
    const save = e.target.closest("[data-save]");
    if (save && !save.disabled) return saveSuggestion(save);
    const hl = e.target.closest("[data-highlight]");
    if (hl) applyHighlight(hl.dataset.highlight.split(","));
  });
  document.getElementById("flow-hl-clear").addEventListener("click", () => clearChatHighlight(true));
  // "toggle" doesn't bubble: listen in the capture phase so opened traces scroll into view.
  chatLog().addEventListener("toggle", (e) => {
    if (e.target.open && e.target.matches("details")) e.target.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, true);
}

// ---- conferences ----------------------------------------------------------------------

function confLine(c) {
  return [c && c.name, c && c.dates, c && c.location].filter(Boolean).join(" · ");
}

function renderConfLabel() {
  const label = document.getElementById("conf-label");
  const btn = document.getElementById("conf-picker");
  const cur = conferences && conferences.current;
  if (cur && cur.name) {
    label.textContent = confLine(cur);
    btn.disabled = false;
    btn.title = "Conferences in Throughline, and conferences near you";
    document.title = `Throughline · ${cur.name}`;
  } else {
    label.textContent = clockConference || " ";
    btn.disabled = true;
    btn.title = "";
  }
}

let confRetry = null;
async function loadConferences() {
  try {
    conferences = await api("/api/conferences");
  } catch (err) {
    conferences = null;
    if (err.status === 404 && !confRetry) confRetry = setTimeout(() => { confRetry = null; loadConferences(); }, 20000);
  }
  renderConfLabel();
}

function openDialog(dlg) {
  if (dlg.open) return;
  if (typeof dlg.showModal === "function") dlg.showModal();
  else dlg.setAttribute("open", "");
}

function renderLoadedConferences() {
  const box = document.getElementById("cf-loaded");
  const cur = conferences && conferences.current;
  if (!cur) {
    box.innerHTML = `<p class="muted">The conference list isn't available yet.</p>`;
    return;
  }
  const loaded = Array.isArray(conferences.loaded) && conferences.loaded.length ? conferences.loaded : [cur];
  box.innerHTML = `<h3>In Throughline now</h3>
    <div class="cf-results">${loaded.filter(Boolean).map((c) => {
      const isCur = c.id === cur.id;
      const facts = [c.dates, c.location, Number(c.talks) > 0 ? plural(Number(c.talks), "talk", "talks") : ""].filter(Boolean).join(" · ");
      return `<div class="cf-item${isCur ? " current" : ""}">
        <span class="cf-name">${escapeHtml(c.name || c.id || "Conference")}</span>
        <button type="button" class="pill ok cf-badge" data-to-map>${isCur ? "You're here · " : ""}Readiness map ready</button>
        <span class="cf-facts">${escapeHtml(facts)}</span>
      </div>`;
    }).join("")}</div>`;
}

function openConferences(focusNear = false) {
  const dlg = document.getElementById("conferences");
  clearHighlight();
  renderLoadedConferences();
  const input = document.getElementById("cf-place");
  if (!input.value) input.value = storageGet(PLACE_KEY) || "";
  openDialog(dlg);
  if (focusNear) {
    document.getElementById("cf-near").scrollIntoView({ block: "nearest" });
    input.focus();
  }
}

function formatSearchedAt(value) {
  if (!value) return "";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

let nearbyBusy = false;
function setNearbyBusy(busy) {
  nearbyBusy = busy;
  document.getElementById("cf-locate").disabled = busy;
  document.querySelector("#cf-form button").disabled = busy;
}

function nearbyState(html, isError = false) {
  document.getElementById("cf-results").innerHTML = `<div class="cf-state${isError ? " error" : ""}">${html}</div>`;
}

async function searchNearby(query, label) {
  if (nearbyBusy) return;
  setNearbyBusy(true);
  const started = Date.now();
  nearbyState(`<span class="spinner"></span><span>Searching the live web for conferences near ${escapeHtml(label)}… <b class="cf-elapsed">0 s</b><br><span class="muted">This usually takes 10–40 seconds.</span></span>`);
  const tick = setInterval(() => {
    const el = document.querySelector("#cf-results .cf-elapsed");
    if (el) el.textContent = `${Math.round((Date.now() - started) / 1000)} s`;
  }, 1000);
  const ctrl = typeof AbortController === "function" ? new AbortController() : null;
  const timeout = ctrl ? setTimeout(() => ctrl.abort(), 90000) : null;
  try {
    const data = await api(`/api/conferences/nearby?${query}`, ctrl ? { signal: ctrl.signal } : {});
    renderNearby(data || {});
  } catch (err) {
    if (err.name === "AbortError") nearbyState("The search took too long. Try again, or try a bigger city nearby.", true);
    else if (err.status === 404) nearbyState("Conference search isn't available yet. Try again in a few minutes.", true);
    else nearbyState(`Couldn't search: ${escapeHtml(err.message)}`, true);
  } finally {
    clearInterval(tick);
    if (timeout) clearTimeout(timeout);
    setNearbyBusy(false);
  }
}

function renderNearby(data) {
  const list = (Array.isArray(data.conferences) ? data.conferences : []).filter((c) => c && c.name);
  const place = data.place ? String(data.place) : "";
  if (place) storageSet(PLACE_KEY, place.slice(0, 80));
  const meta = [
    `${plural(list.length, "conference", "conferences")}${place ? ` near <strong>${escapeHtml(place)}</strong>` : ""}`,
    "found via live web search",
    data.searched_at ? `searched ${escapeHtml(formatSearchedAt(data.searched_at))}` : "",
  ].filter(Boolean).join(" · ");
  const parts = [`<div class="cf-meta">${meta}</div>`];
  if (data.error) parts.push(`<div class="cf-state error">${escapeHtml(data.error)}</div>`);
  if (!list.length) {
    parts.push(`<div class="cf-state">No upcoming conferences turned up${place ? ` near ${escapeHtml(place)}` : ""}. Try a bigger city nearby.</div>`);
  }
  for (const c of list.slice(0, 20)) {
    const badge = c.loaded
      ? `<button type="button" class="pill ok cf-badge" data-to-map>Readiness map ready</button>`
      : `<span class="pill plain cf-badge">Map not loaded yet</span>`;
    const href = safeUrl(c.url);
    parts.push(`<div class="cf-item">
      <span class="cf-name">${escapeHtml(c.name)}</span>
      ${badge}
      <span class="cf-facts">${escapeHtml([c.dates, c.location].filter(Boolean).join(" · "))}
        ${href !== "#" ? ` · <a class="cf-link" href="${href}" target="_blank" rel="noopener noreferrer">Website ↗</a>` : ""}</span>
      ${c.snippet ? `<span class="cf-snippet">${escapeHtml(c.snippet)}</span>` : ""}
    </div>`);
  }
  document.getElementById("cf-results").innerHTML = parts.join("");
}

function locateMe() {
  if (nearbyBusy) return;
  const input = document.getElementById("cf-place");
  if (!navigator.geolocation) {
    nearbyState("Your browser can't share a location here. Type a city instead.");
    input.focus();
    return;
  }
  nearbyState(`<span class="spinner"></span><span>Asking your browser for your location…</span>`);
  navigator.geolocation.getCurrentPosition((pos) => {
    // Rounded to about a kilometre, sent only with this one search, never stored.
    const lat = pos.coords.latitude.toFixed(2);
    const lon = pos.coords.longitude.toFixed(2);
    searchNearby(`lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}`, "you");
  }, (err) => {
    nearbyState(`${err && err.code === 1 ? "Location access was turned down." : "Couldn't get your location."} Type a city instead.`);
    input.focus();
  }, { enableHighAccuracy: false, timeout: 12000, maximumAge: 600000 });
}

function wireConferences() {
  const dlg = document.getElementById("conferences");
  document.getElementById("conf-picker").addEventListener("click", () => openConferences(false));
  document.getElementById("open-nearby").addEventListener("click", () => openConferences(true));
  document.getElementById("cf-locate").addEventListener("click", locateMe);
  document.getElementById("cf-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const place = document.getElementById("cf-place").value.trim().slice(0, 80);
    if (!place) { document.getElementById("cf-place").focus(); return; }
    searchNearby(`place=${encodeURIComponent(place)}`, place);
  });
  dlg.addEventListener("click", (e) => {
    if (e.target === dlg || e.target.closest("[data-close]")) return closeDialog(dlg);
    if (e.target.closest("[data-to-map]")) {
      closeDialog(dlg);
      document.getElementById("flow-wrap").scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  });
}

// ---- start --------------------------------------------------------------------------

async function init() {
  wireProfile();
  wireFlow();
  wireCalendar();
  wireChat();
  wireConferences();
  const clock = api("/api/clock").then((c) => {
    clockNow = c && c.now;
    clockConference = (c && c.conference) || "";
    if (!conferences) renderConfLabel();
  }).catch(() => {});
  loadConferences();
  api("/api/health").then((h) => {
    document.getElementById("status").textContent =
      `${h.talks} talks · knowledge graph “${h.graph}” on ${h.backend}`;
  }).catch(() => {});
  const talks = api("/api/talks").then((t) => { allTalks = t; }).catch(() => {});
  try {
    await startAttendee();
  } catch (err) {
    attendee = null;
    document.getElementById("profile-label").textContent = "Profile unavailable";
    document.getElementById("status").textContent = `Couldn't start your session: ${err.message}`;
  }
  await Promise.allSettled([loadFlow(), loadFeatured(), talks, clock]);
  await loadChat();
  if (location.hash === "#calendar") openCalendar();
}

init();
