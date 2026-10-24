"""PASS/FAIL setup check for everyone on the team. Never prints secrets.

  uv run python -m throughline.check_setup
"""

import os

from .config import settings
from .graph import backend, connect

results: list[tuple[str, bool, str]] = []


def check(name: str):
    def wrap(fn):
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {e}"
        results.append((name, ok, detail))
        return fn
    return wrap


def describe_path(path) -> str:
    nodes, edges = path.nodes(), path.edges()
    label = lambda n: n.properties.get("title") or n.properties.get("key") or n.properties.get("id")
    parts = [label(nodes[0])]
    for edge, node in zip(edges, nodes[1:]):
        parts.append(f"-[{edge.relation}]-")
        parts.append(label(node))
    return " ".join(str(p) for p in parts)


@check("FalkorDB connection")
def _():
    g = connect()
    assert g.query("RETURN 1").result_set == [[1]]
    return True, backend()


@check("Graph data")
def _():
    g = connect()
    talks = g.query("MATCH (t:Talk) RETURN count(t)").result_set[0][0]
    slots = g.query("MATCH (s:TimeSlot) RETURN count(s)").result_set[0][0]
    edges = g.query("MATCH ()-[r]->() RETURN count(r)").result_set[0][0]
    hint = "" if talks else " (run: uv run python -m throughline.graph)"
    return talks > 0, f"graph '{settings.graph_name}': {talks} talks, {slots} time slots, {edges} edges{hint}"


@check("Multi-hop path query")
def _():
    # Two talks in the same time slot (a clash), returned as a path: Talk -> TimeSlot <- Talk.
    # `a <> b` matters: the pattern may otherwise walk back along the same edge to the same talk.
    rows = connect().query(
        "MATCH p = (a:Talk)-[:IN_SLOT]->(:TimeSlot)<-[:IN_SLOT]-(b:Talk) WHERE a <> b RETURN p LIMIT 1"
    ).result_set
    return bool(rows), describe_path(rows[0][0]) if rows else "no path returned"


@check("OpenAI key")
def _():
    if not os.getenv("OPENAI_API_KEY"):
        return False, "OPENAI_API_KEY is empty in .env"
    from openai import OpenAI
    models = {m.id for m in OpenAI().models.list().data}
    missing = {settings.extract_model, settings.agent_model} - models
    return not missing, "works" if not missing else f"key works, but these models aren't available: {sorted(missing)}"


@check("Bright Data settings")
def _():
    names = ["BRIGHTDATA_API_TOKEN", "BRIGHTDATA_SERP_ZONE", "BRIGHTDATA_BROWSER_WS"]
    empty = [n for n in names if not os.getenv(n)]
    return not empty, "all set" if not empty else f"still empty in .env: {', '.join(empty)}"


if __name__ == "__main__":
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
