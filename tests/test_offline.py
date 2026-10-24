import pytest

from throughline.graph import connect
from throughline.offline import copy_graph, counts, fingerprint, read_graph

SRC, DST = "throughline_test_offline_src", "throughline_test_offline_dst"


@pytest.fixture(scope="module")
def graphs():
    try:
        src = connect(SRC, local=True)
        src.query("RETURN 1")
    except Exception as e:  # FalkorDB isn't running
        pytest.skip(f"FalkorDB not reachable: {e}")
    dst = connect(DST, local=True)
    for g in (src, dst):
        try:
            g.delete()
        except Exception:
            pass
    src.query(
        """
        CREATE (t:Talk {code: 'T1', title: 'Graphs 101', topics: ['AI', 'Graphs'], level_num: 200, start_min: 510})
        CREATE (u:Talk {code: 'T2', title: 'No list', sponsor: true, score: 0.75})
        CREATE (c:Concept {id: 'rag', name: 'RAG', aliases: ['retrieval augmented generation']})
        CREATE (d:Concept {id: 'emb', name: 'Embeddings'})
        CREATE (r:Resource:Vetted {url: 'https://example.com', minutes: 7})
        CREATE (a:Attendee {code: 'AAAA-BBBB-CCCC', clock_min: 510})
        CREATE (t)-[:REQUIRES {evidence: 'abstract says RAG', status: 'confirmed'}]->(c)
        CREATE (u)-[:TEACHES]->(d)
        CREATE (c)-[:DEPENDS_ON {via: ['T1', 'T2']}]->(d)
        CREATE (r)-[:EXPLAINS {checked_at: '2026-10-24'}]->(c)
        CREATE (a)-[:ATTENDED]->(u)
        CREATE (a)-[:KNOWS {how: 'attended', via: 'T2'}]->(d)
        """
    )
    # Delete one node so source ids have a gap and can't line up with the copy's by accident.
    src.query("CREATE (:Talk {code: 'GONE'})")
    src.query("MATCH (t:Talk {code: 'GONE'}) DELETE t")
    yield src, dst
    for g in (src, dst):
        try:
            g.delete()
        except Exception:
            pass


def one(g, query):
    return g.query(query).result_set[0][0]


def test_copy_excludes_attendees_and_keeps_everything_else(graphs):
    src, dst = graphs
    nodes, edges = copy_graph(src, dst)
    assert counts(*read_graph(dst, with_attendees=True)) == counts(nodes, edges) == {
        "nodes": {"Concept": 2, "Resource:Vetted": 1, "Talk": 2},
        "edges": {"DEPENDS_ON": 1, "EXPLAINS": 1, "REQUIRES": 1, "TEACHES": 1},
    }
    assert fingerprint(*read_graph(dst)) == fingerprint(nodes, edges)
    assert one(dst, "MATCH (a:Attendee) RETURN count(a)") == 0
    assert one(dst, "MATCH ()-[r:KNOWS|ATTENDED]->() RETURN count(r)") == 0


def test_copy_keeps_properties_lists_and_edge_properties(graphs):
    src, dst = graphs
    copy_graph(src, dst)
    row = dst.query("MATCH (t:Talk {code: 'T1'}) RETURN t.title, t.topics, t.level_num, t.start_min").result_set[0]
    assert row == ["Graphs 101", ["AI", "Graphs"], 200, 510]
    assert dst.query("MATCH (t:Talk {code: 'T2'}) RETURN t.sponsor, t.score").result_set[0] == [True, 0.75]
    assert one(dst, "MATCH (c:Concept {id: 'rag'}) RETURN c.aliases") == ["retrieval augmented generation"]
    assert dst.query(
        "MATCH (:Talk {code: 'T1'})-[r:REQUIRES]->(:Concept {id: 'rag'}) RETURN r.evidence, r.status"
    ).result_set[0] == ["abstract says RAG", "confirmed"]
    assert one(dst, "MATCH (:Concept {id: 'rag'})-[d:DEPENDS_ON]->(:Concept {id: 'emb'}) RETURN d.via") == ["T1", "T2"]
    assert one(dst, "MATCH (:Resource:Vetted)-[e:EXPLAINS]->(:Concept {id: 'rag'}) RETURN e.checked_at") == "2026-10-24"
    assert one(dst, "MATCH (:Talk {code: 'T2'})-[r:TEACHES]->(:Concept {id: 'emb'}) RETURN count(r)") == 1


def test_copy_with_attendees_and_replaces_previous_copy(graphs):
    src, dst = graphs
    copy_graph(src, dst)
    copy_graph(src, dst, with_attendees=True)  # a second sync replaces, never duplicates
    assert one(dst, "MATCH (t:Talk) RETURN count(t)") == 2
    assert one(dst, "MATCH (a:Attendee) RETURN a.clock_min") == 510
    assert one(dst, "MATCH (:Attendee)-[k:KNOWS]->(:Concept {id: 'emb'}) RETURN k.how") == "attended"
    assert fingerprint(*read_graph(dst, with_attendees=True)) == fingerprint(*read_graph(src, with_attendees=True))


def test_copy_recreates_indexes(graphs):
    src, dst = graphs
    copy_graph(src, dst)
    labels = {row[0] for row in dst.query("CALL db.indexes()").result_set}
    assert {"Talk", "Concept", "Attendee"} <= labels
