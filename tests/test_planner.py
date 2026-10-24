"""Planner tests on a small hand-made graph, shaped like the "Own your Copilot" chain.

TARGET (Thu 11:30) requires "customization" and "skills".
CUSTOM teaches customization and requires "basics", so customization depends on basics.
SKILLS_A teaches skills at the same time as CUSTOM; SKILLS_B teaches it later that morning.
"""

import pytest

from throughline.catalog import to_minutes
from throughline.graph import connect, ensure_schema, load_talks
from throughline.knowledge import derive_depends_on, load_concepts, load_edges
from throughline.planner import (
    forget_attendee, learning_path, mark_attended, mark_known, new_attendee, plan_day,
)


def talk(code, date, start, end, abstract):
    return {
        "code": code, "session_id": code, "title": code.title(), "type": "Breakout Session",
        "level": None, "level_num": None, "topics": [], "sponsor": False, "date": date,
        "day": "Wednesday" if date.endswith("28") else "Thursday", "start": start, "end": end,
        "start_min": to_minutes(date, start), "end_min": to_minutes(date, end), "room": "Room 1",
        "speakers": [], "abstract": abstract, "url": f"https://example.com/{code}",
    }


TALKS = [
    talk("TARGET", "2026-10-29", "11:30", "13:00", "You already customize Copilot and write agent skills daily."),
    talk("CUSTOM", "2026-10-29", "09:00", "09:45", "Learn every customization layer, assuming you know Copilot basics well."),
    talk("SKILLS_A", "2026-10-29", "09:00", "09:45", "A practical guide to agent skills for teams."),
    talk("SKILLS_B", "2026-10-29", "10:15", "11:00", "Build agent skills from scratch in this lab."),
    talk("BASICS", "2026-10-28", "10:30", "10:45", "An introduction to Copilot basics for everyone."),
    talk("LATE", "2026-10-29", "14:00", "14:30", "Another look at every customization layer here."),
    talk("PANEL", "2026-10-29", "15:00", "15:30", "A forward-looking panel on what comes next."),
    talk("MCPTALK", "2026-10-29", "16:00", "16:30", "Securing your own MCP servers in production."),
]
CONCEPTS = [
    {"id": c, "name": c.title(), "aliases": [], "definition": ""}
    for c in ("basics", "customization", "skills", "mcp")
]
EDGES = [
    {"type": "REQUIRES", "talk": "TARGET", "concept": "customization", "evidence": "already customize Copilot"},
    {"type": "REQUIRES", "talk": "TARGET", "concept": "skills", "evidence": "write agent skills daily"},
    {"type": "TEACHES", "talk": "CUSTOM", "concept": "customization", "evidence": "every customization layer"},
    {"type": "REQUIRES", "talk": "CUSTOM", "concept": "basics", "evidence": "you know Copilot basics"},
    {"type": "TEACHES", "talk": "SKILLS_A", "concept": "skills", "evidence": "guide to agent skills"},
    {"type": "TEACHES", "talk": "SKILLS_B", "concept": "skills", "evidence": "Build agent skills from scratch"},
    {"type": "TEACHES", "talk": "BASICS", "concept": "basics", "evidence": "introduction to Copilot basics"},
    {"type": "TEACHES", "talk": "LATE", "concept": "customization", "evidence": "every customization layer"},
    {"type": "REQUIRES", "talk": "MCPTALK", "concept": "mcp", "evidence": "your own MCP servers"},
    # Paraphrased evidence, so it must be discarded:
    {"type": "TEACHES", "talk": "PANEL", "concept": "mcp", "evidence": "explains how MCP works"},
]


@pytest.fixture(scope="module")
def g():
    try:
        graph = connect("throughline_test_planner", local=True)
        graph.query("RETURN 1")
    except Exception as e:
        pytest.skip(f"FalkorDB not reachable: {e}")
    ensure_schema(graph)
    load_talks(graph, TALKS)
    load_concepts(graph, CONCEPTS)
    graph.report = load_edges(graph, EDGES)
    derive_depends_on(graph)
    yield graph
    graph.delete()


def concepts(path):
    return [s["concept"] for s in path["steps"]]


def test_evidence_check_drops_paraphrased_edge(g):
    assert g.report["kept"] == 9
    assert [e["talk"] for e in g.report["discarded_edges"]] == ["PANEL"]


def test_depends_on_is_derived_from_the_teaching_talk(g):
    rows = g.query("MATCH (a:Concept)-[d:DEPENDS_ON]->(b:Concept) RETURN a.id, b.id, d.via").result_set
    assert rows == [["customization", "basics", ["CUSTOM"]]]


def test_path_puts_prerequisites_first(g):
    steps = concepts(learning_path(g, "TARGET"))
    assert set(steps) == {"basics", "customization", "skills"}
    assert steps.index("basics") < steps.index("customization")


def test_knowing_a_concept_also_skips_what_it_depends_on(g):
    attendee = new_attendee(g)
    mark_known(g, attendee, "customization")
    assert concepts(learning_path(g, "TARGET", attendee)) == ["skills"]
    forget_attendee(g, attendee)


def test_talk_with_no_requirements_is_ready(g):
    path = learning_path(g, "PANEL")
    assert path["ready"] and path["steps"] == []


def test_attending_learns_what_the_talk_teaches_and_moves_the_clock(g):
    attendee = new_attendee(g)
    assert mark_attended(g, attendee, "BASICS") == ["basics"]
    clock = g.query("MATCH (a:Attendee {code: $c}) RETURN a.clock_min", {"c": attendee}).result_set[0][0]
    assert clock == to_minutes("2026-10-28", "10:45")
    assert "basics" not in concepts(learning_path(g, "TARGET", attendee))
    forget_attendee(g, attendee)
    assert g.query("MATCH (a:Attendee {code: $c}) RETURN count(a)", {"c": attendee}).result_set[0][0] == 0


def test_plan_fits_the_window_and_never_double_books(g):
    plan = plan_day(g, "TARGET")["plan"]
    talks = [p["learn_at"] for p in plan if p["learn_at"]["kind"] == "talk"]
    deadline = to_minutes("2026-10-29", "11:30")
    for t in talks:
        assert t["end_min"] <= deadline and t["code"] not in {"TARGET", "LATE"}
    for i, a in enumerate(talks):
        for b in talks[i + 1:]:
            assert a["code"] == b["code"] or a["end_min"] <= b["start_min"] or b["end_min"] <= a["start_min"]


def test_plan_respects_dependency_order(g):
    plan = {p["concept"]: p["learn_at"] for p in plan_day(g, "TARGET")["plan"]}
    assert plan["basics"]["code"] == "BASICS"
    assert plan["customization"]["start_min"] >= plan["basics"]["end_min"]


def test_clash_is_flagged_with_a_substitute(g):
    skills = next(p for p in plan_day(g, "TARGET")["plan"] if p["concept"] == "skills")
    assert skills["learn_at"]["code"] == "SKILLS_B"
    assert skills["note"]


def test_untaught_concept_falls_back_to_an_explainer(g):
    (step,) = plan_day(g, "MCPTALK")["plan"]
    assert step["learn_at"]["kind"] == "needs_explainer"
