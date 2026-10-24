"""search_talks must put the talk people mean first, however loosely they name it."""

import pytest

from throughline.agent import Tools
from throughline.catalog import read_snapshot
from throughline.graph import connect, ensure_schema, load_talks


@pytest.fixture(scope="module")
def tools():
    try:
        g = connect("throughline_test_search", local=True)
        g.query("RETURN 1")
    except Exception as e:  # FalkorDB isn't running
        pytest.skip(f"FalkorDB not reachable: {e}")
    ensure_schema(g)
    load_talks(g, read_snapshot())
    yield Tools(g, attendee="nobody")
    g.delete()


CASES = [
    # the two known misses
    ("the MCP security talk", "TRU1338W"),            # Securing MCP: Real exploits...
    ("Own your Copilot workshop", "BLD1428W"),        # Own your Copilot: Advanced customization...
    # company, apostrophe
    ("the Levi's one", "LDR1516M"),                   # 17 agents, one SDLC: How Levi Strauss...
    ("Visa's secrets talk", "TRU1100B"),              # Visa's Zero-Secrets Initiative
    ("the Coinbase migration", "LDR1765B"),
    # phrase in the title
    ("the 2am RCA agent", "BLD1657H"),
    ("Actions firewall", "TRU1173D"),                 # not the Package Firewall talk
    ("agentic security", "TRU1397B"),
    # partial titles
    ("shut the context window", "BLD1312D"),
    ("your benchmark is lying", "BLD1132S"),
    ("the night shift talk", "LDR1684B"),
    ("Copilot model router", "BLD1553D"),
    ("stacked PRs", "BLD1485D"),
    ("pixel dog MCP server", "BLD1332H"),
    # speakers
    ("Kent C. Dodds", "BLD1886M"),
    ("the Pamela Fox workshop", "LDR1716W"),
    # talk codes
    ("BLD1428W", "BLD1428W"),
    ("tell me about tru1338w", "TRU1338W"),
]


@pytest.mark.parametrize("query,code", CASES)
def test_top_result(tools, query, code):
    results, _ = tools.search_talks(query, "any")
    assert results, f"nothing found for {query!r}"
    assert results[0]["code"] == code, f"{query!r}: got {[r['title'] for r in results[:3]]}"


def test_shape_and_trace(tools):
    results, queries = tools.search_talks("agents", "any")
    assert 0 < len(results) <= 6
    assert set(results[0]) == {"code", "title", "day", "start", "end", "room", "level"}
    assert len(queries) == 1 and "MATCH (t:Talk)" in queries[0]


def test_day_filter(tools):
    results, _ = tools.search_talks("the MCP security talk", "Thursday")
    assert results and all(r["day"] == "Thursday" for r in results)
    assert all(r["code"] != "TRU1338W" for r in results)  # that one is on Wednesday
