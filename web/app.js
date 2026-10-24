const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

let allTalks = [];

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

// Feed data is untrusted: escape everything, including quotes for attribute values.
function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function safeUrl(url) {
  return /^https:\/\//.test(url || "") ? escapeHtml(url) : "#";
}

function renderTalks(talks) {
  const container = document.getElementById("talks");
  let html = "";
  let currentDay = null;
  for (const t of talks) {
    if (t.day !== currentDay) {
      currentDay = t.day;
      html += `<h2 class="day">${escapeHtml(t.day)}</h2>`;
    }
    html += `
      <button class="talk" data-code="${escapeHtml(t.code)}">
        <span class="when">${formatTime(t.start)}</span>
        <span class="what">
          <span class="title">${escapeHtml(t.title)}</span>
          <span class="meta">${levelBadge(t.level_num)}${escapeHtml(t.type)} · ${escapeHtml(t.room)}</span>
        </span>
      </button>`;
  }
  container.innerHTML = html || `<p class="empty">No talks match.</p>`;
}

async function showTalk(code) {
  document.querySelectorAll(".talk.selected").forEach((el) => el.classList.remove("selected"));
  document.querySelector(`.talk[data-code="${CSS.escape(code)}"]`)?.classList.add("selected");
  const t = await (await fetch(`/api/talks/${encodeURIComponent(code)}`)).json();
  document.getElementById("detail").innerHTML = `
    <p class="eyebrow">${levelBadge(t.level_num)}${escapeHtml(t.level || "No level")} · ${escapeHtml(t.type)}</p>
    <h2>${escapeHtml(t.title)}</h2>
    <p class="when-where">${escapeHtml(t.day)} ${formatTime(t.start)}–${formatTime(t.end)} · ${escapeHtml(t.room)}</p>
    <p class="speakers">${t.speakers.map(escapeHtml).join(" · ")}</p>
    <p class="abstract">${escapeHtml(t.abstract)}</p>
    <button class="primary" disabled title="Coming next: learning path">Plan my path to this talk</button>
    <p class="source">Source: <a href="${safeUrl(t.url)}" target="_blank" rel="noopener">session page</a> · ${escapeHtml(t.source)}, loaded ${escapeHtml(t.fetched_at)}</p>`;
}

function filterTalks(query) {
  const q = query.trim().toLowerCase();
  if (!q) return allTalks;
  return allTalks.filter((t) =>
    [t.title, t.room, t.type, ...(t.speakers || []), ...(t.topics || [])].join(" ").toLowerCase().includes(q)
  );
}

async function init() {
  const [clock, talks, health] = await Promise.all([
    fetch("/api/clock").then((r) => r.json()),
    fetch("/api/talks").then((r) => r.json()),
    fetch("/api/health").then((r) => r.json()),
  ]);
  document.getElementById("clock").textContent = formatClock(clock.now);
  document.getElementById("conference").textContent = clock.conference;
  document.getElementById("status").textContent = `${health.talks} talks in graph “${health.graph}”`;
  allTalks = talks;
  renderTalks(allTalks);

  document.getElementById("talks").addEventListener("click", (e) => {
    const button = e.target.closest(".talk");
    if (button) showTalk(button.dataset.code);
  });
  document.getElementById("search").addEventListener("input", (e) => renderTalks(filterTalks(e.target.value)));
}

init().catch((err) => {
  document.getElementById("status").textContent = `Couldn't load: ${err.message}`;
});
