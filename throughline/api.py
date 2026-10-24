"""The web API. Run with: uv run uvicorn throughline.api:app --reload"""

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from falkordb import Graph

from .config import ROOT, settings
from .graph import connect

app = FastAPI(title="Throughline")

TALK_FIELDS = [
    "code", "title", "type", "level", "level_num", "day", "date", "start", "end",
    "start_min", "end_min", "room", "speakers", "topics", "sponsor", "url",
]
DETAIL_FIELDS = TALK_FIELDS + ["abstract", "source", "fetched_at"]

_graph: Graph | None = None


def graph() -> Graph:
    global _graph
    if _graph is None:
        _graph = connect()
    return _graph


def _rows(result, fields: list[str]) -> list[dict]:
    return [dict(zip(fields, row)) for row in result.result_set]


def _returning(fields: list[str]) -> str:
    return ", ".join(f"t.{f}" for f in fields)


@app.get("/api/health")
def health():
    try:
        talks = graph().query("MATCH (t:Talk) RETURN count(t)").result_set[0][0]
    except Exception as e:
        raise HTTPException(503, f"FalkorDB unavailable: {e}")
    return {"ok": True, "graph": settings.graph_name, "talks": talks}


@app.get("/api/clock")
def clock():
    return {"now": settings.clock_start, "conference": settings.conference_name}


@app.get("/api/talks")
def list_talks():
    result = graph().query(
        f"MATCH (t:Talk) RETURN {_returning(TALK_FIELDS)} ORDER BY t.start_min, t.code"
    )
    return _rows(result, TALK_FIELDS)


@app.get("/api/talks/{code}")
def get_talk(code: str):
    result = graph().query(
        f"MATCH (t:Talk {{code: $code}}) RETURN {_returning(DETAIL_FIELDS)}", {"code": code}
    )
    if not result.result_set:
        raise HTTPException(404, f"No talk with code {code}")
    return _rows(result, DETAIL_FIELDS)[0]


app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
