"""Concepts and the edges that connect them to talks.

Input formats (what the OpenAI extraction step writes):
  concepts: [{"id", "name", "aliases": [...], "definition"}]
  edges:    [{"type": "REQUIRES" | "TEACHES", "talk": code, "concept": id,
              "evidence": phrase from the abstract, "confidence": 0..1}]

`load_edges` keeps an edge only if its evidence phrase is in the talk's abstract.
`derive_depends_on` then builds concept-to-concept links from the talks:
a talk that TEACHES B and REQUIRES C is evidence that B depends on C.
"""

from collections import defaultdict
from datetime import datetime, timezone

from falkordb import Graph

from .evidence import phrase_in_source

EDGE_TYPES = {"REQUIRES", "TEACHES"}
UNSURE_BELOW = 0.6


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_concepts(g: Graph, concepts: list[dict]) -> int:
    g.query(
        """
        UNWIND $rows AS r
        MERGE (c:Concept {id: r.id})
        SET c.name = r.name, c.aliases = r.aliases, c.definition = r.definition
        """,
        {"rows": [
            {"id": c["id"], "name": c["name"], "aliases": c.get("aliases", []),
             "definition": c.get("definition", "")}
            for c in concepts
        ]},
    )
    return len(concepts)


def load_edges(g: Graph, edges: list[dict]) -> dict:
    """Check each proposed edge word for word against its talk's abstract, then write the keepers."""
    abstracts = dict(g.query("MATCH (t:Talk) RETURN t.code, t.abstract").result_set)
    concept_ids = {row[0] for row in g.query("MATCH (c:Concept) RETURN c.id").result_set}
    kept, discarded = defaultdict(list), []
    for e in edges:
        abstract = abstracts.get(e["talk"])
        ok = (
            e["type"] in EDGE_TYPES
            and abstract is not None
            and e["concept"] in concept_ids
            and phrase_in_source(e["evidence"], abstract)
        )
        if not ok:
            discarded.append(e)
            continue
        confidence = float(e.get("confidence", 1.0))
        kept[e["type"]].append({
            "talk": e["talk"], "concept": e["concept"], "evidence": e["evidence"],
            "confidence": confidence, "status": "unsure" if confidence < UNSURE_BELOW else "ok",
        })
    checked_at = _now()
    for edge_type, rows in kept.items():  # edge type can't be a query parameter
        g.query(
            f"""
            UNWIND $rows AS r
            MATCH (t:Talk {{code: r.talk}}), (c:Concept {{id: r.concept}})
            MERGE (t)-[e:{edge_type}]->(c)
            SET e.evidence = r.evidence, e.confidence = r.confidence, e.status = r.status,
                e.source = 'abstract', e.source_url = t.url, e.checked_at = $checked_at
            """,
            {"rows": rows, "checked_at": checked_at},
        )
    return {
        "proposed": len(edges),
        "kept": sum(len(rows) for rows in kept.values()),
        "discarded": len(discarded),
        "discarded_edges": discarded,
    }


def derive_depends_on(g: Graph) -> int:
    """Rebuild every DEPENDS_ON edge from talks that teach one concept and require another."""
    rows = g.query(
        """
        MATCH (t:Talk)-[tb:TEACHES]->(b:Concept), (t)-[rc:REQUIRES]->(c:Concept)
        WHERE b <> c
        RETURN b.id, c.id, t.code, tb.evidence, rc.evidence
        """
    ).result_set
    support = defaultdict(lambda: {"via": [], "evidence": []})
    for b, c, code, teaches, requires in rows:
        link = support[(b, c)]
        link["via"].append(code)
        link["evidence"].append(f'{code} teaches "{teaches}" and requires "{requires}"')
    # When talks disagree on direction, keep the direction more talks support (both on a tie).
    keep = [
        {"from": b, "to": c, "support": len(link["via"]), **link}
        for (b, c), link in support.items()
        if len(link["via"]) >= len(support.get((c, b), {"via": []})["via"])
    ]
    g.query("MATCH ()-[d:DEPENDS_ON]->() DELETE d")
    if keep:
        g.query(
            """
            UNWIND $rows AS r
            MATCH (b:Concept {id: r.from}), (c:Concept {id: r.to})
            MERGE (b)-[d:DEPENDS_ON]->(c)
            SET d.support = r.support, d.via = r.via, d.evidence = r.evidence,
                d.source = 'derived from talk abstracts', d.checked_at = $checked_at
            """,
            {"rows": keep, "checked_at": _now()},
        )
    return len(keep)
