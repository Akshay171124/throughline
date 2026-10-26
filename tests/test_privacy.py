"""Free-form Cypher (the agent's GraphRAG tool) must never reveal attendee codes or memory."""

import json
import re

import pytest

from throughline.agent import Tools
from throughline.graph import connect, publish_public_view
from throughline.planner import CODE_ALPHABET, mark_known, new_attendee, new_code


@pytest.fixture(scope="module")
def graphs():
    try:
        g = connect("throughline_test_privacy", local=True)
        g.query("RETURN 1")
    except Exception as e:
        pytest.skip(f"FalkorDB not reachable: {e}")
    g.query("CREATE (:Talk {code: 'T1', title: 'A talk'}), (:Concept {id: 'mcp', name: 'MCP'})")
    code = new_attendee(g)
    mark_known(g, code, "mcp")
    view = publish_public_view(g)
    yield g, view, code
    g.delete()
    view.delete()


@pytest.mark.parametrize("cypher", [
    "MATCH (n) RETURN n",
    "MATCH (n) WHERE n.code IS NOT NULL RETURN n.code",
    "MATCH (n)-[r]->(m) RETURN n, r, m",
    "MATCH p = ()-[]->() RETURN p",
    "CALL db.labels() YIELD label RETURN label",
])
def test_queries_that_never_name_attendees_still_cant_see_them(graphs, cypher):
    g, view, code = graphs
    result, _ = Tools(g, code, public=view).run_cypher(cypher)
    dumped = json.dumps(result, default=str)
    assert code not in dumped  # the code is the only key to someone's memory
    assert "clock_min" not in dumped and '"how"' not in dumped  # no attendee node or KNOWS edge data
    # (db.labels() may still list the label name "Attendee": FalkorDB keeps label names in a
    # copied graph's schema after the nodes are deleted. Names aren't data.)


@pytest.mark.parametrize("cypher", [
    "MATCH (a:Attendee) RETURN a.code",
    "MATCH ()-[k:KNOWS]->(c) RETURN c",
    "match (a:attendee) return a",
])
def test_queries_naming_attendee_data_are_refused(graphs, cypher):
    g, view, code = graphs
    result, _ = Tools(g, code, public=view).run_cypher(cypher)
    assert "error" in result


def test_the_attendee_still_sees_their_own_memory(graphs):
    g, view, code = graphs
    state, _ = Tools(g, code, public=view).get_attendee()
    assert [k["concept"] for k in state["known"]] == ["mcp"]


def test_codes_are_long_and_unambiguous():
    codes = {new_code() for _ in range(200)}
    assert len(codes) == 200
    for c in codes:
        assert re.fullmatch(rf"[{CODE_ALPHABET}]{{4}}-[{CODE_ALPHABET}]{{4}}-[{CODE_ALPHABET}]{{4}}", c)


def test_the_public_view_is_built_without_ever_holding_attendees(monkeypatch):
    # It is rebuilt while a map is live (after its explainers run), so it is made in a staging copy:
    # the public name only ever receives a copy that has no Attendee nodes.
    from falkordb import Graph
    try:
        g = connect("throughline_test_privacy_staging", local=True)
        g.query("RETURN 1")
    except Exception as e:
        pytest.skip(f"FalkorDB not reachable: {e}")
    g.query("CREATE (:Talk {code: 'T1', title: 'A talk'})")
    new_attendee(g)
    copies, real_copy = [], Graph.copy

    def copy(self, clone):
        attendees = self.query("MATCH (a:Attendee) RETURN count(a)").result_set[0][0]
        copies.append((self.name, clone, attendees))
        return real_copy(self, clone)

    monkeypatch.setattr(Graph, "copy", copy)
    try:
        view = publish_public_view(g)
        publish_public_view(g)  # again, over an existing view
        public = "throughline_test_privacy_staging_public"
        assert view.name == public
        assert [c for c in copies if c[1] == public] and all(n == 0 for _, clone, n in copies if clone == public)
        assert view.query("MATCH (a:Attendee) RETURN count(a)").result_set[0][0] == 0
        assert view.query("MATCH (t:Talk) RETURN count(t)").result_set[0][0] == 1
        from falkordb import FalkorDB
        from throughline.config import settings
        names = FalkorDB(host=settings.falkordb_host, port=settings.falkordb_port).list_graphs()
        assert public in names and public + "_next" not in names
    finally:
        g.delete()
        connect("throughline_test_privacy_staging_public", local=True).delete()
