"""The goal chat's talk ranking: the first concept the model gives counts most."""

import pytest

from tests.test_planner import CONCEPTS, EDGES, TALKS
from throughline.agent import Tools
from throughline.graph import connect, ensure_schema, load_talks
from throughline.knowledge import load_concepts, load_edges


@pytest.fixture(scope="module")
def g():
    try:
        graph = connect("throughline_test_goal_ranking", local=True)
        graph.query("RETURN 1")
    except Exception as e:
        pytest.skip(f"FalkorDB not reachable: {e}")
    ensure_schema(graph)
    load_talks(graph, TALKS)
    load_concepts(graph, CONCEPTS)
    load_edges(graph, EDGES)
    # One talk covers two side concepts; it must not outrank talks teaching the main one.
    graph.query("MATCH (t:Talk {code: 'BASICS'}), (c:Concept {id: 'customization'}) "
                "MERGE (t)-[:TEACHES {evidence: 'x', confidence: 1.0, status: 'ok'}]->(c)")
    yield graph
    graph.delete()


def test_main_concept_outranks_several_side_concepts(g):
    tools = Tools(g, "nobody")
    result, _ = tools.talks_for_concepts(["skills", "customization", "basics"])
    top_two = {t["code"] for t in sorted(result["talks"], key=lambda t: -t["score"])[:2]}
    assert top_two == {"SKILLS_A", "SKILLS_B"}  # they teach the goal's main concept
    assert [s["code"] for s in tools.suggestions] == [t["code"] for t in result["talks"]]  # cards match the picks
