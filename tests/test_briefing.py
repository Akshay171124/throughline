"""'About this talk' briefings, with search and the model faked."""

import json
from types import SimpleNamespace

import pytest

from throughline import briefing
from throughline.graph import connect, ensure_schema


@pytest.fixture(scope="module")
def g():
    try:
        graph = connect("throughline_test_briefing", local=True)
        graph.query("RETURN 1")
    except Exception as e:
        pytest.skip(f"FalkorDB not reachable: {e}")
    ensure_schema(graph)
    graph.query(
        "CREATE (t:Talk {code: 'T1', title: 'Securing MCP: real exploits', level: 'Level 200', abstract: 'How to secure MCP servers.'}),"
        " (c:Concept {id: 'mcp', name: 'MCP', definition: 'A protocol.', basic: false}),"
        " (t)-[:REQUIRES {evidence: 'MCP servers'}]->(c)"
    )
    yield graph
    graph.delete()


class FakeClient:
    def __init__(self, payload):
        content = json.dumps(payload)
        message = SimpleNamespace(content=content)
        self.chat = SimpleNamespace(completions=SimpleNamespace(
            create=lambda **_: SimpleNamespace(choices=[SimpleNamespace(message=message)])))


RESULTS = [
    {"title": "MCP spec", "url": "https://modelcontextprotocol.io/spec", "snippet": "The spec"},
    {"title": "Universe page", "url": "https://githubuniverse.com/session/1", "snippet": "the talk itself"},
    {"title": "A post", "url": "https://www.linkedin.com/posts/x", "snippet": "social"},
    {"title": "MCP security guide", "url": "https://owasp.org/mcp", "snippet": "Security"},
]


def test_only_real_outside_results_can_be_picked(g, monkeypatch):
    monkeypatch.setattr(briefing.brightdata, "serp_search", lambda q: RESULTS)
    client = FakeClient({"summary": "About securing MCP.", "picks": [
        {"result": 0, "kind": "docs", "why": "The protocol itself", "minutes": 10},
        {"result": 1, "kind": "article", "why": "duplicate pick", "minutes": 0},
        {"result": 7, "kind": "article", "why": "made-up index", "minutes": 5},  # not a real result
    ]})
    b = briefing.build(client, g, "T1")
    urls = [r["url"] for r in b["readings"]]
    # Conference and social pages never reach the model, so index 1 is the OWASP guide here.
    assert urls == ["https://modelcontextprotocol.io/spec", "https://owasp.org/mcp"]
    assert b["readings"][0]["domain"] == "modelcontextprotocol.io" and b["readings"][1]["minutes"] is None


def test_stored_briefing_round_trips_and_replaces_old_links(g, monkeypatch):
    first = {"code": "T1", "summary": "Old.", "summary_source": briefing.SUMMARY_SOURCE, "fetched_at": "t0",
             "readings": [{"title": "Old", "url": "https://old.example/a", "domain": "old.example", "kind": "article", "why": "x", "minutes": 3}]}
    second = {**first, "summary": "New.", "fetched_at": "t1",
              "readings": [{"title": "New", "url": "https://new.example/b", "domain": "new.example", "kind": "docs", "why": "y", "minutes": None}]}
    briefing.store(g, first)
    briefing.store(g, second)
    out = briefing.briefing(g, "T1")
    assert out["status"] == "ready" and out["summary"] == "New."
    assert [r["url"] for r in out["readings"]] == ["https://new.example/b"]
    assert out["concepts"] == [{"id": "mcp", "name": "MCP", "definition": "A protocol.", "role": "requires", "basic": False}]


def test_excluded_and_insecure_links():
    assert not briefing._allowed("http://docs.example.com")  # https only
    assert not briefing._allowed("https://reg.githubuniverse.com/flow/x")
    assert briefing._allowed("https://docs.github.com/en/copilot")
