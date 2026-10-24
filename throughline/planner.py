"""Learning path, day plan and attendee memory: the graph queries behind every button and agent tool.

Each function returns the Cypher it ran under "queries", so the trace panel can show it.
"""

import json
import secrets
from datetime import datetime, timezone

from falkordb import Graph

from .catalog import to_minutes
from .config import settings

MAX_DEPTH = 3

PATH_ROOTS = """
MATCH (t:Talk {code: $talk})-[r:REQUIRES]->(c:Concept)
RETURN c.id, c.name, r.evidence, r.status
ORDER BY c.id
"""
PATH_LINKS = f"""
MATCH (:Talk {{code: $talk}})-[:REQUIRES]->(root:Concept)
MATCH p = (root)-[:DEPENDS_ON*1..{MAX_DEPTH}]->(:Concept)
UNWIND relationships(p) AS d
WITH DISTINCT d
RETURN startNode(d).id, endNode(d).id, endNode(d).name, d.support, d.via
"""
KNOWN = "MATCH (:Attendee {code: $attendee})-[k:KNOWS]->(c:Concept) RETURN c.id, k.how"
TEACHERS = """
MATCH (c:Concept {id: $concept})<-[e:TEACHES]-(t:Talk)
WHERE t.start_min >= $after AND t.end_min <= $before AND t.code <> $target
RETURN t.code, t.title, t.day, t.start, t.end, t.start_min, t.end_min, t.room, e.evidence, t.level_num, t.sponsor
ORDER BY t.start_min
"""
TEACHER_KEYS = ["code", "title", "day", "start", "end", "start_min", "end_min", "room", "evidence", "level_num", "sponsor"]
EXPLAINERS = """
MATCH (r:Resource)-[e:EXPLAINS]->(:Concept {id: $concept})
RETURN r.url, r.title, r.minutes, r.fetched_at, e.evidence
LIMIT 1
"""


def format_minutes(minutes: int | None) -> str | None:
    """Conference wall-clock minutes (see catalog.to_minutes) as e.g. "Wed Oct 28, 8:30 AM"."""
    if minutes is None:
        return None
    moment = datetime.fromtimestamp(minutes * 60, tz=timezone.utc)
    return f"{moment:%a %b} {moment.day}, {moment.hour % 12 or 12}:{moment:%M %p}"


# --- attendee memory -------------------------------------------------------

# No 0/O, 1/I/L: the code is read off a screen and typed back in.
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def new_code() -> str:
    """12 characters (~59 bits) grouped for reading, e.g. K7QF-M2XA-9PLR. The code is the only
    key to an attendee's memory, so it has to be unguessable; 128-bit tokens would be too long
    to retype on stage, and the page keeps the code in local storage so most visits never type it."""
    chars = "".join(secrets.choice(CODE_ALPHABET) for _ in range(12))
    return "-".join(chars[i:i + 4] for i in range(0, 12, 4))


def new_attendee(g: Graph) -> str:
    code = new_code()
    date, time = settings.clock_start.split("T")
    g.query(
        "CREATE (:Attendee {code: $code, clock_min: $clock})",
        {"code": code, "clock": to_minutes(date, time)},
    )
    return code


def attendee_clock(g: Graph, attendee: str) -> int | None:
    rows = g.query("MATCH (a:Attendee {code: $code}) RETURN a.clock_min", {"code": attendee}).result_set
    return rows[0][0] if rows else None


def mark_known(g: Graph, attendee: str, concept: str) -> None:
    g.query(
        """
        MATCH (a:Attendee {code: $attendee}), (c:Concept {id: $concept})
        MERGE (a)-[k:KNOWS]->(c) SET k.how = 'said'
        """,
        {"attendee": attendee, "concept": concept},
    )


def mark_attended(g: Graph, attendee: str, talk: str) -> list[str]:
    """Record the talk, learn everything it teaches, and move the clock to its end."""
    params = {"attendee": attendee, "talk": talk}
    g.query(
        """
        MATCH (a:Attendee {code: $attendee}), (t:Talk {code: $talk})
        MERGE (a)-[:ATTENDED]->(t)
        SET a.clock_min = CASE WHEN t.end_min > a.clock_min THEN t.end_min ELSE a.clock_min END
        """,
        params,
    )
    rows = g.query(
        """
        MATCH (a:Attendee {code: $attendee}), (t:Talk {code: $talk})-[:TEACHES]->(c:Concept)
        MERGE (a)-[k:KNOWS]->(c)
        SET k.how = 'attended', k.via = t.code
        RETURN c.id
        """,
        params,
    ).result_set
    return [r[0] for r in rows]


def forget_known(g: Graph, attendee: str, concept: str) -> None:
    g.query(
        "MATCH (:Attendee {code: $attendee})-[k:KNOWS]->(:Concept {id: $concept}) DELETE k",
        {"attendee": attendee, "concept": concept},
    )


# --- profile, saved talks and chat memory (all on the Attendee node, so "Forget me" removes them) ---

EXPERIENCE_LEVELS = ("", "new", "some", "experienced")
CHAT_LIMIT = 50


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def set_profile(g: Graph, attendee: str, role: str = "", experience: str = "", interests: list[str] | None = None) -> dict:
    if experience not in EXPERIENCE_LEVELS:
        raise ValueError(f"experience must be one of {EXPERIENCE_LEVELS[1:]}")
    clean = [i.strip()[:40] for i in (interests or []) if i and i.strip()][:10]
    g.query(
        """
        MATCH (a:Attendee {code: $a})
        SET a.role = $role, a.experience = $experience, a.interests = $interests, a.profile_updated_at = $at
        """,
        {"a": attendee, "role": (role or "").strip()[:60], "experience": experience, "interests": clean, "at": _now()},
    )
    return get_profile(g, attendee)


def get_profile(g: Graph, attendee: str) -> dict:
    rows = g.query(
        "MATCH (a:Attendee {code: $a}) RETURN a.role, a.experience, a.interests, a.profile_updated_at", {"a": attendee}
    ).result_set
    if not rows or rows[0][3] is None:
        return {}
    role, experience, interests, updated_at = rows[0]
    return {"role": role or "", "experience": experience or "", "interests": interests or [], "updated_at": updated_at}


TARGET_FIELDS = ["code", "title", "day", "start", "end", "room"]


def add_target(g: Graph, attendee: str, talk: str) -> list[dict]:
    g.query(
        "MATCH (a:Attendee {code: $a}), (t:Talk {code: $t}) MERGE (a)-[r:TARGETS]->(t) SET r.at = $at",
        {"a": attendee, "t": talk, "at": _now()},
    )
    return targets(g, attendee)


def remove_target(g: Graph, attendee: str, talk: str) -> list[dict]:
    g.query("MATCH (:Attendee {code: $a})-[r:TARGETS]->(:Talk {code: $t}) DELETE r", {"a": attendee, "t": talk})
    return targets(g, attendee)


def targets(g: Graph, attendee: str) -> list[dict]:
    rows = g.query(
        "MATCH (:Attendee {code: $a})-[:TARGETS]->(t:Talk) "
        "RETURN t.code, t.title, t.day, t.start, t.end, t.room ORDER BY t.start_min",
        {"a": attendee},
    ).result_set
    return [dict(zip(TARGET_FIELDS, r)) for r in rows]


def chat_history(g: Graph, attendee: str) -> list[dict]:
    rows = g.query("MATCH (a:Attendee {code: $a}) RETURN a.chat", {"a": attendee}).result_set
    if not rows or not rows[0][0]:
        return []
    try:
        return json.loads(rows[0][0])
    except ValueError:
        return []


def append_chat(g: Graph, attendee: str, messages: list[dict]) -> None:
    stamped = [{**m, "at": m.get("at") or _now()} for m in messages]
    history = (chat_history(g, attendee) + stamped)[-CHAT_LIMIT:]
    g.query("MATCH (a:Attendee {code: $a}) SET a.chat = $chat", {"a": attendee, "chat": json.dumps(history)})


def clear_chat(g: Graph, attendee: str) -> None:
    g.query("MATCH (a:Attendee {code: $a}) SET a.chat = NULL", {"a": attendee})


def forget_attendee(g: Graph, attendee: str) -> None:
    g.query("MATCH (a:Attendee {code: $code}) DETACH DELETE a", {"code": attendee})


# --- learning path ---------------------------------------------------------

def learning_path(g: Graph, talk: str, attendee: str | None = None) -> dict:
    """Concepts still to learn for this talk, prerequisites first. Empty means "You're ready"."""
    params = {"talk": talk, "attendee": attendee or ""}
    roots = g.query(PATH_ROOTS, params).result_set
    links = g.query(PATH_LINKS, params).result_set
    known = dict(g.query(KNOWN, params).result_set) if attendee else {}

    names = {cid: name for cid, name, *_ in roots}
    needs = {}  # concept -> concepts it depends on
    for src, dst, dst_name, support, via in links:
        names[dst] = dst_name
        needs.setdefault(src, []).append({"concept": dst, "support": support, "via": via})

    # Walk from the talk's required concepts; stop at anything the attendee already knows.
    required = [cid for cid, *_ in roots]
    needed, frontier = [], [c for c in required if c not in known]
    while frontier:
        cid = frontier.pop(0)
        if cid in needed:
            continue
        needed.append(cid)
        frontier += [d["concept"] for d in needs.get(cid, []) if d["concept"] not in known]

    # Order so every concept comes after the concepts it depends on.
    ordered, placed = [], set()

    def place(cid: str, seen: frozenset = frozenset()) -> None:
        if cid in placed or cid in seen:
            return
        for d in needs.get(cid, []):
            if d["concept"] in needed:
                place(d["concept"], seen | {cid})
        placed.add(cid)
        ordered.append(cid)

    for cid in needed:
        place(cid)

    root_info = {cid: {"evidence": ev, "status": st} for cid, _, ev, st in roots}
    steps = [
        {
            "concept": cid,
            "name": names.get(cid, cid),
            "required_by_talk": root_info.get(cid),
            "depends_on": [d for d in needs.get(cid, []) if d["concept"] in needed],
        }
        for cid in ordered
    ]
    return {
        "talk": talk,
        "ready": not steps,
        "steps": steps,
        "already_known": [{"concept": c, "how": how} for c, how in known.items() if c in names],
        "queries": [PATH_ROOTS.strip(), PATH_LINKS.strip()] + ([KNOWN] if attendee else []),
    }


# --- day plan --------------------------------------------------------------

def choose_teaching_talk(candidates: list[dict], planned: list[dict]) -> tuple[dict | None, str | None]:
    """Pick where to learn one concept from the talks that teach it in the allowed window.

    candidates: talks that teach the concept, start after the clock (and after the
                steps it depends on) and end before the target talk, sorted by start time.
                Each has code, title, start_min, end_min, ...
    planned:    talks already chosen for earlier steps of this plan.

    Returns (chosen talk or None, a note for the screen or None). The note is how
    clashes get explained, e.g. "Clashes with <planned talk>; using <substitute> instead".
    Return (None, None) when nothing fits; the caller falls back to an outside explainer.
    """
    planned_codes = {p["code"] for p in planned}
    for c in candidates:  # one hour that covers two steps beats two hours
        if c["code"] in planned_codes:
            return c, f"Already in your plan: {c['title']} covers this too."
    # For learning the basics: introductory talks first, then non-sponsored ones, then the earliest.
    ranked = sorted(candidates, key=lambda c: (c.get("level_num") != 100, bool(c.get("sponsor")), c["start_min"]))
    skipped = None
    for c in ranked:  # best talk that doesn't clash with the plan so far
        clash = next((p for p in planned if overlaps(c, p)), None)
        if clash is None:
            note = f"{skipped[0]['title']} clashes with {skipped[1]['title']}; using {c['title']} instead." if skipped else None
            return c, note
        skipped = skipped or (c, clash)
    if skipped:
        return None, f"Every talk that teaches this clashes with your plan ({skipped[0]['title']} vs {skipped[1]['title']})."
    return None, None


def overlaps(a: dict, b: dict) -> bool:
    return a["start_min"] < b["end_min"] and b["start_min"] < a["end_min"]


def plan_day(g: Graph, talk: str, attendee: str | None = None) -> dict:
    """Greedy plan: walk the path in order and give each concept a talk or an explainer."""
    path = learning_path(g, talk, attendee)
    target = g.query(
        "MATCH (t:Talk {code: $talk}) RETURN t.start_min, t.title", {"talk": talk}
    ).result_set
    if not target:
        raise ValueError(f"No talk with code {talk}")
    deadline, target_title = target[0]
    clock = attendee_clock(g, attendee) if attendee else None
    if clock is None:
        date, time = settings.clock_start.split("T")
        clock = to_minutes(date, time)

    planned, plan, ready_at = [], [], {}
    for step in path["steps"]:
        # A step can't start before the talks for the concepts it depends on have ended.
        after = max([clock] + [ready_at[d["concept"]] for d in step["depends_on"] if d["concept"] in ready_at])
        rows = g.query(TEACHERS, {"concept": step["concept"], "after": after, "before": deadline, "target": talk}).result_set
        candidates = [dict(zip(TEACHER_KEYS, r)) for r in rows]
        chosen, note = choose_teaching_talk(candidates, planned)
        if chosen:
            if chosen not in planned:
                planned.append(chosen)
            ready_at[step["concept"]] = chosen["end_min"]
            plan.append({**step, "learn_at": {"kind": "talk", **chosen}, "note": note})
            continue
        explainer = g.query(EXPLAINERS, {"concept": step["concept"]}).result_set
        learn_at = (
            {"kind": "explainer", **dict(zip(["url", "title", "minutes", "fetched_at", "evidence"], explainer[0]))}
            if explainer else {"kind": "needs_explainer"}
        )
        ready_at[step["concept"]] = after
        plan.append({**step, "learn_at": learn_at, "note": note or "No talk teaches this before your talk starts."})

    return {
        "talk": talk,
        "talk_title": target_title,
        "clock_min": clock,
        "ready": path["ready"],
        "plan": plan,
        "already_known": path["already_known"],
        "queries": path["queries"] + [TEACHERS.strip(), EXPLAINERS.strip()],
    }
