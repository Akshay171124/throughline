"""Every number in the "Measured quality" section of THROUGHLINE_SUBMISSION.md, from the live graph.

Read-only: it never writes to the graph. The evidence check is re-run in memory over
data/extraction/edges.jsonl with the same rules as knowledge.load_edges.

  uv run python -m throughline.quality          # prints the report, writes data/quality.json
  uv run python -m throughline.quality --sample # the 20 edges for the hand check (fixed seed)

The hand check's verdicts live in data/quality_handcheck.json; this report only counts them.
"""

import json
import random
import sys
from collections import Counter

from falkordb import Graph

from .config import ROOT
from .evaluate import evaluate
from .evidence import phrase_in_source
from .extract import EDGES
from .graph import backend, connect
from .knowledge import EDGE_TYPES

OUT = ROOT / "data" / "quality.json"
HANDCHECK = ROOT / "data" / "quality_handcheck.json"
EDGE_COUNT_TYPES = ["REQUIRES", "TEACHES", "DEPENDS_ON", "EXPLAINS"]
SAMPLE_SIZE, SAMPLE_SEED = 20, 2026


def _one(g: Graph, cypher: str, params: dict | None = None):
    return g.ro_query(cypher, params or {}).result_set


def evidence_check(g: Graph, edges: list[dict]) -> dict:
    """The word-for-word check from knowledge.load_edges, without writing anything."""
    # Same source text as knowledge.load_edges: title, stated level and abstract.
    sources = {code: f"{title}\n{level or ''}\n{abstract}" for code, title, level, abstract in
               _one(g, "MATCH (t:Talk) RETURN t.code, t.title, t.level, t.abstract")}
    concept_ids = {row[0] for row in _one(g, "MATCH (c:Concept) RETURN c.id")}
    reasons = Counter()
    for e in edges:
        source = sources.get(e.get("talk"))
        if e.get("type") not in EDGE_TYPES:
            reasons["unknown edge type"] += 1
        elif source is None:
            reasons["unknown talk"] += 1
        elif e.get("concept") not in concept_ids:
            reasons["unknown concept"] += 1
        elif not phrase_in_source(e.get("evidence", ""), source):
            reasons["evidence not in title, level or abstract"] += 1
    discarded = sum(reasons.values())
    return {
        "proposed": len(edges),
        "kept": len(edges) - discarded,
        "discarded": discarded,
        "discard_rate_pct": round(100 * discarded / max(len(edges), 1), 1),
        "discard_reasons": dict(reasons),
    }


def sample_edges(g: Graph, n: int = SAMPLE_SIZE, seed: int = SAMPLE_SEED) -> list[dict]:
    """A reproducible random sample of REQUIRES/TEACHES edges, with what a reviewer needs to judge them."""
    rows = _one(g, """
        MATCH (t:Talk)-[r:REQUIRES|TEACHES]->(c:Concept)
        RETURN type(r), t.code, c.id, c.definition, r.evidence, r.confidence, t.title, t.abstract
        ORDER BY t.code, type(r), c.id
    """)
    keys = ["type", "code", "concept", "definition", "evidence", "confidence", "title", "abstract"]
    return [dict(zip(keys, r)) for r in random.Random(seed).sample(rows, min(n, len(rows)))]


def measure(g: Graph) -> dict:
    talks = _one(g, "MATCH (t:Talk) RETURN count(t)")[0][0]
    concepts = _one(g, "MATCH (c:Concept) RETURN count(c)")[0][0]
    edges = {t: _one(g, f"MATCH ()-[r:{t}]->() RETURN count(r)")[0][0] for t in EDGE_COUNT_TYPES}

    required = _one(g, """
        MATCH (t:Talk)-[:REQUIRES]->(c:Concept)
        WITH c, count(DISTINCT t) AS assumed_by
        OPTIONAL MATCH (teacher:Talk)-[:TEACHES]->(c)
        WITH c, assumed_by, count(DISTINCT teacher) AS taught_by
        OPTIONAL MATCH (r:Resource)-[:EXPLAINS]->(c)
        RETURN c.id, c.name, assumed_by, taught_by, count(DISTINCT r) AS explainers
        ORDER BY assumed_by DESC, c.id
    """)
    rows = [dict(zip(["id", "name", "assumed_by", "taught_by", "explainers"], r)) for r in required]
    covered = [r for r in rows if r["taught_by"] or r["explainers"]]
    orphans = [r for r in rows if not r["taught_by"]]

    unsure = _one(g, """
        MATCH (t:Talk)-[r:REQUIRES|TEACHES]->(c:Concept) WHERE r.status = 'unsure'
        RETURN type(r), t.code, c.id, r.evidence, r.confidence ORDER BY r.confidence
    """)

    proposed = [json.loads(line) for line in EDGES.open() if line.strip()]
    baseline = evaluate(g)

    result = {
        "graph": backend().split(" (")[0],  # no host name in a file that goes in the repo
        "talks": talks,
        "concepts": concepts,
        "edges": {**edges, "total": sum(edges.values())},
        "coverage": {
            "required_concepts": len(rows),
            "covered": len(covered),
            "covered_pct": round(100 * len(covered) / max(len(rows), 1), 1),
            "by_teaching_talk": sum(1 for r in rows if r["taught_by"]),
            "by_explainer_only": sum(1 for r in rows if r["explainers"] and not r["taught_by"]),
            "uncovered": [r["name"] for r in rows if not (r["taught_by"] or r["explainers"])],
        },
        "orphan_concepts": {
            "count": len(orphans),
            "concepts": [{"id": r["id"], "name": r["name"], "assumed_by": r["assumed_by"],
                          "has_explainer": bool(r["explainers"])} for r in orphans],
        },
        "evidence_check": evidence_check(g, proposed),
        "unsure_edges": {
            "count": len(unsure),
            "edges": [dict(zip(["type", "talk", "concept", "evidence", "confidence"], u)) for u in unsure],
        },
        "baseline": {
            "summary": baseline["summary"],
            "new_teachers": {r["code"]: r["new"] for r in baseline["rows"] if r["new"]},
            "new_teachers_total": sum(len(r["new"]) for r in baseline["rows"]),
            "new_teachers_distinct": len({c for r in baseline["rows"] for c in r["new"]}),
        },
    }
    if HANDCHECK.exists():
        checks = json.loads(HANDCHECK.read_text())
        verdicts = Counter(c["verdict"] for c in checks["edges"])
        result["hand_check"] = {"checked": len(checks["edges"]), "verdicts": dict(verdicts),
                                "reviewer": checks.get("reviewer"), "seed": checks.get("seed")}
    return result


def report(q: dict) -> str:
    e, cov, ev, b = q["edges"], q["coverage"], q["evidence_check"], q["baseline"]["summary"]
    lines = [
        f"Throughline measured quality ({q['graph']})",
        f"  Talks: {q['talks']}  Concepts: {q['concepts']}  Edges: {e['total']}",
        "    " + ", ".join(f"{t} {e[t]}" for t in EDGE_COUNT_TYPES),
        f"  Coverage: {cov['covered_pct']}% ({cov['covered']} of {cov['required_concepts']} required concepts) "
        f"have a teaching talk or an outside explainer",
        f"    by a teaching talk: {cov['by_teaching_talk']}, by an explainer only: {cov['by_explainer_only']}",
        f"    uncovered: {', '.join(cov['uncovered']) or 'none'}",
        f"  Evidence check: {ev['discarded']} of {ev['proposed']} proposed edges discarded "
        f"({ev['discard_rate_pct']}%) {ev['discard_reasons'] or ''}",
        f"  Edges marked unsure: {q['unsure_edges']['count']}",
        f"  Orphan concepts (assumed, taught by none): {q['orphan_concepts']['count']}",
    ]
    lines += [f"    - {o['name']} (assumed by {o['assumed_by']}"
              f"{', has an explainer' if o['has_explainer'] else ', no explainer'})"
              for o in q["orphan_concepts"]["concepts"]]
    lines += [
        "  Baseline (checks/prerequisite-baseline.json):",
        f"    talks with expected teachers where the graph found at least one: "
        f"{b['found_at_least_one_expected_teacher']} of {b['talks_with_expected_teachers']}",
        f"    expected teachers matched: {b['expected_teachers_matched']} of {b['expected_teachers_total']} "
        f"(missed {b['expected_teachers_total'] - b['expected_teachers_matched']})",
        f"    'none needed' talks correctly 'You're ready': {b['none_needed_correctly_ready']} of {b['none_needed_total']}",
        f"    other teaching talks the hand check didn't list: {q['baseline']['new_teachers_total']} "
        f"({q['baseline']['new_teachers_distinct']} distinct talks; not yet checked by hand)",
    ]
    if "hand_check" in q:
        h = q["hand_check"]
        lines.append(f"  Hand check ({h['reviewer']}, seed {h['seed']}): {h['checked']} edges, verdicts {h['verdicts']}")
    return "\n".join(lines)


if __name__ == "__main__":
    if "--sample" in sys.argv:
        print(json.dumps(sample_edges(connect()), indent=2))
        sys.exit()
    quality = measure(connect())
    OUT.write_text(json.dumps(quality, indent=2) + "\n")
    print(report(quality))
    print(f"\nwrote {OUT.relative_to(ROOT)}")
