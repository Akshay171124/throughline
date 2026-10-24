"""The web API. Run with: uv run uvicorn throughline.api:app --reload"""

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from falkordb import Graph
from pydantic import BaseModel

from . import planner
from .agent import Tools, run_agent
from .config import ROOT, settings
from .graph import backend, connect

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
    return {"ok": True, "graph": settings.graph_name, "backend": backend(), "talks": talks}


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


# --- attendee memory, path and plan (the buttons; also the model-free fallback) ---

def _require_attendee(code: str) -> None:
    if planner.attendee_clock(graph(), code) is None:
        raise HTTPException(404, "Unknown attendee code")


@app.post("/api/attendees")
def create_attendee():
    return {"code": planner.new_attendee(graph())}


@app.get("/api/attendees/{code}")
def get_attendee(code: str):
    _require_attendee(code)
    state, _ = Tools(graph(), code).get_attendee()
    return state


@app.delete("/api/attendees/{code}")
def delete_attendee(code: str):
    planner.forget_attendee(graph(), code)
    return {"deleted": code}


class TalkRef(BaseModel):
    talk: str


class ConceptRef(BaseModel):
    concept: str


@app.post("/api/attendees/{code}/attended")
def attended(code: str, body: TalkRef):
    _require_attendee(code)
    learned = planner.mark_attended(graph(), code, body.talk)
    return {"learned": learned, "clock": planner.format_minutes(planner.attendee_clock(graph(), code))}


@app.post("/api/attendees/{code}/known")
def known(code: str, body: ConceptRef):
    _require_attendee(code)
    planner.mark_known(graph(), code, body.concept)
    return {"ok": True}


@app.get("/api/path/{talk}")
def path(talk: str, attendee: str | None = None):
    return planner.learning_path(graph(), talk, attendee)


@app.get("/api/plan/{talk}")
def plan(talk: str, attendee: str | None = None):
    try:
        return planner.plan_day(graph(), talk, attendee)
    except ValueError as e:
        raise HTTPException(404, str(e))


# --- the agent ---

class AgentTurn(BaseModel):
    attendee: str
    message: str
    history: list[dict] = []


@app.post("/api/agent")
def agent(body: AgentTurn):
    _require_attendee(body.attendee)
    return run_agent(graph(), body.attendee, body.message, body.history)


app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
