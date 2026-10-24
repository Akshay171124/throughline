"""FalkorDB connection, schema and the talk loader.

Run `python -m throughline.graph` to load the talks snapshot into the graph.
"""

from datetime import datetime, timezone

from falkordb import FalkorDB, Graph

from .catalog import read_snapshot
from .config import settings

INDEXES = [
    ("Conference", "id"),
    ("Talk", "code"),
    ("TimeSlot", "key"),
    ("Concept", "id"),
    ("Attendee", "code"),
]


def connect(graph_name: str | None = None) -> Graph:
    db = FalkorDB(host=settings.falkordb_host, port=settings.falkordb_port)
    return db.select_graph(graph_name or settings.graph_name)


def ensure_schema(g: Graph) -> None:
    for label, prop in INDEXES:
        try:
            g.query(f"CREATE INDEX FOR (n:{label}) ON (n.{prop})")
        except Exception as e:  # FalkorDB refuses to create an index twice
            if "already indexed" not in str(e).lower():
                raise


def load_talks(g: Graph, talks: list[dict], source: str = "snapshot") -> int:
    """Upsert talks and their time slots. Safe to run again after a fresh scrape."""
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = [
        {
            **{k: t[k] for k in (
                "code", "session_id", "title", "type", "level", "topics", "sponsor",
                "date", "day", "start", "end", "start_min", "end_min", "room", "abstract", "url",
            )},
            "level_num": t["level_num"] if t["level_num"] is not None else 0,
            "speakers": [f"{s['name']} ({s['company']})" if s["company"] else s["name"] for s in t["speakers"]],
            "slot_key": f"{t['date']}T{t['start']}-{t['end']}",
        }
        for t in talks
    ]
    g.query(
        "MERGE (c:Conference {id: $id}) SET c.name = $name",
        {"id": settings.conference_id, "name": settings.conference_name},
    )
    # A re-scrape can move a talk, so drop old slot links before relinking.
    g.query(
        "MATCH (t:Talk)-[r:IN_SLOT]->() WHERE t.code IN $codes DELETE r",
        {"codes": [r["code"] for r in rows]},
    )
    g.query(
        """
        UNWIND $rows AS r
        MATCH (c:Conference {id: $conf})
        MERGE (t:Talk {code: r.code})
        SET t.session_id = r.session_id, t.title = r.title, t.type = r.type,
            t.level = r.level, t.level_num = r.level_num, t.topics = r.topics,
            t.sponsor = r.sponsor, t.date = r.date, t.day = r.day,
            t.start = r.start, t.end = r.end, t.start_min = r.start_min, t.end_min = r.end_min,
            t.room = r.room, t.speakers = r.speakers, t.abstract = r.abstract, t.url = r.url,
            t.source = $source, t.fetched_at = $fetched_at
        MERGE (s:TimeSlot {key: r.slot_key})
        SET s.date = r.date, s.start = r.start, s.end = r.end,
            s.start_min = r.start_min, s.end_min = r.end_min
        MERGE (t)-[:IN_SLOT]->(s)
        MERGE (t)-[:PART_OF]->(c)
        """,
        {"rows": rows, "conf": settings.conference_id, "source": source, "fetched_at": fetched_at},
    )
    return len(rows)


if __name__ == "__main__":
    graph = connect()
    ensure_schema(graph)
    count = load_talks(graph, read_snapshot())
    print(f"loaded {count} talks into graph '{settings.graph_name}'")
