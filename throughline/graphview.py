"""The path behind a plan as nodes and edges, ready for the page to draw.

  target talk -REQUIRES-> concept -DEPENDS_ON-> concept
  teaching talk -TEACHES-> concept        (chosen=True for the one in the plan)
  explainer -EXPLAINS-> concept

Concepts the attendee already knows are included (data.known=True) so the page
can show them as done instead of hiding them.
"""

from falkordb import Graph

from . import planner

MAX_ALTERNATIVES = 3  # other teaching talks per concept, besides the chosen one


def _talk_node(row: dict, node_type: str = "talk") -> dict:
    return {
        "id": f"talk:{row['code']}",
        "type": node_type,
        "label": row["title"],
        "data": {k: row.get(k) for k in ("code", "day", "start", "end", "room", "level_num", "sponsor")},
    }


def graph_for_talk(g: Graph, talk: str, attendee: str | None = None) -> dict:
    plan = planner.plan_day(g, talk, attendee)
    target = g.query(
        "MATCH (t:Talk {code: $talk}) RETURN t.code, t.title, t.day, t.start, t.end, t.room, t.level_num, t.sponsor, t.start_min",
        {"talk": talk},
    ).result_set[0]
    keys = ["code", "title", "day", "start", "end", "room", "level_num", "sponsor"]
    target_row = dict(zip(keys, target[:8]))
    deadline = target[8]
    nodes = {f"talk:{talk}": _talk_node(target_row, "target")}
    edges = []

    # Everything the talk requires, including concepts already known (shown as done).
    required = g.query(
        "MATCH (:Talk {code: $talk})-[r:REQUIRES]->(c:Concept) RETURN c.id, r.evidence, r.status",
        {"talk": talk},
    ).result_set
    known = {k["concept"] for k in plan["already_known"]}
    if attendee:
        known |= {r[0] for r in g.query(planner.KNOWN, {"attendee": attendee}).result_set}
    concept_ids = {cid for cid, *_ in required} | {s["concept"] for s in plan["plan"]}
    for cid, evidence, status in required:
        edges.append({"source": f"talk:{talk}", "target": f"concept:{cid}", "type": "REQUIRES",
                      "evidence": evidence, "status": status, "chosen": cid not in known})

    for row in g.query(
        "MATCH (c:Concept) WHERE c.id IN $ids RETURN c.id, c.name, c.definition", {"ids": sorted(concept_ids)}
    ).result_set:
        cid, name, definition = row
        nodes[f"concept:{cid}"] = {"id": f"concept:{cid}", "type": "concept", "label": name,
                                   "data": {"concept": cid, "definition": definition, "known": cid in known}}

    for a, b, evidence, via in g.query(
        "MATCH (a:Concept)-[d:DEPENDS_ON]->(b:Concept) WHERE a.id IN $ids AND b.id IN $ids "
        "RETURN a.id, b.id, d.evidence, d.via",
        {"ids": sorted(concept_ids)},
    ).result_set:
        edges.append({"source": f"concept:{a}", "target": f"concept:{b}", "type": "DEPENDS_ON",
                      "evidence": "; ".join(evidence or []), "status": "ok", "chosen": True, "via": via})

    clock = plan["clock_min"]
    for step in plan["plan"]:
        at, cid = step["learn_at"], step["concept"]
        chosen_code = at.get("code") if at["kind"] == "talk" else None
        rows = g.query(planner.TEACHERS, {"concept": cid, "after": clock, "before": deadline, "target": talk}).result_set
        teachers = [dict(zip(planner.TEACHER_KEYS, r)) for r in rows]
        teachers.sort(key=lambda t: t["code"] != chosen_code)  # chosen first, then by time
        for t in teachers[: MAX_ALTERNATIVES + (1 if chosen_code else 0)]:
            nodes.setdefault(f"talk:{t['code']}", _talk_node(t))
            edges.append({"source": f"talk:{t['code']}", "target": f"concept:{cid}", "type": "TEACHES",
                          "evidence": t["evidence"], "status": "ok", "chosen": t["code"] == chosen_code})
        if at["kind"] == "explainer":
            node_id = f"explainer:{at['url']}"
            nodes[node_id] = {"id": node_id, "type": "explainer", "label": at.get("title") or at["url"],
                              "data": {"url": at["url"], "fetched_at": at.get("fetched_at")}}
            edges.append({"source": node_id, "target": f"concept:{cid}", "type": "EXPLAINS",
                          "evidence": at.get("evidence"), "status": "ok", "chosen": True})

    return {"talk": talk, "ready": plan["ready"], "clock_min": clock, "nodes": list(nodes.values()), "edges": edges}
