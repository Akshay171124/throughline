const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const CODE_KEY = "throughline.attendee";
const TALK_KEY = "throughline.talk";
const AUTO_ALTS_MAX_NODES = 12; // show faded alternatives by default only on small graphs

let allTalks = [];
let attendee = null;
const SKIP_KEY = "throughline.profile-skipped";

// The attendee's own record. `null` fields mean the server doesn't offer that feature (yet).
const me = {
  profile: null,        // {role, experience, interests, updated_at} or {}
  targets: null,        // saved talks [{code, title, day, start, end, room}]
  readiness: new Map(), // talk code -> plan result (for "Ready" / "N steps to go")
  readinessTurn: 0,
  chatApi: false,
  concepts: null,       // GET /api/concepts, loaded when the profile opens
};
const EXPERIENCE = { new: "New to this", some: "Some experience", experienced: "Experienced" };
let introHtml = "";   // the greeting in the chat, restored when the chat is cleared

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
  me.profile = state.profile && typeof state.profile === "object" ? state.profile : null;
  me.targets = Array.isArray(state.targets) ? state.targets : null;
  renderProfileSummary();
  renderMyTalks();
  refreshReadiness();
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

// ---- profile, saved talks and chat memory ------------------------------------

function isSaved(code) {
  return Boolean(me.targets && me.targets.some((t) => t.code === code));
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

function renderProfileSummary() {
  const entry = document.getElementById("profile-entry");
  entry.hidden = me.profile === null && me.targets === null;
  document.getElementById("profile-btn").textContent = profileSummary(me.profile) || (profileIsSet(me.profile) ? "Edit profile" : "Set up profile");
}

// Saved talks in schedule order.
function sortedTargets() {
  const order = (t) => { const full = findTalk(t.code); return full ? Number(full.start_min) || 0 : 0; };
  return [...(me.targets || [])].sort((a, b) => order(a) - order(b));
}

function readinessPill(code) {
  const plan = me.readiness.get(code);
  if (!plan) return `<span class="pill muted-pill">…</span>`;
  if (plan.error) return `<span class="pill muted-pill">?</span>`;
  if (plan.ready || !(plan.plan || []).length) return `<span class="pill ok">✓ Ready</span>`;
  return `<span class="pill">${plural(plan.plan.length, "step", "steps")} to go</span>`;
}

function myTalksItems() {
  return sortedTargets().map((t) => {
    const full = findTalk(t.code) || t;
    const current = t.code === view.talk ? " current" : "";
    return `<li><button class="mytalk${current}" data-mytalk="${escapeHtml(t.code)}" title="Show the path to this talk">
        <span class="mytalk-when">${escapeHtml(dayShort(full.day))} ${formatTime(full.start)}</span>
        <span class="mytalk-title">${escapeHtml(shortTitle(full.title || t.title, 60))}</span>
        ${readinessPill(t.code)}
      </button></li>`;
  }).join("");
}

function renderMyTalks() {
  const box = document.getElementById("mytalks");
  if (!me.targets || !me.targets.length) { box.hidden = true; box.innerHTML = ""; }
  else {
    box.hidden = false;
    box.innerHTML = `<h2 class="day">My talks <span class="count">${me.targets.length}</span></h2><ul class="mytalk-list">${myTalksItems()}</ul>`;
  }
  const inDialog = document.getElementById("mytalks-dialog");
  if (inDialog) inDialog.innerHTML = myTalksDialogHtml();
}

function myTalksDialogHtml() {
  if (!me.targets || !me.targets.length) {
    return `<p class="muted">None yet. Use “☆ Save” on a talk to keep it here and see how ready you are.</p>`;
  }
  return `<ul class="mytalk-list">${myTalksItems()}</ul>`;
}

// Fetch the plan for each saved talk to show how close the attendee is.
async function refreshReadiness() {
  const targets = me.targets || [];
  const turn = ++me.readinessTurn;
  if (!targets.length || !attendee) return;
  const q = `?attendee=${encodeURIComponent(attendee)}`;
  await Promise.all(targets.map(async (t) => {
    let plan;
    try { plan = await api(`/api/plan/${encodeURIComponent(t.code)}${q}`); } catch { plan = { error: true }; }
    if (turn !== me.readinessTurn) return;
    me.readiness.set(t.code, plan);
  }));
  if (turn === me.readinessTurn) renderMyTalks();
}

async function toggleTarget(code) {
  if (me.targets === null) return;
  const saved = isSaved(code);
  const base = `/api/attendees/${encodeURIComponent(attendee)}/targets`;
  try {
    const result = saved
      ? await api(`${base}/${encodeURIComponent(code)}`, { method: "DELETE" })
      : await api(base, { method: "POST", body: JSON.stringify({ talk: code }) });
    me.targets = Array.isArray(result.targets) ? result.targets : me.targets;
  } catch (err) {
    addMessage("agent card", `<p class="error">Couldn't ${saved ? "unsave" : "save"} that talk: ${escapeHtml(err.message)}</p>`);
    return;
  }
  if (view.talk === code && view.plan) me.readiness.set(code, view.plan);
  renderMyTalks();
  renderTalks(currentTalkList());
  if (view.plan) renderHead(true);
  refreshReadiness();
}

function saveButton(code, cls = "save-btn") {
  if (me.targets === null) return "";
  const saved = isSaved(code);
  return `<button class="${cls}${saved ? " saved" : ""}" data-save="${escapeHtml(code)}" aria-pressed="${saved}"
    title="${saved ? "Remove from My talks" : "Keep this talk in My talks"}">${saved ? "★ Saved" : "☆ Save"}</button>`;
}

// The talk on screen is remembered per attendee code, so a refresh reopens it.
function rememberTalk(code) {
  storageSet(TALK_KEY, code ? JSON.stringify({ attendee, talk: code }) : null);
}

// The talk on screen is also in the address bar (?code=TALKCODE), so a refresh or a shared link
// opens the same talk. The landing page links here the same way.
function linkedTalk() {
  try {
    const code = (new URLSearchParams(window.location.search).get("code") || "").trim().toUpperCase();
    return code && findTalk(code) ? code : null; // unknown codes are ignored
  } catch {
    return null;
  }
}

function syncUrl(code) {
  try {
    const url = new URL(window.location.href);
    if (code) url.searchParams.set("code", code);
    else url.searchParams.delete("code");
    if (url.href !== window.location.href) history.replaceState(history.state, "", url);
  } catch { /* old browsers: the address bar just doesn't follow */ }
}

function rememberedTalk() {
  const raw = storageGet(TALK_KEY);
  if (!raw) return null;
  try {
    const v = JSON.parse(raw);
    return v && v.attendee === attendee && typeof v.talk === "string" ? v.talk : null;
  } catch {
    return raw; // the older format: a bare talk code
  }
}

function resetChat() {
  document.getElementById("messages").innerHTML = introHtml;
}

// Render the stored conversation; returns the talk of the last assistant reply, if any.
async function loadChat() {
  resetChat();
  let messages;
  try {
    messages = (await api(`/api/attendees/${encodeURIComponent(attendee)}/chat`)).messages;
    me.chatApi = Array.isArray(messages);
  } catch {
    me.chatApi = false;
  }
  document.getElementById("chat-bar").hidden = !me.chatApi;
  if (!me.chatApi) return null;
  let lastTalk = null;
  for (const m of messages) {
    if (m.role === "user") addMessage("user", `<p>${escapeHtml(m.content)}</p>`);
    else if (m.role === "assistant") {
      addMessage("agent", `<p>${formatReply(m.content || "")}</p>`);
      lastTalk = m.talk || null;
    }
  }
  return lastTalk;
}

async function clearChat() {
  if (!confirm("Clear this conversation? Your profile, saved talks and what you know stay.")) return;
  try {
    await api(`/api/attendees/${encodeURIComponent(attendee)}/chat`, { method: "DELETE" });
    resetChat();
  } catch (err) {
    addMessage("agent card", `<p class="error">Couldn't clear the chat: ${escapeHtml(err.message)}</p>`);
  }
}

function skippedProfile() {
  return storageGet(SKIP_KEY) === attendee;
}

function maybePromptProfile() {
  document.querySelectorAll(".profile-prompt").forEach((el) => el.remove());
  if (me.profile === null || profileIsSet(me.profile) || skippedProfile()) return;
  addMessage("agent card profile-prompt", `<p><strong>New here?</strong> Tell me your role and what you already know, and I'll skip the basics you don't need.</p>
    <div class="dialog-actions"><button class="primary small-btn" data-prompt="open">Set up my profile</button>
    <button class="link" data-prompt="skip">Not now</button></div>`);
}

// Back to the empty right-hand panel (after "Forget me").
function resetTalkView() {
  view.version++;
  view.talk = null; view.plan = null; view.graph = null; view.showAlts = null; view.wasReady = null;
  destroyGraph();
  document.getElementById("graph").hidden = true;
  document.getElementById("path").innerHTML = "";
  document.getElementById("dayplan").innerHTML = "";
  document.getElementById("legend").hidden = true;
  document.getElementById("toggle-alts").hidden = true;
  document.getElementById("graph-wrap").classList.remove("loading");
  document.getElementById("trace").innerHTML = `<p class="muted pad">Nothing yet. Ask the agent, or use “Plan without AI” on a talk.</p>`;
  document.getElementById("how-count").textContent = "";
  rememberTalk(null);
  syncUrl(null);
  renderHead(false);
  hideAbout();
}

// ---- the profile dialog --------------------------------------------------------

const profileDraft = { interests: [], knownDirty: false };

async function openProfile() {
  const dlg = document.getElementById("profile");
  const p = me.profile || {};
  profileDraft.interests = [...(p.interests || [])];
  profileDraft.knownDirty = false;
  const exp = ["", "new", "some", "experienced"].map((v) => `
    <label class="seg"><input type="radio" name="experience" value="${v}" ${(p.experience || "") === v ? "checked" : ""}>
      <span>${v ? escapeHtml(EXPERIENCE[v]) : "Not saying"}</span></label>`).join("");
  document.getElementById("profile-body").innerHTML = `
    <span class="label">Your profile · ${escapeHtml(attendee)}</span>
    <h2>About you</h2>
    ${me.profile === null ? "" : `
    <form id="profile-form" class="profile-form">
      <label class="field"><span>Role</span>
        <input id="pf-role" list="role-options" maxlength="60" placeholder="e.g. Developer" value="${escapeHtml(p.role || "")}"></label>
      <fieldset class="field"><legend>Experience</legend><div class="segs">${exp}</div></fieldset>
      <div class="field"><span>Interests</span>
        <div class="tags" id="pf-tags"></div>
        <input id="pf-interest" maxlength="40" placeholder="Type a topic, press Enter (e.g. agents, security)"></div>
      <div class="dialog-actions"><button class="primary" type="submit">Save profile</button><span id="pf-status" class="muted" role="status"></span></div>
    </form>`}
    ${me.targets === null ? "" : `<h3>My talks</h3><div id="mytalks-dialog">${myTalksDialogHtml()}</div>`}
    <div id="known-section"><h3>Concepts I already know</h3><p class="muted">Loading concepts…</p></div>`;
  renderTags();
  if (!dlg.open) {
    if (typeof dlg.showModal === "function") dlg.showModal();
    else dlg.setAttribute("open", "");
  }
  renderKnownSection();
}

function closeProfile() {
  const dlg = document.getElementById("profile");
  if (dlg.open) { if (typeof dlg.close === "function") dlg.close(); else { dlg.removeAttribute("open"); onProfileClosed(); } }
}

function onProfileClosed() {
  if (profileDraft.knownDirty) {
    profileDraft.knownDirty = false;
    refreshAll().catch(() => {});
  }
}

function renderTags() {
  const box = document.getElementById("pf-tags");
  if (!box) return;
  box.innerHTML = profileDraft.interests.map((t, i) =>
    `<span class="tag">${escapeHtml(t)}<button type="button" data-untag="${i}" aria-label="Remove ${escapeHtml(t)}">×</button></span>`).join("");
}

function addInterest(raw) {
  for (const part of String(raw).split(",")) {
    const tag = part.trim().slice(0, 40);
    if (tag && !profileDraft.interests.some((x) => x.toLowerCase() === tag.toLowerCase()) && profileDraft.interests.length < 12) {
      profileDraft.interests.push(tag);
    }
  }
  renderTags();
}

async function renderKnownSection() {
  const box = document.getElementById("known-section");
  if (!me.concepts) {
    try {
      const list = await api("/api/concepts");
      me.concepts = Array.isArray(list) ? [...list].sort((a, b) => String(a.name).localeCompare(String(b.name))) : null;
    } catch { me.concepts = null; }
  }
  if (!box || !box.isConnected) return;
  if (!me.concepts) { box.hidden = true; return; }
  const known = new Set(view.known.map((k) => k.concept));
  const how = new Map(view.known.map((k) => [k.concept, k.how]));
  box.hidden = false;
  box.innerHTML = `<h3>Concepts I already know <span class="muted" id="known-count">${known.size} of ${me.concepts.length}</span></h3>
    <p class="muted small">Ticked concepts come off every path. Untick one to learn it again.</p>
    <input id="concept-search" type="search" placeholder="Search concepts…" autocomplete="off">
    <div class="concept-list" id="concept-list">${me.concepts.map((c) => `
      <label class="concept-row" data-name="${escapeHtml(String(c.name).toLowerCase())}" title="${escapeHtml(c.definition || "")}">
        <input type="checkbox" data-concept="${escapeHtml(c.id)}" ${known.has(c.id) ? "checked" : ""}>
        <span class="concept-name">${escapeHtml(c.name)}</span>
        ${how.get(c.id) === "attended" ? `<span class="muted small">from a talk</span>` : ""}
      </label>`).join("")}</div>`;
}

async function toggleKnown(box) {
  const concept = box.dataset.concept;
  const want = box.checked;
  const base = `/api/attendees/${encodeURIComponent(attendee)}/known`;
  box.disabled = true;
  try {
    if (want) await api(base, { method: "POST", body: JSON.stringify({ concept }) });
    else await api(`${base}/${encodeURIComponent(concept)}`, { method: "DELETE" });
    const c = (me.concepts || []).find((x) => x.id === concept);
    view.known = want
      ? [...view.known.filter((k) => k.concept !== concept), { concept, name: c ? c.name : concept, how: "told" }]
      : view.known.filter((k) => k.concept !== concept);
    profileDraft.knownDirty = true;
    const count = document.getElementById("known-count");
    if (count) count.textContent = `${view.known.length} of ${(me.concepts || []).length}`;
  } catch (err) {
    box.checked = !want;
    alert(`Couldn't save that: ${err.message}`);
  } finally {
    box.disabled = false;
  }
}

async function saveProfile() {
  const status = document.getElementById("pf-status");
  const pending = document.getElementById("pf-interest");
  if (pending && pending.value.trim()) { addInterest(pending.value); pending.value = ""; }
  const checked = document.querySelector('#profile-form input[name="experience"]:checked');
  const body = {
    role: document.getElementById("pf-role").value.trim(),
    experience: checked ? checked.value : "",
    interests: profileDraft.interests,
  };
  status.textContent = "Saving…";
  try {
    const result = await api(`/api/attendees/${encodeURIComponent(attendee)}/profile`, { method: "PUT", body: JSON.stringify(body) });
    me.profile = result.profile || { ...body, updated_at: "now" };
    renderProfileSummary();
    maybePromptProfile();
    status.textContent = "Saved ✓";
  } catch (err) {
    status.textContent = `Couldn't save: ${err.message}`;
  }
}

function wireProfile() {
  const dlg = document.getElementById("profile");
  document.getElementById("profile-btn").addEventListener("click", openProfile);
  dlg.addEventListener("close", onProfileClosed);
  dlg.addEventListener("click", (e) => {
    if (e.target === dlg || e.target.closest("[data-close]")) return closeProfile();
    const untag = e.target.closest("[data-untag]");
    if (untag) { profileDraft.interests.splice(Number(untag.dataset.untag), 1); renderTags(); return; }
    const talk = e.target.closest("[data-mytalk]");
    if (talk) { closeProfile(); loadTalkView(talk.dataset.mytalk, { trace: true }).catch(() => {}); }
  });
  dlg.addEventListener("submit", (e) => { e.preventDefault(); saveProfile(); });
  dlg.addEventListener("keydown", (e) => {
    if (e.target.id !== "pf-interest") return;
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addInterest(e.target.value);
      e.target.value = "";
    } else if (e.key === "Backspace" && !e.target.value && profileDraft.interests.length) {
      profileDraft.interests.pop();
      renderTags();
    }
  });
  dlg.addEventListener("input", (e) => {
    if (e.target.id !== "concept-search") return;
    const q = e.target.value.trim().toLowerCase();
    dlg.querySelectorAll(".concept-row").forEach((row) => { row.hidden = Boolean(q) && !row.dataset.name.includes(q); });
  });
  dlg.addEventListener("change", (e) => {
    if (e.target.matches("input[data-concept]")) toggleKnown(e.target);
  });

  document.getElementById("mytalks").addEventListener("click", (e) => {
    const b = e.target.closest("[data-mytalk]");
    if (b) loadTalkView(b.dataset.mytalk, { trace: true }).catch(() => {});
  });
  document.getElementById("clear-chat").addEventListener("click", clearChat);
  document.getElementById("messages").addEventListener("click", (e) => {
    const b = e.target.closest("[data-prompt]");
    if (!b) return;
    if (b.dataset.prompt === "skip") storageSet(SKIP_KEY, attendee);
    document.querySelectorAll(".profile-prompt").forEach((el) => el.remove());
    if (b.dataset.prompt === "open") openProfile();
  });
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
    const saved = isSaved(t.code);
    if (saved) { classes.push("saved"); badge += `<span class="badge saved">★ Saved</span>`; }
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
            ${me.targets === null ? "" : `<button class="chip ghost" data-action="save">${saved ? "★ Saved" : "☆ Save"}</button>`}
          </span>
        </span>
      </div>`;
  }
  const box = document.getElementById("talks");
  const scroll = box.scrollTop;
  box.innerHTML = html || `<p class="muted pad">No talks match.</p>`;
  box.scrollTop = scroll;
}

// Bring the open talk into view in the schedule and flash it once, so arriving from the
// conference map (or a link) shows which talk you picked.
function revealTalk(code) {
  const row = document.querySelector(`#talks .talk[data-code="${CSS.escape(code)}"]`);
  if (!row) return; // hidden by the search filter
  const box = document.getElementById("talks");
  const rowBox = row.getBoundingClientRect();
  const listBox = box.getBoundingClientRect();
  box.scrollTop += rowBox.top - listBox.top - box.clientHeight / 2 + rowBox.height / 2;
  row.classList.remove("flash");
  void row.offsetWidth; // restart the animation if it's already running
  row.classList.add("flash");
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

// ---- "Why this answer?": the trace as plain steps (same code in app.js and landing.js) ----

// A concept id like "mcp-server" read as words, when no name is at hand.
function humanizeId(id) {
  return String(id ?? "").replace(/^concept:/, "").replace(/[-_]+/g, " ").trim();
}

function listWords(items, max = 4) {
  const list = [...new Set((items || []).map((x) => String(x ?? "").trim()).filter(Boolean))];
  if (list.length <= max) return list.join(", ");
  return `${list.slice(0, max).join(", ")} and ${list.length - max} more`;
}

// One plain sentence (or two) per tool call. `look` gives talk titles and concept names
// for codes and ids: { talk(code) -> title|null, concept(id) -> name|null }. Never raw JSON.
function whyLines(step, look) {
  const tool = String(step.tool || "").replace(/\s*\(no AI\)\s*$/, "");
  const noAI = /\(no AI\)\s*$/.test(String(step.tool || ""));
  const args = step.args && typeof step.args === "object" ? step.args : {};
  const r = step.result;
  const obj = r && typeof r === "object" && !Array.isArray(r) ? r : {};
  const failed = Boolean(obj.error);
  const talkName = (code, fallback) => (fallback || (code && look.talk(code)) || (code ? "that talk" : "the talk"));
  const conceptOf = (id) => (id && look.concept(id)) || humanizeId(id) || "that idea";
  switch (tool) {
    case "get_attendee": {
      if (failed) return ["Checked what you already know (nothing saved yet)"];
      const p = obj.profile || {};
      const bits = [];
      const who = [p.role, EXPERIENCE[p.experience]].filter(Boolean).join(" · ");
      if (who) bits.push(`your profile: ${who}`);
      const known = Array.isArray(obj.known) ? obj.known.length : 0;
      if (known) bits.push(`including ${plural(known, "concept", "concepts")} you know`);
      const went = Array.isArray(obj.attended_talks) ? obj.attended_talks.length : 0;
      if (went) bits.push(`${plural(went, "talk", "talks")} you attended`);
      return [`Checked what you already know${bits.length ? ` — ${bits.join(", ")}` : " (nothing saved yet)"}`];
    }
    case "update_profile": {
      const s = obj.saved && typeof obj.saved === "object" ? obj.saved : args;
      const parts = [s.role || args.role, EXPERIENCE[s.experience || args.experience]].filter(Boolean);
      const interests = Array.isArray(args.interests) && args.interests.length ? args.interests : s.interests;
      if (Array.isArray(interests) && interests.length) parts.push(`interested in ${listWords(interests)}`);
      return [`Saved what you told me${parts.length ? `: ${parts.join(", ")}` : ""}`];
    }
    case "list_concepts": {
      const n = Array.isArray(r) ? r.length : 0;
      // The trace keeps at most 25 rows, so a full list means "at least that many".
      return [n && n < 25 ? `Looked through the conference's ${n} topics` : "Looked through the conference's list of topics"];
    }
    case "talks_for_concepts": {
      if (failed) return ["Tried to match your goal to the conference's topics, but none fit"];
      const talks = Array.isArray(obj.talks) ? obj.talks : [];
      let names = talks.flatMap((t) => (Array.isArray(t.teaches) ? t.teaches : []));
      if (!names.length) names = (obj.concepts_used || args.concepts || []).map(conceptOf);
      return [
        `Matched your goal to: ${listWords(names, 5) || "the closest topics"}`,
        talks.length ? `Found ${plural(talks.length, "talk", "talks")} that teach ${names.length === 1 ? "it" : "them"}` : "Found no talks that teach them",
      ];
    }
    case "search_talks": {
      const hits = Array.isArray(r) ? r : [];
      if (!hits.length) return [`Searched the schedule for “${String(args.query || "").slice(0, 60)}” but found no match`];
      return [`Found the talk you meant: ${hits[0].title || talkName(hits[0].code)}`];
    }
    case "plan_day":
    case "get_learning_path": {
      if (failed) return ["Tried to follow the prerequisites in the graph, but couldn't find that talk"];
      const title = talkName(obj.talk || args.talk, obj.talk_title);
      const tail = noAI ? "; no AI involved" : "";
      if (obj.ready === true) return [`Followed the prerequisites in the graph for ${title}: nothing missing — you're ready${tail}`];
      const plan = Array.isArray(obj.plan) ? obj.plan : null;
      const n = plan ? plan.length : Array.isArray(obj.steps) ? obj.steps.length : Number(obj.steps) || 0;
      let detail = "";
      if (plan) {
        const atTalks = plan.filter((s) => s && s.learn_at && s.learn_at.kind === "talk").length;
        detail = ` (${atTalks} at earlier talks, ${plural(n - atTalks, "outside explainer", "outside explainers")})`;
      } else if (Number.isFinite(obj.at_talks)) {
        detail = ` (${obj.at_talks} at earlier talks, ${plural(n - obj.at_talks, "outside explainer", "outside explainers")})`;
      }
      const what = tool === "get_learning_path" ? plural(n, "thing", "things") + " to learn first" : plural(n, "step", "steps");
      return [`Followed the prerequisites in the graph for ${title}: ${what}${detail}${tail}`];
    }
    case "find_where_to_learn": {
      const hits = Array.isArray(r) ? r.length : 0;
      const before = args.before_talk ? `before ${talkName(args.before_talk)}` : "at the conference";
      return [`Looked for talks that teach ${conceptOf(args.concept)} ${before}: ${hits ? `found ${hits}` : "none fit"}`];
    }
    case "explain_step":
      if (failed) return [`Looked for the evidence for ${conceptOf(args.concept)}, but couldn't find that talk`];
      return [`Pulled the evidence for ${conceptOf(args.concept)}${obj.talk ? ` in ${obj.talk}` : ""}`];
    case "mark_attended": {
      const learned = (Array.isArray(obj.learned) ? obj.learned : []).map(conceptOf);
      return [`Marked ${talkName(args.talk)} as attended; you learned ${listWords(learned) || "nothing new"}${obj.clock ? `; the clock moved to ${obj.clock}` : ""}`];
    }
    case "mark_known":
      return [`Noted that you know ${conceptOf(args.concept || obj.known)}`];
    case "save_talk":
      return [`Saved ${talkName(args.talk || obj.saved)} to My talks`];
    case "run_cypher":
      return [failed ? "Tried to ask the graph a direct question, but it couldn't answer that" : "Asked the graph a direct question (read-only)"];
    default:
      return [failed ? "Looked something up in the graph, but it had no answer" : "Looked something up in the graph"];
  }
}

function whySteps(trace, look) {
  const lines = [];
  for (const step of trace) {
    for (const line of whyLines(step, look)) if (line !== lines[lines.length - 1]) lines.push(line);
  }
  return lines;
}

function whyStepsHtml(lines) {
  return `<ol class="why-steps">${lines.map((l) => `<li>${escapeHtml(l)}</li>`).join("")}</ol>
    <p class="why-note">Every step above is a query on the FalkorDB knowledge graph.</p>`;
}

function techStepsHtml(trace) {
  const queries = trace.reduce((n, s) => n + (Array.isArray(s.cypher) ? s.cypher.length : 0), 0);
  const label = queries ? `See the graph queries (${queries})` : `See the tool calls (${trace.length})`;
  return `<details class="why-tech">
    <summary>${escapeHtml(label)}</summary>
    ${trace.map((step, i) => `
      <details class="step">
        <summary><span class="step-n">${i + 1}</span> <code>${escapeHtml(step.tool)}</code>
          <span class="muted">${escapeHtml(JSON.stringify(step.args ?? {}))}</span></summary>
        ${(Array.isArray(step.cypher) ? step.cypher : []).map((c) => `<pre class="cypher">${escapeHtml(c)}</pre>`).join("")}
        ${step.result !== undefined ? `<pre class="result">${escapeHtml((JSON.stringify(step.result, null, 2) || "").slice(0, 4000))}</pre>` : ""}
      </details>`).join("")}
  </details>`;
}

// Concept names for the plain steps, fetched once (the same list the profile uses).
let conceptsLoading = null;
function loadConceptNames() {
  if (me.concepts) return Promise.resolve();
  conceptsLoading = conceptsLoading || api("/api/concepts").then((list) => {
    if (!me.concepts && Array.isArray(list)) me.concepts = [...list].sort((a, b) => String(a.name).localeCompare(String(b.name)));
  }).catch(() => {}).finally(() => { conceptsLoading = null; });
  return conceptsLoading;
}

let traceShown = null;
function renderTrace(trace) {
  traceShown = trace;
  if (!me.concepts) loadConceptNames().then(() => { if (me.concepts && traceShown === trace) renderTrace(trace); });
  const list = document.getElementById("trace");
  const count = document.getElementById("how-count");
  const steps = (Array.isArray(trace) ? trace : []).filter((s) => s && s.tool);
  if (!steps.length) {
    list.innerHTML = `<p class="muted pad">I answered from the conversation; no graph lookups were needed.</p>`;
    count.textContent = "";
    return;
  }
  const lines = whySteps(steps, {
    talk: (code) => { const t = findTalk(code); return t && t.title ? t.title : null; },
    concept: (id) => {
      const n = conceptName(id);
      if (n && n !== id) return n;
      const c = Array.isArray(me.concepts) ? me.concepts.find((x) => x && x.id === id) : null;
      return c && c.name ? c.name : null;
    },
  });
  openHow();
  count.textContent = `· ${plural(lines.length, "step", "steps")}`;
  list.innerHTML = whyStepsHtml(lines) + techStepsHtml(steps);
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
  const pending = addMessage("agent pending", `<p>Walking the graph<span class="dots"><span>.</span><span>.</span><span>.</span></span> <span class="muted elapsed"></span></p>`);
  // Show the wait, and give up after 90 s so a stuck request can't lock the chat on stage.
  const started = Date.now();
  const tick = setInterval(() => {
    const el = pending.querySelector(".elapsed");
    if (el) el.textContent = `${Math.round((Date.now() - started) / 1000)} s`;
  }, 1000);
  const abort = new AbortController();
  const timeout = setTimeout(() => abort.abort(), 90000);
  let turn = null;
  try {
    turn = await api("/api/agent", {
      method: "POST",
      body: JSON.stringify({ attendee, message }), // the server keeps the conversation
      signal: abort.signal,
    });
    pending.classList.remove("pending");
    pending.innerHTML = `<p>${formatReply(turn.reply || "")}</p>`;
  } catch (err) {
    pending.classList.remove("pending");
    const why = err.name === "AbortError" ? "it took too long" : err.message;
    pending.innerHTML = `<p class="error">The agent failed: ${escapeHtml(why)}. Use “Plan without AI” on the talk instead.</p>`;
  } finally {
    clearInterval(tick);
    clearTimeout(timeout);
    asking = false;
    setBusy(false);
  }
  if (!turn) return;
  // The answer is already on screen; a problem drawing the extras must not replace it.
  try {
    renderTrace(turn.trace || []);
    await refreshAttendee();
    const target = turn.view && turn.view.talk;
    if (target) await loadTalkView(target);
    else if (view.talk) await loadTalkView(view.talk);
  } catch { /* keep the answer; the panels refresh on the next action */ }
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
  if (!sameTalk) { wrap.classList.add("loading"); loadAbout(code).catch(() => {}); }
  try {
    const q = `?attendee=${encodeURIComponent(attendee)}`;
    const [plan, graph] = await Promise.all([
      api(`/api/plan/${encodeURIComponent(code)}${q}`),
      api(`/api/graph/${encodeURIComponent(code)}${q}`),
    ]);
    if (version !== view.version) return null; // a newer request won
    if (!sameTalk) { view.showAlts = null; view.wasReady = null; }
    if (sameTalk) loadAbout(code).catch(() => {}); // retries only if it wasn't ready yet
    view.talk = code;
    view.plan = plan;
    view.graph = graph;
    rememberTalk(code);
    syncUrl(code);
    if (isSaved(code)) me.readiness.set(code, plan);
    renderHead(sameTalk);
    if (about.code === code && about.state === "ready") renderAbout(); // refresh "known" ticks
    renderGraph(sameTalk);
    renderDayPlan();
    renderTalks(currentTalkList());
    if (!sameTalk) revealTalk(code);
    renderMyTalks();
    if (trace) {
      const atTalks = plan.plan.filter((s) => s.learn_at && s.learn_at.kind === "talk").length;
      renderTrace([{ tool: "plan_day (no AI)", args: { talk: code }, cypher: plan.queries || [],
        result: { talk_title: plan.talk_title, steps: plan.plan.length, at_talks: atTalks, ready: plan.ready } }]);
    }
    view.wasReady = plan.ready;
    return plan;
  } finally {
    if (version === view.version) wrap.classList.remove("loading");
  }
}

function knownHow(how) {
  if (how === "attended") return "learned at a talk you attended";
  if (how === "profile") return "from your profile (you have experience)";
  return "you told me you know it";
}

// Basics the server took off the path because the profile says "some" or "experienced".
function profileSkippedNote(plan) {
  const n = (plan.already_known || []).filter((k) => k.how === "profile").length;
  if (!n) return "";
  return `<p class="profile-skip">${plural(n, "basic", "basics")} skipped from your profile · <button class="link" data-open-profile="1" title="Change your experience level">change</button></p>`;
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
    const known = (plan.already_known || []).map((k) => `<li><span class="tick-mark">✓</span> ${escapeHtml(conceptName(k.concept))} <span class="muted">· ${knownHow(k.how)}</span></li>`).join("");
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
    <div class="head-top"><span class="label">Your path to</span>${saveButton(plan.talk)}</div>
    <button class="head-title" data-open-talk="1">${escapeHtml(plan.talk_title)}</button>
    <div class="muted">${when}</div>
    ${status}
    ${profileSkippedNote(plan)}`;
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
      width: 230, height: 84, "background-color": c.accent, "border-color": c.accent,
      color: c.onAccent, "font-weight": 700, "font-size": 13, "text-max-width": 210,
    } },
    { selector: "node.concept", style: {
      width: 180, height: 56, "background-color": c.accentSoft, "border-color": c.accent, "border-width": 2,
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
      label = `YOUR TALK · ${dayShort(d.day)} ${formatTime(d.start)}\n${shortTitle(n.label, 40)}`;
    } else if (n.type === "talk") {
      const chosen = chosenTeachers.has(n.id);
      if (!chosen && !showAlts) continue;
      classes.push(chosen ? "chosen" : "alt");
      label = `${dayShort(d.day)} ${formatTime(d.start)}${d.sponsor ? " · Sponsored" : ""}\n${shortTitle(n.label)}`;
    } else if (n.type === "explainer") {
      classes.push(chosenTeachers.has(n.id) ? "chosen" : "alt");
      label = `Read · outside explainer\n${shortTitle(n.label)}`;
    } else if (n.type === "concept") {
      const name = shortTitle(n.label, 38); // long names like "Model Context Protocol (MCP) and MCP servers" fit the box
      if (d.known) { classes.push("known"); label = `✓ ${name}`; }
      else label = steps.has(d.concept) ? `${steps.get(d.concept)}. ${name}` : name;
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
// ---- resizable panels ------------------------------------------------------

const PANELS_KEY = "throughline.panels";
const PANEL_MIN = [220, 280]; // schedule, conversation
const PATH_MIN = 360; // the path panel keeps at least this much, so the graph never gets crushed
const HANDLE = 14;

function setupResizers() {
  const layout = document.querySelector(".layout");
  const panels = [layout.querySelector(".schedule"), layout.querySelector(".chat")];
  let fitQueued = false;

  const refit = () => {
    if (fitQueued) return;
    fitQueued = true;
    requestAnimationFrame(() => { fitQueued = false; if (cy) { cy.resize(); sizeAndFit(false); } });
  };
  // Clamp both widths so every panel keeps its minimum and the path panel keeps PATH_MIN.
  const apply = (w1, w2) => {
    const inner = layout.clientWidth - parseFloat(getComputedStyle(layout).paddingLeft) * 2 - 2 * HANDLE;
    w1 = Math.max(PANEL_MIN[0], Math.min(w1, inner - PANEL_MIN[1] - PATH_MIN));
    w2 = Math.max(PANEL_MIN[1], Math.min(w2, inner - w1 - PATH_MIN));
    layout.style.setProperty("--w1", `${Math.round(w1)}px`);
    layout.style.setProperty("--w2", `${Math.round(w2)}px`);
    refit();
    return [w1, w2];
  };
  const current = () => panels.map((p) => p.getBoundingClientRect().width);
  const save = (w) => storageSet(PANELS_KEY, JSON.stringify(w.map(Math.round)));
  const reset = () => {
    layout.style.removeProperty("--w1");
    layout.style.removeProperty("--w2");
    storageSet(PANELS_KEY, null);
    refit();
  };

  try {
    const saved = JSON.parse(storageGet(PANELS_KEY) || "null");
    if (Array.isArray(saved) && saved.length === 2 && saved.every(Number.isFinite)) apply(saved[0], saved[1]);
  } catch { /* ignore a bad saved value */ }

  layout.querySelectorAll(".resizer").forEach((handle) => {
    const index = Number(handle.dataset.resizer); // 0: between schedule and chat, 1: between chat and path
    handle.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      handle.setPointerCapture(e.pointerId);
      const startX = e.clientX;
      const [w1, w2] = current();
      handle.classList.add("dragging");
      document.body.classList.add("resizing");
      let last = [w1, w2];
      const move = (ev) => {
        const dx = ev.clientX - startX;
        // Left handle trades space between schedule and chat; right handle widens or narrows the chat.
        last = index === 0 ? apply(w1 + dx, w2 - dx) : apply(w1, w2 + dx);
      };
      const up = () => {
        handle.removeEventListener("pointermove", move);
        handle.classList.remove("dragging");
        document.body.classList.remove("resizing");
        save(last);
      };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", up, { once: true });
      handle.addEventListener("pointercancel", up, { once: true });
    });
    handle.addEventListener("dblclick", reset);
    handle.addEventListener("keydown", (e) => {
      if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return;
      e.preventDefault();
      const step = e.key === "ArrowRight" ? 32 : -32;
      const [w1, w2] = current();
      save(index === 0 ? apply(w1 + step, w2 - step) : apply(w1, w2 + step));
    });
  });
}

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

// ---- "About this talk": summary, key concepts, what to read first ------------------

// Collapsed by default; "1" here means the attendee opened it (new key, so earlier choices don't carry over).
const ABOUT_KEY = "throughline.about-open";
const MAX_READINGS = 3;
const READING_KINDS = ["docs", "video", "article", "repo", "paper"];
// code: the talk shown; data: briefing; abstract: from /api/talks; state: loading|ready|hidden
// state: loading | ready | pending (server still building it; retried quietly) | hidden
const about = { code: null, data: null, abstract: "", state: "hidden", turn: 0, openConcept: null, retries: 0, timer: 0 };

function aboutCollapsed() {
  return storageGet(ABOUT_KEY) !== "1";
}

// "2026-10-24T13:40:12Z" -> "Oct 24"; anything unparseable is shown as-is (escaped by the caller).
function formatFetched(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ""));
  if (!m) return String(iso || "");
  const mo = Number(m[2]);
  return mo >= 1 && mo <= 12 ? `${MONTHS[mo - 1]} ${Number(m[3])}, ${m[1]}` : String(iso);
}

function hideAbout() {
  about.turn++;
  clearTimeout(about.timer);
  about.code = null; about.data = null; about.abstract = ""; about.state = "hidden"; about.openConcept = null;
  document.getElementById("about").hidden = true;
}

// Called with every talk load. A new talk shows a skeleton; the same talk only retries if
// the briefing wasn't there yet (the endpoint may come online after the page loaded).
async function loadAbout(code) {
  if (about.code === code && about.state === "ready") return;
  const turn = ++about.turn;
  const fresh = about.code !== code;
  clearTimeout(about.timer);
  if (fresh) {
    about.code = code; about.data = null; about.abstract = ""; about.openConcept = null; about.retries = 0;
    about.state = "loading";
    renderAbout();
  }
  const [briefing, talk] = await Promise.all([
    api(`/api/talks/${encodeURIComponent(code)}/briefing`).catch(() => null),
    api(`/api/talks/${encodeURIComponent(code)}`).catch(() => null),
  ]);
  if (turn !== about.turn || about.code !== code) return; // the user moved on
  const ok = briefing && briefing.status === "ready"
    && (briefing.summary || (briefing.concepts || []).length || (briefing.readings || []).length);
  about.data = ok ? briefing : null;
  about.abstract = (talk && talk.abstract) || "";
  about.state = ok ? "ready" : briefing && briefing.status === "missing" ? "pending" : "hidden";
  renderAbout();
  // Still being built on the server: look again in a minute, a few times, then stay quiet.
  if (about.state === "pending" && about.retries < 6) {
    about.retries++;
    about.timer = setTimeout(() => { if (about.code === code && about.state === "pending") loadAbout(code).catch(() => {}); }, 60000);
  }
}

// The server may send a code ("ai", "abstract") or a ready-made phrase.
function summarySourceLabel(src) {
  const s = String(src || "").trim();
  if (!s || /^(ai|llm|model|claude|generated|summary)$/i.test(s)) return "AI summary of the abstract";
  if (/^(abstract|original|catalog|feed)$/i.test(s)) return "From the talk abstract";
  return s.slice(0, 80);
}

function aboutSkeleton() {
  return `<div class="about-skel" aria-hidden="true">
      <span class="sk sk-line"></span><span class="sk sk-line short"></span>
      <span class="sk sk-chips"><i></i><i></i><i></i></span>
      <span class="sk sk-line"></span><span class="sk sk-line"></span>
    </div><span class="visually-hidden">Loading the talk briefing…</span>`;
}

function aboutChip(c, knownIds) {
  const known = knownIds.has(c.id);
  const cls = ["cchip", c.basic ? "basic" : "", known ? "known" : "", about.openConcept === c.id ? "open" : ""].filter(Boolean).join(" ");
  const tip = [c.basic ? "Basic" : "", known ? "You know this" : "", c.definition || ""].filter(Boolean).join(" · ");
  return `<button type="button" class="${cls}" data-concept="${escapeHtml(c.id)}" title="${escapeHtml(tip)}"
      aria-expanded="${about.openConcept === c.id ? "true" : "false"}">${known ? `<span class="tick-mark" aria-hidden="true">✓</span>` : ""}${escapeHtml(c.name || c.id)}${
      c.basic ? `<span class="basic-tag">basic</span>` : ""}</button>`;
}

function aboutConceptGroup(label, hint, list, knownIds) {
  if (!list.length) return "";
  const open = list.find((c) => c.id === about.openConcept);
  return `<div class="about-group">
      <span class="about-sub" title="${escapeHtml(hint)}">${escapeHtml(label)}</span>
      <div class="cchips">${list.map((c) => aboutChip(c, knownIds)).join("")}</div>
      ${open ? `<div class="concept-pop" role="note"><strong>${escapeHtml(open.name || open.id)}</strong>${
        open.basic ? ` <span class="basic-tag">basic</span>` : ""}<p>${escapeHtml(open.definition || "No definition on file.")}</p></div>` : ""}
    </div>`;
}

function aboutReading(r) {
  const kind = READING_KINDS.includes(String(r.kind || "").toLowerCase()) ? String(r.kind).toLowerCase() : "link";
  const minutes = Number.isFinite(r.minutes) && r.minutes > 0 ? `<span class="read-min">~${Math.round(r.minutes)} min</span>` : "";
  const href = safeUrl(r.url);
  const title = escapeHtml(r.title || r.domain || r.url || "Untitled");
  return `<li class="reading">
      <div class="read-top">
        ${href === "#" ? `<span class="read-title">${title}</span>` : `<a class="read-title" href="${href}" target="_blank" rel="noopener noreferrer">${title}<span class="ext" aria-hidden="true"> ↗</span></a>`}
      </div>
      <div class="read-meta"><span class="kind kind-${kind}">${escapeHtml(kind)}</span>${
        r.domain ? `<span class="read-domain">${escapeHtml(r.domain)}</span>` : ""}${minutes}</div>
      ${r.why ? `<p class="read-why">${escapeHtml(r.why)}</p>` : ""}
    </li>`;
}

function renderAbout() {
  const box = document.getElementById("about");
  const body = document.getElementById("about-body");
  const toggle = document.getElementById("about-toggle");
  const peek = document.getElementById("about-peek");
  if (about.state === "hidden" || !about.code) { box.hidden = true; return; }
  const collapsed = aboutCollapsed();
  box.hidden = false;
  box.classList.toggle("collapsed", collapsed);
  toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
  body.hidden = collapsed;
  if (about.state === "loading" || about.state === "pending") {
    peek.textContent = about.state === "pending" ? "Preparing…" : "";
    body.innerHTML = about.state === "pending"
      ? `<p class="about-pending muted"><span class="spinner" aria-hidden="true"></span> Preparing the summary and reading list for this talk…</p>`
      : aboutSkeleton();
    return;
  }
  const b = about.data;
  const concepts = b.concepts || [];
  const readings = (b.readings || []).slice(0, MAX_READINGS);
  const knownIds = new Set([
    ...((view.plan && view.plan.already_known) || []).map((k) => k.concept),
    ...(view.known || []).map((k) => k.concept),
  ]);
  peek.textContent = collapsed
    ? [concepts.length ? plural(concepts.length, "concept", "concepts") : "", readings.length ? plural(readings.length, "reading", "readings") : ""].filter(Boolean).join(" · ")
    : "";
  const requires = concepts.filter((c) => c.role === "requires");
  const teaches = concepts.filter((c) => c.role === "teaches");
  const summary = b.summary ? `
      <p class="about-summary">${escapeHtml(b.summary)}</p>
      <div class="about-src">
        <span class="muted">${escapeHtml(summarySourceLabel(b.summary_source))}</span>
        ${about.abstract ? `<button type="button" class="link" data-abstract aria-expanded="false" aria-controls="about-abstract">Read the full abstract</button>` : ""}
      </div>
      ${about.abstract ? `<p class="about-abstract" id="about-abstract" hidden>${escapeHtml(about.abstract)}</p>` : ""}` : "";
  const conceptBlock = requires.length || teaches.length ? `
      <div class="about-concepts">
        <h4>Key concepts</h4>
        ${aboutConceptGroup("Assumes", "What the talk expects you to know already", requires, knownIds)}
        ${aboutConceptGroup("Teaches", "What you should walk out knowing", teaches, knownIds)}
      </div>` : "";
  const readBlock = readings.length ? `
      <div class="about-reads">
        <h4>Read before this talk</h4>
        <ul class="readings">${readings.map(aboutReading).join("")}</ul>
        <p class="about-foot muted">Found with live web search${b.fetched_at ? ` · checked ${escapeHtml(formatFetched(b.fetched_at))}` : ""}</p>
      </div>` : `<p class="about-pending muted">Preparing the reading list…</p>`;
  // Keep the abstract open across re-renders (chip clicks re-render the card).
  const abstractOpen = !!body.querySelector("#about-abstract:not([hidden])");
  body.innerHTML = summary + conceptBlock + readBlock;
  if (abstractOpen) setAbstractOpen(body, true);
}

function setAbstractOpen(body, open) {
  const text = body.querySelector("#about-abstract");
  const btn = body.querySelector("[data-abstract]");
  if (!text || !btn) return;
  text.hidden = !open;
  btn.setAttribute("aria-expanded", open ? "true" : "false");
  btn.textContent = open ? "Hide the abstract" : "Read the full abstract";
}

function wireAbout() {
  document.getElementById("about-toggle").addEventListener("click", () => {
    storageSet(ABOUT_KEY, aboutCollapsed() ? "1" : null);
    renderAbout();
  });
  document.getElementById("about-body").addEventListener("click", (e) => {
    const body = e.currentTarget;
    if (e.target.closest("[data-abstract]")) {
      setAbstractOpen(body, body.querySelector("#about-abstract").hidden);
      return;
    }
    const chip = e.target.closest("button[data-concept]");
    if (!chip || !about.data) return;
    const id = chip.dataset.concept;
    // On the graph already: open the full evidence dialog. Otherwise show its definition inline.
    const node = view.plan && graphNode(`concept:${id}`);
    if (node && node.type === "concept") { about.openConcept = null; renderAbout(); openConcept(node); return; }
    about.openConcept = about.openConcept === id ? null : id;
    renderAbout();
    const again = body.querySelector(`button[data-concept="${CSS.escape(id)}"]`);
    if (again) again.focus();
  });
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
      ${saveButton(t.code, "secondary save-btn")}
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
  api("/api/conferences").then((c) => {
    const cur = c && c.current;
    if (cur && cur.name) document.getElementById("conference").textContent = [cur.name, cur.dates, cur.location].filter(Boolean).join(" · ");
  }).catch(() => {});
  document.getElementById("clock").textContent = formatClock(clock.now);
  document.getElementById("status").textContent = `${health.talks} talks · FalkorDB knowledge graph${
    graphAvailable() ? "" : " · graph drawing unavailable, showing text path"}`;
  allTalks = talks;
  introHtml = document.getElementById("messages").innerHTML;
  renderTalks(allTalks);
  renderHead(false);
  wireProfile();
  wireAbout();
  await startAttendee();
  renderTalks(allTalks);
  const lastChatTalk = await loadChat();

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
    if (button.dataset.action === "save") toggleTarget(code);
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
    const save = e.target.closest("[data-save]");
    if (save) return toggleTarget(save.dataset.save);
    if (e.target.closest("[data-open-profile]")) return openProfile();
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
    const save = e.target.closest("button[data-save]");
    if (save) {
      const code = save.dataset.save;
      toggleTarget(code).then(() => { if (dialogCtx && dialogCtx.kind === "talk" && dialogCtx.code === code) openTalk(code); });
      return;
    }
    const b = e.target.closest("button[data-act]");
    if (b) onDialogAction(b.dataset.act);
  });
  dlg.addEventListener("close", () => { dialogCtx = null; });

  window.addEventListener("resize", () => { if (cy) { cy.resize(); sizeAndFit(false); } });
  setupResizers();
  try {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { if (cy) cy.style(graphStyle()); });
  } catch { /* old browsers */ }

  document.getElementById("forget").addEventListener("click", async () => {
    if (!confirm("Delete everything Throughline remembers about you?")) return;
    await api(`/api/attendees/${encodeURIComponent(attendee)}`, { method: "DELETE" });
    storageSet(CODE_KEY, null);
    storageSet(TALK_KEY, null);
    me.readiness.clear();
    resetTalkView();
    await startAttendee();
    await loadChat();
    addMessage("agent card", `<p>Forgotten. You have a fresh code: <strong>${escapeHtml(attendee)}</strong>.</p>`);
    renderTalks(currentTalkList());
    maybePromptProfile();
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
      me.readiness.clear();
      const lastTalk = await loadChat();
      addMessage("agent card", `<p>Welcome back. You know ${state.known.length} concept(s) and attended ${state.attended.length} talk(s).</p>`);
      const talk = rememberedTalk() || lastTalk;
      if (talk && findTalk(talk)) await loadTalkView(talk, { trace: true });
      else { resetTalkView(); renderTalks(currentTalkList()); }
      maybePromptProfile();
    } catch {
      attendee = previous;
      await refreshAttendee();
      alert("That code isn't known.");
    }
  });

  // A ?code= link wins (the conference map links here that way), then the talk you were
  // looking at, then the one the conversation was about. All model-free: no agent call.
  maybePromptProfile();
  const linked = linkedTalk();
  const saved = rememberedTalk() || lastChatTalk;
  if (linked && linked !== saved) {
    planWithoutAI(linked);
  } else if (linked || (saved && findTalk(saved))) {
    loadTalkView(linked || saved, { trace: true }).catch(() => { rememberTalk(null); syncUrl(null); });
  } else {
    syncUrl(null); // drop an unknown ?code=
  }
}

init().catch((err) => {
  document.getElementById("status").textContent = `Couldn't load: ${err.message}`;
});
