"""Offline demo: keep a local copy of the shared graph so "Plan without AI" survives a Wi-Fi outage.

  uv run python -m throughline.offline sync                    # lab -> local Docker FalkorDB
  uv run python -m throughline.offline sync --with-attendees   # also copy attendee memory
  uv run python -m throughline.offline check                   # prove the local copy works

The copy is plain Cypher (read every node and edge, recreate them), because GRAPH.COPY only works
within one server and DUMP/RESTORE ties both sides to the same FalkorDB build. Attendee nodes and
their relationships are left out by default: the local copy is for the demo, not for people's memory.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict

from falkordb import Graph

from .config import settings
from .graph import connect, ensure_schema, publish_public_view

BATCH = 500
SKIP_ATTENDEES = "Attendee"


def _label_expr(labels: list[str]) -> str:
    return "".join(f":`{label}`" for label in labels)


def read_graph(g: Graph, with_attendees: bool = False) -> tuple[list[dict], list[dict]]:
    """Every node (id, labels, properties) and edge (source id, target id, type, properties)."""
    node_filter = "" if with_attendees else f"WHERE NOT n:{SKIP_ATTENDEES}"
    edge_filter = "" if with_attendees else f"WHERE NOT a:{SKIP_ATTENDEES} AND NOT b:{SKIP_ATTENDEES}"
    nodes, edges = [], []
    skip = 0
    while True:
        rows = g.query(
            f"MATCH (n) {node_filter} RETURN id(n), labels(n), properties(n) ORDER BY id(n) SKIP $skip LIMIT $limit",
            {"skip": skip, "limit": BATCH},
        ).result_set
        nodes += [{"id": i, "labels": list(labels), "props": dict(props)} for i, labels, props in rows]
        if len(rows) < BATCH:
            break
        skip += BATCH
    skip = 0
    while True:
        rows = g.query(
            f"MATCH (a)-[e]->(b) {edge_filter} RETURN id(a), id(b), type(e), properties(e) "
            "ORDER BY id(e) SKIP $skip LIMIT $limit",
            {"skip": skip, "limit": BATCH},
        ).result_set
        edges += [{"src": s, "dst": d, "type": t, "props": dict(props)} for s, d, t, props in rows]
        if len(rows) < BATCH:
            break
        skip += BATCH
    return nodes, edges


def write_graph(dst: Graph, nodes: list[dict], edges: list[dict]) -> None:
    """Replace `dst` with exactly these nodes and edges, then recreate the indexes."""
    try:
        dst.delete()
    except Exception:  # nothing there yet
        pass
    ensure_schema(dst)

    id_map: dict[int, int] = {}
    by_labels: dict[tuple, list[dict]] = defaultdict(list)
    for n in nodes:
        by_labels[tuple(n["labels"])].append(n)
    for labels, group in by_labels.items():
        for i in range(0, len(group), BATCH):
            rows = [{"id": n["id"], "p": n["props"]} for n in group[i:i + BATCH]]
            created = dst.query(
                f"UNWIND $rows AS r CREATE (n{_label_expr(list(labels))}) SET n = r.p RETURN r.id, id(n)",
                {"rows": rows},
            ).result_set
            id_map.update({old: new for old, new in created})

    by_type: dict[str, list[dict]] = defaultdict(list)
    for e in edges:
        by_type[e["type"]].append(e)
    for rel_type, group in by_type.items():
        for i in range(0, len(group), BATCH):
            rows = [{"s": id_map[e["src"]], "d": id_map[e["dst"]], "p": e["props"]} for e in group[i:i + BATCH]]
            dst.query(
                f"UNWIND $rows AS r MATCH (a) WHERE id(a) = r.s MATCH (b) WHERE id(b) = r.d "
                f"CREATE (a)-[e:`{rel_type}`]->(b) SET e = r.p",
                {"rows": rows},
            )


def copy_graph(src: Graph, dst: Graph, with_attendees: bool = False) -> tuple[list[dict], list[dict]]:
    nodes, edges = read_graph(src, with_attendees)
    write_graph(dst, nodes, edges)
    return nodes, edges


def counts(nodes: list[dict], edges: list[dict]) -> dict:
    return {
        "nodes": dict(sorted(Counter(":".join(n["labels"]) for n in nodes).items())),
        "edges": dict(sorted(Counter(e["type"] for e in edges).items())),
    }


def fingerprint(nodes: list[dict], edges: list[dict]) -> tuple[Counter, Counter]:
    """Id-free content of a graph: each node as labels+properties, each edge with both endpoints."""
    key = {n["id"]: json.dumps([sorted(n["labels"]), n["props"]], sort_keys=True, default=str) for n in nodes}
    return (
        Counter(key.values()),
        Counter(json.dumps([key[e["src"]], e["type"], e["props"], key[e["dst"]]], sort_keys=True, default=str)
                for e in edges),
    )


def _print_counts(title: str, c: dict) -> None:
    print(f"{title}:")
    print("  nodes  " + ", ".join(f"{k} {v}" for k, v in c["nodes"].items()))
    print("  edges  " + ", ".join(f"{k} {v}" for k, v in c["edges"].items()))


def sync(with_attendees: bool = False) -> bool:
    if not settings.falkordb_url:
        print("FALKORDB_URL is not set, so there is no shared lab to copy from (the app already uses local).")
        return False
    src = connect()
    dst = connect(local=True)
    print(f"copying graph '{src.name}' from the shared lab to local FalkorDB "
          f"({settings.falkordb_host}:{settings.falkordb_port}); attendees "
          f"{'included' if with_attendees else 'excluded'}")
    nodes, edges = copy_graph(src, dst, with_attendees)
    publish_public_view(dst)

    copied = read_graph(dst, with_attendees=True)
    _print_counts("lab (source)", counts(nodes, edges))
    _print_counts("local (copy)", counts(*copied))
    same = counts(nodes, edges) == counts(*copied) and fingerprint(nodes, edges) == fingerprint(*copied)
    public = connect(dst.name + "_public", local=True)
    attendees = public.query("MATCH (a:Attendee) RETURN count(a)").result_set[0][0]
    print(f"public view '{public.name}' refreshed ({attendees} attendees)")
    print("PASS counts and contents match" if same else "FAIL local copy differs from the lab")
    return same


def check() -> bool:
    from . import graphview, planner

    g = connect(local=True)
    print(f"checking local FalkorDB ({settings.falkordb_host}:{settings.falkordb_port}), graph '{g.name}'"
          " (FALKORDB_URL ignored)")
    results = []

    def step(name, fn):
        try:
            detail = fn()
            results.append(True)
            print(f"PASS {name}: {detail}")
        except Exception as e:
            results.append(False)
            print(f"FAIL {name}: {type(e).__name__}: {e}")

    def talks():
        n = g.query("MATCH (t:Talk) RETURN count(t)").result_set[0][0]
        assert n > 0, "no talks"
        return f"{n} talks"

    def plan():
        p = planner.plan_day(g, "BLD1428W")
        assert p["plan"], "plan has no steps"
        kinds = Counter(s["learn_at"]["kind"] for s in p["plan"])
        return f"{len(p['plan'])} steps for '{p['talk_title']}' ({dict(kinds)})"

    def view():
        v = graphview.graph_for_talk(g, "BLD1428W")
        assert v["nodes"] and v["edges"], "empty graph view"
        return f"{len(v['nodes'])} nodes, {len(v['edges'])} edges"

    def attendee():
        code = planner.new_attendee(g)
        try:
            teacher = g.query("MATCH (t:Talk)-[:TEACHES]->() RETURN t.code LIMIT 1").result_set
            assert teacher, "no talk teaches anything"
            learned = planner.mark_attended(g, code, teacher[0][0])
            assert learned, "attending taught nothing"
            assert planner.attendee_clock(g, code) is not None
            with_memory = planner.plan_day(g, "BLD1428W", code)
        finally:
            planner.forget_attendee(g, code)
        assert planner.attendee_clock(g, code) is None, "attendee not forgotten"
        return f"created, attended {teacher[0][0]} (learned {len(learned)}), planned {len(with_memory['plan'])} steps, forgot"

    def public():
        p = connect(g.name + "_public", local=True)
        n = p.query("MATCH (t:Talk) RETURN count(t)").result_set[0][0]
        a = p.query("MATCH (a:Attendee) RETURN count(a)").result_set[0][0]
        assert n > 0 and a == 0, f"{n} talks, {a} attendees"
        return f"'{p.name}' has {n} talks and no attendees"

    def explainers():
        n = g.query("MATCH (:Resource)-[e:EXPLAINS]->(:Concept) RETURN count(e)").result_set[0][0]
        return f"{n} EXPLAINS edges in the local graph"

    step("talks", talks)
    step("plan BLD1428W", plan)
    step("graph view BLD1428W", view)
    step("attendee create/mark_attended/forget", attendee)
    step("public view", public)
    step("explainers", explainers)
    ok = all(results)
    print("PASS offline demo ready" if ok else "FAIL offline demo not ready")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description="Copy the shared graph to local FalkorDB and check the offline demo.")
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("sync", help="copy the shared lab graph into the local FalkorDB (replaces the local one)")
    s.add_argument("--with-attendees", action="store_true", help="also copy Attendee nodes and their edges")
    sub.add_parser("check", help="verify the plan/graph/attendee path works against local FalkorDB")
    args = parser.parse_args()
    ok = sync(args.with_attendees) if args.command == "sync" else check()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
