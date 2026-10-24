"""The graph endpoint's shape, on the same hand-made graph as the planner tests."""

import pytest

from tests.test_planner import CONCEPTS, EDGES, TALKS
from throughline.graph import connect, ensure_schema, load_talks
from throughline.graphview import graph_for_talk
from throughline.knowledge import derive_depends_on, load_concepts, load_edges
from throughline.planner import forget_attendee, mark_known, new_attendee


@pytest.fixture(scope="module")
def g():
    try:
        graph = connect("throughline_test_graphview", local=True)
        graph.query("RETURN 1")
    except Exception as e:
        pytest.skip(f"FalkorDB not reachable: {e}")
    ensure_schema(graph)
    load_talks(graph, TALKS)
    load_concepts(graph, CONCEPTS)
    load_edges(graph, EDGES)
    derive_depends_on(graph)
    yield graph
    graph.delete()


def test_nodes_and_edges_for_the_plan(g):
    view = graph_for_talk(g, "TARGET")
    ids = {n["id"] for n in view["nodes"]}
    assert {"talk:TARGET", "concept:customization", "concept:skills", "concept:basics"} <= ids
    assert next(n for n in view["nodes"] if n["id"] == "talk:TARGET")["type"] == "target"
    edge = lambda s, t, kind: next(e for e in view["edges"] if (e["source"], e["target"], e["type"]) == (s, t, kind))
    assert edge("concept:customization", "concept:basics", "DEPENDS_ON")
    # SKILLS_B is in the plan; SKILLS_A (it clashes) is shown as a faded alternative
    assert edge("talk:SKILLS_B", "concept:skills", "TEACHES")["chosen"] is True
    assert edge("talk:SKILLS_A", "concept:skills", "TEACHES")["chosen"] is False
    for e in view["edges"]:
        assert e["source"] in ids and e["target"] in ids


def test_known_concepts_stay_visible_as_done(g):
    attendee = new_attendee(g)
    mark_known(g, attendee, "customization")
    view = graph_for_talk(g, "TARGET", attendee)
    custom = next(n for n in view["nodes"] if n["id"] == "concept:customization")
    assert custom["data"]["known"] is True
    assert next(e for e in view["edges"] if e["target"] == "concept:customization" and e["type"] == "REQUIRES")["chosen"] is False
    forget_attendee(g, attendee)


def test_ready_talk_is_just_the_target(g):
    view = graph_for_talk(g, "PANEL")
    assert view["ready"] and [n["id"] for n in view["nodes"]] == ["talk:PANEL"]
