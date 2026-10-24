"""The landing page's talk flow, on the planner tests' hand-made graph."""

import pytest

from tests.test_planner import CONCEPTS, EDGES, TALKS
from throughline import flow, planner
from throughline.graph import connect, ensure_schema, load_talks
from throughline.knowledge import derive_depends_on, load_concepts, load_edges


@pytest.fixture(scope="module")
def g():
    try:
        graph = connect("throughline_test_flow", local=True)
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


def edge_pairs(view):
    return {(e["source"], e["target"]) for e in view["edges"]}


def test_prepares_edges_only_go_forward_in_time(g):
    view = flow.flow(g)
    pairs = edge_pairs(view)
    assert ("BASICS", "CUSTOM") in pairs
    # Three talks tie for TARGET; the two drawn are the closest in time, then by code.
    assert {a for a, b in pairs if b == "TARGET"} == {"SKILLS_B", "CUSTOM"}
    assert flow.flow(g)["edges"] == view["edges"]  # same picture on every load
    assert ("LATE", "TARGET") not in pairs  # LATE teaches customization, but after TARGET starts
    starts = {n["code"]: n["start_min"] for n in view["nodes"]}
    ends = {n["code"]: n["end_min"] for n in view["nodes"]}
    for a, b in pairs:
        assert ends[a] <= starts[b]


def test_each_talk_keeps_only_its_strongest_incoming_links(g):
    view = flow.flow(g)
    incoming = {}
    for e in view["edges"]:
        incoming[e["target"]] = incoming.get(e["target"], 0) + 1
    assert max(incoming.values()) <= flow.EDGES_PER_TALK
    target = next(n for n in view["nodes"] if n["code"] == "TARGET")
    assert target["builds_on"] >= 2  # CUSTOM, SKILLS_A, SKILLS_B all prepare for it


def test_ready_reflects_what_the_attendee_knows(g):
    code = planner.new_attendee(g)
    try:
        assert next(n for n in flow.flow(g, code)["nodes"] if n["code"] == "TARGET")["ready"] is False
        planner.mark_known(g, code, "customization")
        planner.mark_known(g, code, "skills")
        assert next(n for n in flow.flow(g, code)["nodes"] if n["code"] == "TARGET")["ready"] is True
        assert all(n["ready"] is None for n in flow.flow(g)["nodes"])  # no attendee, no readiness
    finally:
        planner.forget_attendee(g, code)


def test_featured_has_reasons_and_is_in_time_order(g):
    cards = flow.featured(g)
    assert cards and all(c["reason"] for c in cards)
    assert [c["start_min"] for c in cards] == sorted(c["start_min"] for c in cards)
    assert any(c["reason"].startswith("Prepares you for") for c in cards)
