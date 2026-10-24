import json

import pytest

from throughline.catalog import extract_items, normalize_items
from throughline.config import settings
from throughline.graph import connect, ensure_schema, load_talks


@pytest.fixture(scope="module")
def graph():
    try:
        g = connect("throughline_test", local=True)
        g.query("RETURN 1")
    except Exception as e:  # FalkorDB isn't running
        pytest.skip(f"FalkorDB not reachable: {e}")
    raw = json.loads(settings.raw_snapshot.read_text(encoding="utf-8"))
    ensure_schema(g)
    load_talks(g, normalize_items(extract_items(raw)))
    yield g
    g.delete()


def scalar(g, query, params=None):
    return g.query(query, params or {}).result_set[0][0]


def test_all_talks_loaded_with_a_slot(graph):
    assert scalar(graph, "MATCH (t:Talk) RETURN count(t)") == 125
    assert scalar(graph, "MATCH (t:Talk) WHERE NOT (t)-[:IN_SLOT]->(:TimeSlot) RETURN count(t)") == 0
    assert scalar(graph, "MATCH (t:Talk)-[:PART_OF]->(:Conference {id: 'universe26'}) RETURN count(t)") == 125


def test_reloading_is_idempotent(graph):
    raw = json.loads(settings.raw_snapshot.read_text(encoding="utf-8"))
    load_talks(graph, normalize_items(extract_items(raw)))
    assert scalar(graph, "MATCH (t:Talk) RETURN count(t)") == 125
    assert scalar(graph, "MATCH (:Talk)-[r:IN_SLOT]->() RETURN count(r)") == 125


def test_talks_in_the_same_slot_share_one_timeslot(graph):
    shared = scalar(
        graph,
        "MATCH (s:TimeSlot)<-[:IN_SLOT]-(t:Talk) WITH s, count(t) AS n WHERE n > 1 RETURN count(s)",
    )
    assert shared > 0
