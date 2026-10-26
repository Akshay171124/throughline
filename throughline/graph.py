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


def backend() -> str:
    """Which FalkorDB we're talking to, without revealing the password."""
    if settings.falkordb_url:
        host = settings.falkordb_url.rsplit("@", 1)[-1]
        return f"FalkorDB lab ({host})"
    return f"local FalkorDB ({settings.falkordb_host}:{settings.falkordb_port})"


def connect(graph_name: str | None = None, local: bool = False) -> Graph:
    """Connect to the lab if FALKORDB_URL is set, else to the local instance (or force local)."""
    if settings.falkordb_url and not local:
        db = FalkorDB.from_url(settings.falkordb_url)
    else:
        db = FalkorDB(host=settings.falkordb_host, port=settings.falkordb_port)
    return db.select_graph(graph_name or settings.graph_name)


PUBLIC_SUFFIX = "_public"


def public_name(graph_name: str | None = None) -> str:
    return (graph_name or settings.graph_name) + PUBLIC_SUFFIX


def publish_public_view(g: Graph) -> Graph:
    """Copy the graph without any attendee data. Free-form (GraphRAG) Cypher only ever runs here,
    so no query, however it's written, can read another attendee's code or memory."""
    target = g.name + PUBLIC_SUFFIX
    try:
        g.execute_command("GRAPH.DELETE", target)
    except Exception:  # no previous view
        pass
    view = g.copy(target)
    view.query("MATCH (a:Attendee) DETACH DELETE a")
    return view


def ensure_schema(g: Graph) -> None:
    for label, prop in INDEXES:
        try:
            g.query(f"CREATE INDEX FOR (n:{label}) ON (n.{prop})")
        except Exception as e:  # FalkorDB refuses to create an index twice
            if "already indexed" not in str(e).lower():
                raise


def upsert_conference(g: Graph, conf: dict | None = None) -> None:
    """The conference's own details live in the graph, so the app never hard-codes them.
    None means GitHub Universe, from settings."""
    conf = conf or {
        "id": settings.conference_id, "name": settings.conference_name, "dates": settings.conference_dates,
        "start_date": settings.conference_start, "end_date": settings.conference_end,
        "location": settings.conference_location, "clock_start": settings.clock_start, "url": "",
    }
    g.query(
        """
        MERGE (c:Conference {id: $id})
        SET c.name = $name, c.dates = $dates, c.start_date = $start, c.end_date = $end, c.location = $location,
            c.clock_start = $clock, c.url = $url
        """,
        {"id": conf["id"], "name": conf["name"], "dates": conf.get("dates", ""), "start": conf.get("start_date", ""),
         "end": conf.get("end_date", ""), "location": conf.get("location", ""),
         "clock": conf.get("clock_start", ""), "url": conf.get("url", "")},
    )


def conferences(g: Graph) -> list[dict]:
    rows = g.query(
        """
        MATCH (c:Conference)
        OPTIONAL MATCH (t:Talk)-[:PART_OF]->(c)
        RETURN c.id, c.name, c.dates, c.start_date, c.end_date, c.location, count(t)
        ORDER BY c.start_date
        """
    ).result_set
    keys = ["id", "name", "dates", "start_date", "end_date", "location", "talks"]
    return [dict(zip(keys, r)) for r in rows]


def load_talks(g: Graph, talks: list[dict], source: str = "snapshot", conf: dict | None = None) -> int:
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
    upsert_conference(g, conf)
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
        {"rows": rows, "conf": conf["id"] if conf else settings.conference_id, "source": source, "fetched_at": fetched_at},
    )
    return len(rows)


if __name__ == "__main__":
    graph = connect()
    ensure_schema(graph)
    count = load_talks(graph, read_snapshot())
    publish_public_view(graph)
    print(f"loaded {count} talks into graph '{settings.graph_name}' (public view refreshed)")
