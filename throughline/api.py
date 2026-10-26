"""The web API. Run with: uv run uvicorn throughline.api:app --reload

Every request is about one conference: `?conf=<id>`, else the `X-Conference` header, else GitHub Universe.
Attendee accounts (code and profile) live in the registry graph, so one code works at every conference."""

import socket
from contextlib import asynccontextmanager
from dataclasses import dataclass
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from falkordb import Graph
from pydantic import BaseModel

from . import briefing, build, flow, importer, nearby, planner
from . import registry as registry_db
from .agent import Tools, run_agent
from .config import ROOT, settings
from .graph import backend, conferences, connect, public_name
from .graphview import graph_for_talk

BUILT = ("ready", "partial")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    reg = registry()
    registry_db.ensure_universe(reg)
    build.recover_interrupted(reg)
    migrate_accounts(reg, graph())
    yield


app = FastAPI(title="Throughline", lifespan=lifespan)

TALK_FIELDS = [
    "code", "title", "type", "level", "level_num", "day", "date", "start", "end",
    "start_min", "end_min", "room", "speakers", "topics", "sponsor", "url",
]
DETAIL_FIELDS = TALK_FIELDS + ["abstract", "source", "fetched_at"]

_graph: Graph | None = None  # Universe overrides (tests set these)
_public: Graph | None = None
_graphs: dict[str, Graph] = {}
_registry: Graph | None = None


@dataclass
class Ctx:
    conf: dict
    g: Graph
    public: Graph


def registry() -> Graph:
    global _registry
    if _registry is None:
        _registry = registry_db.registry_graph()
    return _registry


def _handle(name: str) -> Graph:
    if name not in _graphs:
        _graphs[name] = connect(name)
    return _graphs[name]


def _universe_settings() -> dict:
    return {
        "id": registry_db.UNIVERSE_ID, "name": settings.conference_name, "dates": settings.conference_dates,
        "start_date": settings.conference_start, "end_date": settings.conference_end,
        "location": settings.conference_location, "graph": settings.graph_name, "status": "ready",
        "clock_start": settings.clock_start,
    }


def _conference(conf_id: str) -> Ctx:
    if conf_id == registry_db.UNIVERSE_ID and _graph is not None:
        return Ctx(_universe_settings(), _graph, _public if _public is not None else _handle(public_name()))
    reg = registry()
    conf = registry_db.get(reg, conf_id)
    if conf is None and conf_id == registry_db.UNIVERSE_ID:
        conf = registry_db.ensure_universe(reg)
    if conf is None:
        raise HTTPException(404, "Unknown conference")
    if conf["status"] not in BUILT:
        raise HTTPException(409, "This conference's map isn't built yet")
    return Ctx(conf, _handle(conf["graph"]), _handle(public_name(conf["graph"])))


def ctx(conf: str | None = Query(None), x_conference: str | None = Header(None)) -> Ctx:
    """The conference this request is about: the query, else the header, else Universe."""
    return _conference(conf or x_conference or registry_db.UNIVERSE_ID)


def graph() -> Graph:
    """Universe's graph."""
    return _conference(registry_db.UNIVERSE_ID).g


def public_graph() -> Graph:
    """Universe's attendee-free copy that the agent's free-form Cypher runs on."""
    return _conference(registry_db.UNIVERSE_ID).public


def _rows(result, fields: list[str]) -> list[dict]:
    return [dict(zip(fields, row)) for row in result.result_set]


def _returning(fields: list[str]) -> str:
    return ", ".join(f"t.{f}" for f in fields)


@app.get("/api/health")
def health(c: Ctx = Depends(ctx)):
    try:
        talks = c.g.query("MATCH (t:Talk) RETURN count(t)").result_set[0][0]
    except Exception as e:
        raise HTTPException(503, f"FalkorDB unavailable: {e}")
    return {"ok": True, "graph": c.conf["graph"], "backend": backend(), "talks": talks}


@app.get("/api/clock")
def clock(c: Ctx = Depends(ctx)):
    return {"now": c.conf["clock_start"], "conference": c.conf["name"]}


@app.get("/api/talks")
def list_talks(c: Ctx = Depends(ctx)):
    result = c.g.query(
        f"MATCH (t:Talk) RETURN {_returning(TALK_FIELDS)} ORDER BY t.start_min, t.code"
    )
    return _rows(result, TALK_FIELDS)


@app.get("/api/talks/{code}/briefing")
def talk_briefing(code: str, c: Ctx = Depends(ctx)):
    """'About this talk': AI summary of the abstract, its concepts, and outside links to read first."""
    try:
        b = briefing.briefing(c.g, code)
    except ValueError:
        raise HTTPException(404, f"No talk with code {code}")
    if b["status"] == "missing":  # the first open builds it in the background; the page asks again
        abstract = c.g.query("MATCH (t:Talk {code: $c}) RETURN t.abstract", {"c": code}).result_set[0][0]
        if (abstract or "").strip():
            briefing.start(c.g, code)
            return {**b, "status": "building"}
        return {**b, "status": "none"}
    return b


@app.get("/api/talks/{code}")
def get_talk(code: str, c: Ctx = Depends(ctx)):
    result = c.g.query(
        f"MATCH (t:Talk {{code: $code}}) RETURN {_returning(DETAIL_FIELDS)}", {"code": code}
    )
    if not result.result_set:
        raise HTTPException(404, f"No talk with code {code}")
    return _rows(result, DETAIL_FIELDS)[0]


# --- attendee accounts, memory, path and plan (the buttons; also the model-free fallback) ---

def _adopt(reg: Graph, g: Graph, code: str) -> None:
    """An account for an attendee that only has a node (made before accounts existed), with its profile."""
    registry_db.create_account(reg, code)
    rows = g.query("MATCH (a:Attendee {code: $code}) RETURN a.role, a.experience, a.interests", {"code": code}).result_set
    role, experience, interests = rows[0] if rows else (None, None, None)
    if role or experience or interests:
        experience = experience if experience in planner.EXPERIENCE_LEVELS else ""
        registry_db.set_profile(reg, code, role or "", experience, interests or [])


def migrate_accounts(reg: Graph, g: Graph) -> int:
    """Give every attendee in this graph without an account one, copying their profile."""
    codes = [r[0] for r in g.query("MATCH (a:Attendee) RETURN a.code").result_set]
    missing = [code for code in codes if not registry_db.account_exists(reg, code)]
    for code in missing:
        _adopt(reg, g, code)
    return len(missing)


def ensure_attendee(c: Ctx, code: str) -> None:
    """The attendee's node in this conference's graph: made from their account on a first visit here,
    and given the account's profile when that changed elsewhere since."""
    reg = registry()
    has_node = planner.attendee_clock(c.g, code) is not None
    if not registry_db.account_exists(reg, code):
        if not has_node:
            raise HTTPException(404, "Unknown attendee code")
        _adopt(reg, c.g, code)
        return
    if not has_node:
        c.g.query("MERGE (a:Attendee {code: $code}) ON CREATE SET a.clock_min = $clock",
                  {"code": code, "clock": planner.default_clock(c.g)})
    account, node = registry_db.get_profile(reg, code), planner.get_profile(c.g, code)
    if _newer(account, node):
        planner.set_profile(c.g, code, account["role"], account["experience"], account["interests"])


def _newer(profile: dict, other: dict) -> bool:
    """`profile` differs from `other` and isn't older (timestamps are to the second, so ties count)."""
    def fields(p):
        return p.get("role", ""), p.get("experience", ""), list(p.get("interests") or [])
    return bool(profile) and fields(profile) != fields(other) and profile["updated_at"] >= other.get("updated_at", "")


@app.post("/api/attendees")
def create_attendee(c: Ctx = Depends(ctx)):
    code = planner.new_attendee(c.g)
    registry_db.create_account(registry(), code)
    return {"code": code}


@app.get("/api/attendees/{code}")
def get_attendee(code: str, c: Ctx = Depends(ctx)):
    ensure_attendee(c, code)
    state, _ = Tools(c.g, code).get_attendee()
    return state


@app.delete("/api/attendees/{code}")
def delete_attendee(code: str):
    """Forget me: the attendee's node in every conference graph (any status), then the account."""
    reg = registry()
    universe = graph()
    graphs = {universe.name: universe} | {conf["graph"]: _handle(conf["graph"]) for conf in registry_db.list_conferences(reg)
                                          if conf["graph"] and conf["graph"] != universe.name}
    for g in graphs.values():  # the nodes first, the account last: a failure part-way can be retried
        planner.forget_attendee(g, code)
    registry_db.delete_account(reg, code)
    return {"deleted": code}


class TalkRef(BaseModel):
    talk: str


class ConceptRef(BaseModel):
    concept: str


@app.post("/api/attendees/{code}/attended")
def attended(code: str, body: TalkRef, c: Ctx = Depends(ctx)):
    ensure_attendee(c, code)
    learned = planner.mark_attended(c.g, code, body.talk)
    return {"learned": learned, "clock": planner.format_minutes(planner.attendee_clock(c.g, code))}


@app.post("/api/attendees/{code}/known")
def known(code: str, body: ConceptRef, c: Ctx = Depends(ctx)):
    ensure_attendee(c, code)
    planner.mark_known(c.g, code, body.concept)
    return {"ok": True}


@app.delete("/api/attendees/{code}/known/{concept}")
def unknown(code: str, concept: str, c: Ctx = Depends(ctx)):
    ensure_attendee(c, code)
    planner.forget_known(c.g, code, concept)
    return {"ok": True}


class Profile(BaseModel):
    role: str = ""
    experience: str = ""
    interests: list[str] = []


@app.put("/api/attendees/{code}/profile")
def put_profile(code: str, body: Profile, c: Ctx = Depends(ctx)):
    """The account first (it follows the attendee to other conferences), then this conference's node."""
    ensure_attendee(c, code)
    try:
        registry_db.set_profile(registry(), code, body.role, body.experience, body.interests)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"profile": planner.set_profile(c.g, code, body.role, body.experience, body.interests)}


@app.post("/api/attendees/{code}/targets")
def add_target(code: str, body: TalkRef, c: Ctx = Depends(ctx)):
    ensure_attendee(c, code)
    return {"targets": planner.add_target(c.g, code, body.talk)}


@app.delete("/api/attendees/{code}/targets/{talk}")
def remove_target(code: str, talk: str, c: Ctx = Depends(ctx)):
    ensure_attendee(c, code)
    return {"targets": planner.remove_target(c.g, code, talk)}


@app.get("/api/attendees/{code}/chat")
def get_chat(code: str, c: Ctx = Depends(ctx)):
    ensure_attendee(c, code)
    return {"messages": planner.chat_history(c.g, code)}


@app.delete("/api/attendees/{code}/chat")
def delete_chat(code: str, c: Ctx = Depends(ctx)):
    ensure_attendee(c, code)
    planner.clear_chat(c.g, code)
    return {"ok": True}


@app.get("/api/concepts")
def list_concepts(c: Ctx = Depends(ctx)):
    rows = c.g.query("MATCH (c:Concept) RETURN c.id, c.name, c.definition ORDER BY toLower(c.name)").result_set
    return [{"id": i, "name": n, "definition": d} for i, n, d in rows]


@app.get("/api/path/{talk}")
def path(talk: str, attendee: str | None = None, c: Ctx = Depends(ctx)):
    return planner.learning_path(c.g, talk, attendee)


@app.get("/api/plan/{talk}")
def plan(talk: str, attendee: str | None = None, c: Ctx = Depends(ctx)):
    try:
        return planner.plan_day(c.g, talk, attendee)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get("/api/graph/{talk}")
def talk_graph(talk: str, attendee: str | None = None, c: Ctx = Depends(ctx)):
    """The plan's path as nodes and edges for the page to draw."""
    try:
        return graph_for_talk(c.g, talk, attendee)
    except (ValueError, IndexError):
        raise HTTPException(404, f"No talk with code {talk}")


def _summary(entry: dict) -> dict:
    keys = ("id", "name", "dates", "start_date", "end_date", "location", "talks", "status", "counts")
    return {k: entry[k] for k in keys}


@app.get("/api/conferences")
def list_conferences():
    """Every conference the registry knows; `loaded` are the ones with a map. The app never hard-codes a conference."""
    entries = registry_db.list_conferences(registry())
    current = next((e for e in entries if e["id"] == registry_db.UNIVERSE_ID), None)
    if current and not current["talks"]:  # Universe's entry is made from settings; its graph has the count
        current["talks"] = graph().query("MATCH (t:Talk) RETURN count(t)").result_set[0][0]
    return {"current": current and _summary(current), "loaded": [_summary(e) for e in entries if e["status"] in BUILT],
            "all": entries}


def _resolver():
    """Name resolution for the pre-check (tests replace this)."""
    return socket.getaddrinfo


class BuildRequest(BaseModel):
    schedule_url: str | None = None


def _known(conf_id: str) -> dict:
    entry = registry_db.get(registry(), conf_id)
    if entry is None:
        raise HTTPException(404, "Unknown conference")
    return entry


@app.post("/api/conferences/{conf_id}/build")
def build_conference(conf_id: str, body: BuildRequest | None = None):
    """Start (or retry) the map for a conference; the build itself runs in the background."""
    _known(conf_id)
    if conf_id == registry_db.UNIVERSE_ID:
        raise HTTPException(409, "This conference's map is maintained separately.")
    url = (body.schedule_url if body else None) or None
    if url and (urlparse(url).scheme not in ("http", "https") or not urlparse(url).netloc):
        raise HTTPException(422, "The schedule link must start with http:// or https://")
    if url:
        try:
            importer.check_url(url, resolve=_resolver())
        except importer.Unresolvable:
            pass  # the build reports a host that doesn't resolve
        except importer.UnsafeURL:
            raise HTTPException(422, "That link can't be fetched safely.")
    return build.start(registry(), conf_id, url)


@app.get("/api/conferences/{conf_id}/build")
def build_status(conf_id: str):
    entry = _known(conf_id)
    return {k: entry[k] for k in ("status", "step", "counts", "reason", "checked_at", "talks")}


@app.get("/api/conferences/nearby")
def conferences_nearby(place: str = "", lat: float | None = None, lon: float | None = None):
    """Conferences happening near a place (typed, or from the browser's location), found by live web search."""
    if lat is not None and not (-90 <= lat <= 90 and -180 <= (lon or 0) <= 180):
        raise HTTPException(422, "Invalid coordinates")
    reg = registry()
    built = [e for e in registry_db.list_conferences(reg) if e["status"] in BUILT]
    return nearby.nearby(lambda found: registry_db.upsert_found(reg, found), place=place, lat=lat, lon=lon, built=built)


@app.get("/api/flow")
def conference_flow(attendee: str | None = None, include: str = "", c: Ctx = Depends(ctx)):
    """The conference as a left-to-right flow of 'prepares you for' links, for the landing page.
    include: comma-separated talk codes that must be on the map (the chat's picks)."""
    return flow.flow(c.g, attendee, include=[x.strip() for x in include.split(",") if x.strip()])


@app.get("/api/featured")
def featured_talks(attendee: str | None = None, c: Ctx = Depends(ctx)):
    """Don't-miss talks: keynotes, then the talks that prepare you for the most others."""
    return flow.featured(c.g, attendee)


# --- the agent ---

class AgentTurn(BaseModel):
    attendee: str
    message: str
    history: list[dict] = []  # ignored: the server keeps the conversation
    page: str = "talk"  # "landing" when the attendee describes a goal on the conference map


@app.post("/api/agent")
def agent(body: AgentTurn, c: Ctx = Depends(ctx)):
    ensure_attendee(c, body.attendee)
    g = c.g
    # The stored conversation, not what the browser sends, so it survives a refresh and can't be forged.
    history = [{"role": m["role"], "content": m["content"]} for m in planner.chat_history(g, body.attendee)
               if m.get("role") in ("user", "assistant") and m.get("content")]
    page = "landing" if body.page == "landing" else "talk"
    turn = run_agent(g, body.attendee, body.message[:2000], history, public=c.public, page=page)
    view = turn.get("view") or {}
    reply = {"role": "assistant", "content": turn.get("reply") or "", "page": page}
    if view.get("talk"):
        reply["talk"] = view["talk"]
    if turn.get("highlight"):
        reply["highlight"] = turn["highlight"]
    planner.append_chat(g, body.attendee, [{"role": "user", "content": body.message[:2000], "page": page}, reply])
    node, reg = planner.get_profile(g, body.attendee), registry()
    if _newer(node, registry_db.get_profile(reg, body.attendee)):  # the agent saved a profile: it follows the attendee too
        registry_db.set_profile(reg, body.attendee, node["role"], node["experience"], node["interests"])
    return turn


app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
