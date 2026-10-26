"""The build job: a conference's schedule page becomes its own map, in the background.

`start` marks the conference `building` and runs `run` in a thread, one per conference (a second
click joins the running build). `run` is the whole pipeline, and each step's text goes to the registry:
  1. Find the schedule page from the pasted link, else the conference website (at most 2 link hops).
  2. Have the model list the talks, then keep only what the page itself says (importer.verify_listing).
  3. Read each talk's own page for its full abstract and duration; drop talks without times.
  4. Check the talks belong to this event's dates, and that at least MIN_TALKS are left.
  5. Draft the concept list and link talks to it (the word-for-word evidence check runs on load).
  6. Write a fresh graph `throughline_c_<id>_v<n>` and its public copy; mark the entry ready or partial.
  7. Find outside explainers, after the map is already open.

A retry never makes things worse. When the conference already has a map, the new one replaces it
only if it kept more talks, and attendees' marks carry over to it; otherwise the earlier map stays.
Universe is never built here.
"""

import logging
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Lock, Thread, current_thread
from typing import Callable

from falkordb import Graph
from openai import OpenAI

from . import explainers, extract, graph, importer, registry
from .evidence import normalize
from .knowledge import derive_depends_on, load_concepts, load_edges

log = logging.getLogger(__name__)

MIN_TALKS = 5
STEPS = {
    "schedule": "Finding the schedule",
    "listing": "Reading the talks",
    "details": "Reading talk pages ({done} of {total})",
    "concepts": "Making the concept list",
    "edges": "Linking talks to concepts ({done} of {total})",
    "finish": "Finishing the map",
}
BUILT = ("ready", "partial")
KEPT_OLD = "The retry found fewer talks, so the earlier map was kept."
NOT_LINKED = "The retry couldn't link talks to concepts, so the earlier map was kept."
RETRY_INTERRUPTED = "A retry was interrupted; the earlier map was kept."
UNSAFE = "That link can't be fetched safely."
NEEDS_LOGIN = "The schedule page needs a login."
LOGIN_WORDS = re.compile(r"\b(sign|log) in\b", re.I)  # not "blog in" or "catalog in"
GRAPH_PREFIX = "throughline_c_"
CLOCK_TIME = "08:30"


def ask_openai(system: str, user: str, schema: dict) -> dict:
    """importer.ask_openai, with a 600 s wait for the one call that reads every abstract at once."""
    if system == extract.CONCEPTS_PROMPT:
        return extract._ask(OpenAI(timeout=600, max_retries=1), system, user, schema)
    return importer.ask_openai(system, user, schema)


def find_explainers(g: Graph) -> None:
    """Outside explainers for a new map (Universe's cache file is never read or written), then a fresh public copy."""
    explainers.run(g, cache=None)
    graph.publish_public_view(g)


@dataclass
class Deps:
    fetch: Callable[[str], importer.Page] = importer.fetch_page
    ask: importer.Ask = ask_openai
    connect: Callable[[str], Graph] = graph.connect  # graph name -> Graph
    explain: Callable[[Graph], None] = find_explainers


_running: dict[str, Thread] = {}
_lock = Lock()


def start(reg: Graph, conf_id: str, schedule_url: str | None = None, deps: Deps | None = None) -> dict:
    """Mark the conference building and build it in a background thread; join a build already running."""
    with _lock:
        entry = registry.get(reg, conf_id)
        if entry is None:
            raise KeyError(conf_id)
        running = _running.get(conf_id)
        if conf_id == registry.UNIVERSE_ID or (running and running.is_alive()):
            return entry
        entry = _mark_building(reg, conf_id, schedule_url)
        thread = Thread(target=_run_then_forget, args=(reg, conf_id, schedule_url, deps or Deps()),
                        name=f"build-{conf_id}", daemon=True)
        _running[conf_id] = thread
        thread.start()
    return entry


def _run_then_forget(reg: Graph, conf_id: str, schedule_url: str | None, deps: Deps) -> None:
    try:
        run(reg, conf_id, schedule_url, deps)
    finally:
        with _lock:
            if _running.get(conf_id) is current_thread():
                del _running[conf_id]


def _mark_building(reg: Graph, conf_id: str, schedule_url: str | None) -> dict:
    fields = {"schedule_url": schedule_url} if schedule_url else {}
    return registry.set_status(reg, conf_id, status="building", step=STEPS["schedule"], reason="", **fields)


def recover_interrupted(reg: Graph) -> int:
    """At startup: a build left `building` died with the old process. A retry of an existing map gives
    that map back (its status from its counts); a first build becomes `failed`. Returns how many changed."""
    retried = [c for c in registry.list_conferences(reg) if c["status"] == "building" and c["graph"]]
    for c in retried:
        registry.set_status(reg, c["id"], status=status_for(c["counts"]), step="", reason=RETRY_INTERRUPTED)
    return len(retried) + registry.mark_interrupted(reg)


def status_for(counts: dict) -> str:
    """partial when anything was left out (dropped talks, unread talk pages, failed extractions)."""
    return "partial" if any(n for key, n in counts.items() if key != "kept") else "ready"


def run(reg: Graph, conf_id: str, schedule_url: str | None = None, deps: Deps | None = None) -> dict:
    """Build the conference's map now (the thread's job) and return its final registry entry."""
    deps = deps or Deps()
    entry = registry.get(reg, conf_id)
    if entry is None:
        raise KeyError(conf_id)
    if conf_id == registry.UNIVERSE_ID:
        return entry
    # Only a finished build assigns a graph, so a graph name means there is a map to protect.
    # Its status comes from its counts: `building` (or `failed`, after a restart) has overwritten it.
    old = None
    if entry["graph"]:
        old = {"graph": entry["graph"], "status": status_for(entry["counts"]), "talks": entry["talks"]}

    def step(key: str, **numbers) -> None:
        registry.set_status(reg, conf_id, step=STEPS[key].format(**numbers))

    def finish(status: str, reason: str = "", **fields) -> dict:
        if old and status not in BUILT:  # a failed retry leaves the earlier map open
            status, reason = old["status"], f"{reason} The earlier map was kept."
        return registry.set_status(reg, conf_id, status=status, step="", reason=reason, **fields)

    _mark_building(reg, conf_id, schedule_url)
    new_name = ""
    try:
        start_url = schedule_url or entry["url"]
        page, reason = _find_schedule(start_url, deps)
        if page is None:
            return finish("not_found", reason)
        step("listing")
        kept, counts, reason = _read_talks(page, entry, deps, step)
        if reason:
            return finish("not_found", reason)
        talks = importer.to_talks(conf_id, kept, page_url=page.url)
        counts = {"kept": len(talks), **counts}
        if old and len(talks) <= old["talks"]:
            return registry.set_status(reg, conf_id, status=old["status"], step="", reason=KEPT_OLD)

        step("concepts")
        concepts = extract.draft_concepts(talks, ask=deps.ask)
        edges, failed = [], 0
        if concepts:
            edges, failed = extract.extract_edges(
                talks, concepts, ask=deps.ask, progress=lambda done, total: step("edges", done=done, total=total))
        if failed:
            counts["extract_failed"] = failed

        step("finish")
        new_name = f"{GRAPH_PREFIX}{conf_id}_v{_version(old['graph'] if old else '') + 1}"
        _drop(deps, new_name)  # a build interrupted earlier may have left this version half-written
        conf = _conference(entry, talks)
        g = deps.connect(new_name)
        graph.ensure_schema(g)
        graph.load_talks(g, talks, source="schedule page", conf=conf)
        load_concepts(g, concepts)
        linked = load_edges(g, edges)["kept"]
        with_abstracts = sum(1 for t in talks if t["abstract"].strip())
        if old and (linked == 0 or failed > with_abstracts / 2):  # never swap a linked map for an unlinked one
            _drop(deps, new_name)
            new_name = ""
            return registry.set_status(reg, conf_id, status=old["status"], step="", reason=NOT_LINKED)
        if linked == 0:  # the talks are real, but nothing connects them yet
            counts["no_links"] = len(talks)
        derive_depends_on(g)
        if old:
            carry_over(deps.connect(old["graph"]), g)
        graph.publish_public_view(g)
        final = registry.set_status(
            reg, conf_id, status=status_for(counts), step="", reason="", counts=counts, graph=new_name,
            talks=len(talks), **{k: conf[k] for k in ("clock_start", "start_date", "end_date", "dates")})
        new_name = ""  # the registry points at it now: never clean it up
        if old:
            _drop(deps, old["graph"])
    except Exception as e:
        log.exception("the build of %s stopped", conf_id)
        if new_name:
            _drop(deps, new_name)
        return finish("failed", f"The build stopped: {type(e).__name__}")

    try:
        deps.explain(g)
    except Exception:  # the map is already open; it just has no outside explainers yet
        log.exception("explainers for %s failed", conf_id)
    return final


def _find_schedule(start_url: str, deps: Deps) -> tuple[importer.Page | None, str]:
    """The schedule page, or None and the reason in plain words."""
    if not start_url:
        return None, "We couldn't find a schedule page."
    try:
        first = deps.fetch(start_url)
    except importer.UnsafeURL:
        return None, UNSAFE
    except Exception:
        return None, f"We couldn't load {start_url}."
    fetch = lambda url: first if url == start_url else deps.fetch(url)  # noqa: E731
    try:
        page, _ = importer.find_schedule(start_url, fetch=fetch, ask=deps.ask)
    except importer.UnsafeURL:
        return None, UNSAFE
    return page, "" if page else f"We couldn't find a schedule page on {start_url}."


def _read_talks(page: importer.Page, entry: dict, deps: Deps, step) -> tuple[list[dict], Counter, str]:
    """The talks the page vouches for, what was left out, and the not-found reason if too few remain."""
    raw = importer.read_listing(page, ask=deps.ask)
    if len(raw) < MIN_TALKS and LOGIN_WORDS.search(page.text):
        return [], Counter(), NEEDS_LOGIN
    kept, dropped = importer.verify_listing(page, raw)
    if len(kept) >= MIN_TALKS:
        step("details", done=0, total=sum(1 for t in kept if t.get("detail_url")))
        dropped += importer.enrich(kept, fetch=deps.fetch, ask=deps.ask,
                                   progress=lambda done, total: step("details", done=done, total=total))
        dropped += importer.finish_times(kept)
        before = len(kept)
        kept, reason = importer.check_event(kept, entry["start_date"], entry["end_date"])
        if reason:
            return [], dropped, reason
        if before > len(kept):
            dropped["outside_dates"] = before - len(kept)
    if len(kept) < MIN_TALKS:
        return [], dropped, f"{page.url} doesn't list any talks yet."
    return kept, dropped, ""


def _version(name: str) -> int:
    match = re.search(r"_v(\d+)$", name or "")
    return int(match.group(1)) if match else 0


def _drop(deps: Deps, name: str) -> None:
    """Delete a conference graph and its public copy; never Universe's or anything not built here."""
    if not name.startswith(GRAPH_PREFIX):
        return
    for target in (name, graph.public_name(name)):
        try:
            deps.connect(target).delete()
        except Exception:  # it was never written
            pass


# --- the Conference node -------------------------------------------------------

def clock_start(talks: list[dict]) -> str:
    """08:30 on the first talk day, or 30 minutes before the first talk if that is earlier."""
    first = min(datetime.fromisoformat(f"{t['date']}T{t['start']}") for t in talks)
    clock = min(datetime.fromisoformat(f"{first.date().isoformat()}T{CLOCK_TIME}"), first - timedelta(minutes=30))
    return clock.strftime("%Y-%m-%dT%H:%M")


def dates_text(start: str, end: str) -> str:
    """"Nov 16–20, 2026", "Oct 30–Nov 2, 2026" or "Nov 16, 2026"."""
    a, b = datetime.fromisoformat(start), datetime.fromisoformat(end)
    first = f"{importer.MONTHS[a.month - 1]} {a.day}"
    if a == b:
        return f"{first}, {a.year}"
    if a.year != b.year:
        return f"{first}, {a.year}–{importer.MONTHS[b.month - 1]} {b.day}, {b.year}"
    last = str(b.day) if a.month == b.month else f"{importer.MONTHS[b.month - 1]} {b.day}"
    return f"{first}–{last}, {a.year}"


def _conference(entry: dict, talks: list[dict]) -> dict:
    """The entry's details, with the clock; dates come from the talks when the search gave none."""
    conf = {k: entry.get(k) or "" for k in ("id", "name", "dates", "start_date", "end_date", "location", "url")}
    if not conf["start_date"]:
        days = sorted(t["date"] for t in talks)
        conf.update(start_date=days[0], end_date=days[-1], dates=dates_text(days[0], days[-1]))
    conf["end_date"] = conf["end_date"] or conf["start_date"]
    conf["dates"] = conf["dates"] or dates_text(conf["start_date"], conf["end_date"])
    conf["clock_start"] = clock_start(talks)
    return conf


# --- carrying attendees over to a rebuilt map -------------------------------------

def carry_over(old: Graph, new: Graph) -> int:
    """Copy each Attendee to the new map: its properties, attended and saved talks by talk code, and
    "I know this" marks by concept id, else by name matching a new concept's name or alias.
    Marks that match nothing are dropped. Returns the number of attendees copied."""
    people = old.query("MATCH (a:Attendee) RETURN properties(a)").result_set
    new.query("UNWIND $rows AS r MERGE (a:Attendee {code: r.code}) SET a += r", {"rows": [dict(p[0]) for p in people]})
    for edge in ("ATTENDED", "TARGETS"):  # edge types can't be query parameters
        rows = old.query(f"MATCH (a:Attendee)-[e:{edge}]->(t:Talk) RETURN a.code, t.code, properties(e)").result_set
        new.query(
            f"""
            UNWIND $rows AS r
            MATCH (a:Attendee {{code: r[0]}}), (t:Talk {{code: r[1]}})
            MERGE (a)-[e:{edge}]->(t) SET e += r[2]
            """,
            {"rows": [[a, t, dict(props)] for a, t, props in rows]},
        )
    concepts = new.query("MATCH (c:Concept) RETURN c.id, c.name, c.aliases").result_set
    ids = {cid for cid, _, _ in concepts}
    by_name = {normalize(alias): cid for cid, _, aliases in concepts for alias in aliases or []}
    by_name |= {normalize(name): cid for cid, name, _ in concepts}  # a name wins over another concept's alias
    marks = []
    for code, cid, name, props in old.query(
            "MATCH (a:Attendee)-[k:KNOWS]->(c:Concept) RETURN a.code, c.id, c.name, properties(k)").result_set:
        target = cid if cid in ids else by_name.get(normalize(name))
        if target:
            marks.append([code, target, dict(props)])
    new.query(
        """
        UNWIND $rows AS r
        MATCH (a:Attendee {code: r[0]}), (c:Concept {id: r[1]})
        MERGE (a)-[k:KNOWS]->(c) SET k += r[2]
        """,
        {"rows": marks},
    )
    return len(people)
