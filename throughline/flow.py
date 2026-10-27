"""The conference as a flow of talks, for the landing page.

An edge A -> B means "A prepares you for B": A teaches a concept B requires, and A
ends before B starts. Every talk keeps only its strongest few incoming edges (most
shared concepts, then the closest in time), so the picture reads as a flow, not a
hairball. "Prepares"/"builds on" counts use every edge, not just the drawn ones.
"""

from collections import defaultdict

from falkordb import Graph

from . import planner

EDGES_PER_TALK = 2
UNLOCKER_PICKS = 6
FEATURED_MAX = 8
HEADLINE_TYPES = ("Keynote", "Main Stage")

PREPARES = """
MATCH (a:Talk)-[:TEACHES]->(c:Concept)<-[:REQUIRES]-(b:Talk)
WHERE a.end_min <= b.start_min AND a <> b
RETURN a.code, b.code, collect(DISTINCT c.name), count(DISTINCT c), a.end_min
"""
TALKS = """
MATCH (t:Talk)
RETURN t.code, t.title, t.day, t.date, t.start, t.end, t.start_min, t.end_min, t.level_num, t.type, t.room, t.sponsor
"""
TALK_KEYS = ["code", "title", "day", "date", "start", "end", "start_min", "end_min", "level_num", "type", "room", "sponsor"]


def _short(title: str, limit: int = 42) -> str:
    head = title.split(":")[0].strip() if ":" in title and len(title.split(":")[0]) >= 12 else title
    return head if len(head) <= limit else head[: limit - 1].rstrip() + "…"


def ready_map(g: Graph, attendee: str | None) -> dict[str, bool] | None:
    """For each talk: is everything it requires already known (by memory or profile)?"""
    if not attendee:
        return None
    known = {r[0] for r in g.query(planner.KNOWN, {"attendee": attendee}).result_set}
    if planner.get_profile(g, attendee).get("experience") in ("some", "experienced"):
        known |= {r[0] for r in g.query(planner.BASICS).result_set}
    required = defaultdict(set)
    for code, cid in g.query("MATCH (t:Talk)-[:REQUIRES]->(c:Concept) RETURN t.code, c.id").result_set:
        required[code].add(cid)
    codes = [r[0] for r in g.query("MATCH (t:Talk) RETURN t.code").result_set]
    return {code: required[code] <= known for code in codes}


def _all_edges(g: Graph):
    return g.query(PREPARES).result_set


def _counts(rows) -> tuple[dict, dict]:
    prepares, builds_on = defaultdict(set), defaultdict(set)
    for a, b, *_ in rows:
        prepares[a].add(b)
        builds_on[b].add(a)
    return prepares, builds_on


def flow(g: Graph, attendee: str | None = None, include: list[str] | None = None) -> dict:
    """`include`: talks that must be on the map (e.g. the agent's picks), with every link between them."""
    talks = {r[0]: dict(zip(TALK_KEYS, r)) for r in g.query(TALKS).result_set}
    rows = _all_edges(g)
    prepares, builds_on = _counts(rows)
    include = [c for c in (include or []) if c in talks][:20]

    incoming = defaultdict(list)
    for a, b, concepts, weight, a_end in rows:
        incoming[b].append((weight, a_end, a, concepts))
    edges, drawn = [], set()
    for b, options in incoming.items():
        # most shared concepts, then the closest in time, then by code so the picture never changes on reload
        options.sort(key=lambda o: (-o[0], -o[1], o[2]))
        for weight, _, a, concepts in options[:EDGES_PER_TALK]:
            edges.append({"source": a, "target": b, "concepts": sorted(concepts), "weight": weight})
            drawn.add((a, b))
    wanted = set(include)
    for a, b, concepts, weight, _ in rows:  # links among the included talks, even if not the strongest
        if a in wanted and b in wanted and (a, b) not in drawn:
            edges.append({"source": a, "target": b, "concepts": sorted(concepts), "weight": weight})
            drawn.add((a, b))

    # FalkorDB returns rows in no fixed order; sort so every load draws the same picture.
    edges.sort(key=lambda e: (talks[e["target"]]["start_min"], e["target"], talks[e["source"]]["start_min"], e["source"]))
    must_see = {c for c, _ in _featured_codes(talks, prepares)}
    shown = {e["source"] for e in edges} | {e["target"] for e in edges} | must_see | wanted
    ready = ready_map(g, attendee)
    nodes = [
        {
            **talks[code], "short_title": _short(talks[code]["title"]),
            "ready": ready.get(code) if ready is not None else None,
            "must_see": code in must_see,
            "prepares": len(prepares[code]), "builds_on": len(builds_on[code]),
        }
        for code in sorted(shown, key=lambda c: (talks[c]["start_min"], c))
    ]
    day_starts = {}
    for t in talks.values():
        day_starts[t["date"]] = min(day_starts.get(t["date"], t["start_min"]), t["start_min"])
    return {"nodes": nodes, "edges": edges, "day_starts": day_starts, "talks_total": len(talks),
            "links_total": len(rows)}


def _featured_codes(talks: dict, prepares: dict) -> list[tuple[str, str]]:
    """Keynotes first, then the talks that prepare you for the most others."""
    picks = [(c, "Keynote") for c, t in talks.items() if t["type"] == "Keynote"]
    unlockers = sorted(
        (c for c in talks if c not in dict(picks) and prepares.get(c)),
        key=lambda c: (-len(prepares[c]), talks[c]["start_min"]),
    )
    for c in unlockers[:UNLOCKER_PICKS]:
        n = len(prepares[c])
        reason = f"Prepares you for {n} {'talk' if n == 1 else 'talks'}"
        if talks[c]["type"] == "Main Stage":
            reason = f"Main stage · {reason[0].lower()}{reason[1:]}"
        picks.append((c, reason))
    if len(picks) < FEATURED_MAX:  # fill with main-stage sessions
        for c, t in sorted(talks.items(), key=lambda kv: kv[1]["start_min"]):
            if t["type"] == "Main Stage" and c not in dict(picks):
                picks.append((c, "Main stage"))
            if len(picks) >= FEATURED_MAX:
                break
    return picks[:FEATURED_MAX]


def featured(g: Graph, attendee: str | None = None) -> list[dict]:
    talks = {r[0]: dict(zip(TALK_KEYS, r)) for r in g.query(TALKS).result_set}
    prepares, _ = _counts(_all_edges(g))
    ready = ready_map(g, attendee)
    picks = _featured_codes(talks, prepares)
    cards = [
        {**{k: talks[c][k] for k in ("code", "title", "day", "start", "end", "room", "level_num", "type")},
         "start_min": talks[c]["start_min"], "reason": reason,
         "ready": ready.get(c) if ready is not None else None}
        for c, reason in picks
    ]
    return sorted(cards, key=lambda card: card["start_min"])
