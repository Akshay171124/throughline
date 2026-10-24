const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const CODE_KEY = "throughline.attendee";

let allTalks = [];
let attendee = null;
let history = []; // earlier user/assistant text for the agent

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

function levelBadge(levelNum) {
  return levelNum ? `<span class="level l${levelNum}">${levelNum}</span>` : "";
}

// Minimal formatting for agent replies: escape, then **bold** and line breaks.
function formatReply(text) {
  return escapeHtml(text).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/\n/g, "<br>");
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

// ---- attendee memory -------------------------------------------------------

async function refreshAttendee() {
  const state = await api(`/api/attendees/${encodeURIComponent(attendee)}`);
  document.getElementById("attendee-code").textContent = attendee;
  document.getElementById("clock").textContent = state.clock ? state.clock.replace(",", " ·") : "--";
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

// ---- schedule --------------------------------------------------------------

function renderTalks(talks) {
  let html = "";
  let currentDay = null;
  for (const t of talks) {
    if (t.day !== currentDay) {
      currentDay = t.day;
      html += `<h2 class="day">${escapeHtml(t.day)}</h2>`;
    }
    html += `
      <div class="talk" data-code="${escapeHtml(t.code)}">
        <span class="when">${formatTime(t.start)}</span>
        <span class="what">
          <span class="title">${escapeHtml(t.title)}</span>
          <span class="meta">${levelBadge(t.level_num)}${escapeHtml(t.type)} · ${escapeHtml(t.room)}</span>
          <span class="actions">
            <button class="chip" data-action="ask">Get me ready</button>
            <button class="chip ghost" data-action="plan" title="Same graph queries, no AI">Plan without AI</button>
            <button class="chip ghost" data-action="attended">I attended this</button>
          </span>
        </span>
      </div>`;
  }
  document.getElementById("talks").innerHTML = html || `<p class="muted pad">No talks match.</p>`;
}

function filterTalks(query) {
  const q = query.trim().toLowerCase();
  if (!q) return allTalks;
  return allTalks.filter((t) =>
    [t.title, t.room, t.type, ...(t.speakers || []), ...(t.topics || [])].join(" ").toLowerCase().includes(q)
  );
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
  if (!trace.length) {
    list.innerHTML = `<p class="muted pad">No tools were called for this answer.</p>`;
    return;
  }
  list.innerHTML = trace.map((step, i) => `
    <details class="step" ${i === trace.length - 1 ? "open" : ""}>
      <summary><span class="step-n">${i + 1}</span> <code>${escapeHtml(step.tool)}</code>
        <span class="muted">${escapeHtml(JSON.stringify(step.args))}</span></summary>
      ${step.cypher.map((c) => `<pre class="cypher">${escapeHtml(c)}</pre>`).join("")}
      <pre class="result">${escapeHtml(JSON.stringify(step.result, null, 2)).slice(0, 4000)}</pre>
    </details>`).join("");
}

async function ask(message) {
  addMessage("user", `<p>${escapeHtml(message)}</p>`);
  const pending = addMessage("agent pending", `<p>Checking the graph…</p>`);
  try {
    const turn = await api("/api/agent", {
      method: "POST",
      body: JSON.stringify({ attendee, message, history }),
    });
    pending.classList.remove("pending");
    pending.innerHTML = `<p>${formatReply(turn.reply || "")}</p>`;
    history.push({ role: "user", content: message }, { role: "assistant", content: turn.reply || "" });
    renderTrace(turn.trace);
    await refreshAttendee();
  } catch (err) {
    pending.classList.remove("pending");
    pending.innerHTML = `<p class="error">The agent failed: ${escapeHtml(err.message)}. Use “Plan without AI” on the talk instead.</p>`;
  }
}

// The model-free fallback: the same graph queries, rendered directly.
async function planWithoutAI(code) {
  const plan = await api(`/api/plan/${encodeURIComponent(code)}?attendee=${encodeURIComponent(attendee)}`);
  if (plan.ready) {
    addMessage("agent card", `<p><strong>You're ready</strong> for ${escapeHtml(plan.talk_title)}. Nothing on its path is missing.</p>`);
  } else {
    const steps = plan.plan.map((s, i) => {
      const at = s.learn_at;
      const where = at.kind === "talk"
        ? `${escapeHtml(at.day)} ${formatTime(at.start)} · ${escapeHtml(at.title)} <span class="muted">(${escapeHtml(at.room)})</span>`
        : at.kind === "explainer"
          ? `<a href="${safeUrl(at.url)}" target="_blank" rel="noopener">${escapeHtml(at.title)}</a> <span class="muted">(explainer)</span>`
          : `<span class="muted">No talk teaches this in time: needs an outside explainer</span>`;
      return `<li><strong>${escapeHtml(s.name)}</strong><br>${where}${s.note ? `<br><span class="note">${escapeHtml(s.note)}</span>` : ""}</li>`;
    }).join("");
    addMessage("agent card", `<p>Your path to <strong>${escapeHtml(plan.talk_title)}</strong>:</p><ol>${steps}</ol><p class="muted">Model-free plan from the graph.</p>`);
  }
  renderTrace([{ tool: "plan_day (no AI)", args: { talk: code }, cypher: plan.queries, result: { steps: plan.plan.length, ready: plan.ready } }]);
}

async function attendedTalk(code) {
  const result = await api(`/api/attendees/${encodeURIComponent(attendee)}/attended`, {
    method: "POST", body: JSON.stringify({ talk: code }),
  });
  const talk = allTalks.find((t) => t.code === code);
  addMessage("agent card", `<p>Marked <strong>${escapeHtml(talk ? talk.title : code)}</strong> as attended. Learned: ${
    result.learned.length ? result.learned.map(escapeHtml).join(", ") : "nothing new"}. Clock moved to ${escapeHtml(result.clock)}.</p>`);
  await refreshAttendee();
}

// ---- wiring ----------------------------------------------------------------

async function init() {
  const [clock, talks, health] = await Promise.all([api("/api/clock"), api("/api/talks"), api("/api/health")]);
  document.getElementById("conference").textContent = clock.conference;
  document.getElementById("clock").textContent = formatClock(clock.now);
  document.getElementById("status").textContent = `${health.talks} talks · graph “${health.graph}” on ${health.backend}`;
  allTalks = talks;
  renderTalks(allTalks);
  await startAttendee();

  document.getElementById("talks").addEventListener("click", (e) => {
    const button = e.target.closest("button[data-action]");
    const row = e.target.closest(".talk");
    if (!row) return;
    const code = row.dataset.code;
    const talk = allTalks.find((t) => t.code === code);
    if (!button) return row.classList.toggle("open");
    if (button.dataset.action === "ask") ask(`Get me ready for "${talk.title}" (${code}).`);
    if (button.dataset.action === "plan") planWithoutAI(code);
    if (button.dataset.action === "attended") attendedTalk(code);
  });
  document.getElementById("search").addEventListener("input", (e) => renderTalks(filterTalks(e.target.value)));
  document.getElementById("composer").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = document.getElementById("input");
    if (input.value.trim()) ask(input.value.trim());
    input.value = "";
  });
  document.getElementById("forget").addEventListener("click", async () => {
    if (!confirm("Delete everything Throughline remembers about you?")) return;
    await api(`/api/attendees/${encodeURIComponent(attendee)}`, { method: "DELETE" });
    storageSet(CODE_KEY, null);
    history = [];
    await startAttendee();
    addMessage("agent card", `<p>Forgotten. You have a fresh code: <strong>${escapeHtml(attendee)}</strong>.</p>`);
  });
  document.getElementById("switch-code").addEventListener("click", async () => {
    const code = (prompt("Enter your Throughline code") || "").trim().toUpperCase();
    if (!code) return;
    const previous = attendee;
    try {
      attendee = code;
      const state = await refreshAttendee();
      storageSet(CODE_KEY, code);
      history = [];
      addMessage("agent card", `<p>Welcome back. You know ${state.known.length} concept(s) and attended ${state.attended.length} talk(s).</p>`);
    } catch {
      attendee = previous;
      await refreshAttendee();
      alert("That code isn't known.");
    }
  });
}

init().catch((err) => {
  document.getElementById("status").textContent = `Couldn't load: ${err.message}`;
});
