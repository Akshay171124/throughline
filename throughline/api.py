"""The web API. Run with: uv run uvicorn throughline.api:app --reload"""

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from falkordb import Graph
from pydantic import BaseModel

from . import flow, nearby, planner
from .agent import Tools, run_agent
from .config import ROOT, settings
from .graph import backend, conferences, connect, public_name
from .graphview import graph_for_talk

app = FastAPI(title="Throughline")

TALK_FIELDS = [
    "code", "title", "type", "level", "level_num", "day", "date", "start", "end",
    "start_min", "end_min", "room", "speakers", "topics", "sponsor", "url",
]
DETAIL_FIELDS = TALK_FIELDS + ["abstract", "source", "fetched_at"]

_graph: Graph | None = None
_public: Graph | None = None


def graph() -> Graph:
    global _graph
    if _graph is None:
        _graph = connect()
    return _graph


def public_graph() -> Graph:
    """The attendee-free copy that the agent's free-form Cypher runs on."""
    global _public
    if _public is None:
        _public = connect(public_name())
    return _public


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


@app.delete("/api/attendees/{code}/known/{concept}")
def unknown(code: str, concept: str):
    _require_attendee(code)
    planner.forget_known(graph(), code, concept)
    return {"ok": True}


class Profile(BaseModel):
    role: str = ""
    experience: str = ""
    interests: list[str] = []


@app.put("/api/attendees/{code}/profile")
def put_profile(code: str, body: Profile):
    _require_attendee(code)
    try:
        return {"profile": planner.set_profile(graph(), code, body.role, body.experience, body.interests)}
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/api/attendees/{code}/targets")
def add_target(code: str, body: TalkRef):
    _require_attendee(code)
    return {"targets": planner.add_target(graph(), code, body.talk)}


@app.delete("/api/attendees/{code}/targets/{talk}")
def remove_target(code: str, talk: str):
    _require_attendee(code)
    return {"targets": planner.remove_target(graph(), code, talk)}


@app.get("/api/attendees/{code}/chat")
def get_chat(code: str):
    _require_attendee(code)
    return {"messages": planner.chat_history(graph(), code)}


@app.delete("/api/attendees/{code}/chat")
def delete_chat(code: str):
    _require_attendee(code)
    planner.clear_chat(graph(), code)
    return {"ok": True}


@app.get("/api/concepts")
def list_concepts():
    rows = graph().query("MATCH (c:Concept) RETURN c.id, c.name, c.definition ORDER BY toLower(c.name)").result_set
    return [{"id": i, "name": n, "definition": d} for i, n, d in rows]


@app.get("/api/path/{talk}")
def path(talk: str, attendee: str | None = None):
    return planner.learning_path(graph(), talk, attendee)


@app.get("/api/plan/{talk}")
def plan(talk: str, attendee: str | None = None):
    try:
        return planner.plan_day(graph(), talk, attendee)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get("/api/graph/{talk}")
def talk_graph(talk: str, attendee: str | None = None):
    """The plan's path as nodes and edges for the page to draw."""
    try:
        return graph_for_talk(graph(), talk, attendee)
    except (ValueError, IndexError):
        raise HTTPException(404, f"No talk with code {talk}")


@app.get("/api/conferences")
def list_conferences():
    """Conferences whose schedules are loaded. The app never hard-codes a conference."""
    loaded = conferences(graph())
    current = next((c for c in loaded if c["id"] == settings.conference_id), loaded[0] if loaded else None)
    return {"current": current, "loaded": loaded}


@app.get("/api/conferences/nearby")
def conferences_nearby(place: str = "", lat: float | None = None, lon: float | None = None):
    """Conferences happening near a place (typed, or from the browser's location), found by live web search."""
    if lat is not None and not (-90 <= lat <= 90 and -180 <= (lon or 0) <= 180):
        raise HTTPException(422, "Invalid coordinates")
    return nearby.nearby(conferences(graph()), place=place, lat=lat, lon=lon)


@app.get("/api/flow")
def conference_flow(attendee: str | None = None):
    """The conference as a left-to-right flow of 'prepares you for' links, for the landing page."""
    return flow.flow(graph(), attendee)


@app.get("/api/featured")
def featured_talks(attendee: str | None = None):
    """Don't-miss talks: keynotes, then the talks that prepare you for the most others."""
    return flow.featured(graph(), attendee)


# --- the agent ---

class AgentTurn(BaseModel):
    attendee: str
    message: str
    history: list[dict] = []  # ignored: the server keeps the conversation
    page: str = "talk"  # "landing" when the attendee describes a goal on the conference map


@app.post("/api/agent")
def agent(body: AgentTurn):
    _require_attendee(body.attendee)
    g = graph()
    # The stored conversation, not what the browser sends, so it survives a refresh and can't be forged.
    history = [{"role": m["role"], "content": m["content"]} for m in planner.chat_history(g, body.attendee)
               if m.get("role") in ("user", "assistant") and m.get("content")]
    page = "landing" if body.page == "landing" else "talk"
    turn = run_agent(g, body.attendee, body.message[:2000], history, public=public_graph(), page=page)
    view = turn.get("view") or {}
    reply = {"role": "assistant", "content": turn.get("reply") or "", "page": page}
    if view.get("talk"):
        reply["talk"] = view["talk"]
    if turn.get("highlight"):
        reply["highlight"] = turn["highlight"]
    planner.append_chat(g, body.attendee, [{"role": "user", "content": body.message[:2000], "page": page}, reply])
    return turn


app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
