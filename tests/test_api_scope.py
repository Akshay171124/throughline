"""Every API request is about one conference's graph; an attendee's account and profile follow them across conferences."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from throughline import api, planner, registry
from throughline.catalog import to_minutes
from throughline.config import settings
from throughline.graph import connect, ensure_schema, public_name, upsert_conference

A, B, REG = "throughline_test_api_a", "throughline_test_api_b", "throughline_test_api_registry"
QCON = {
    "id": "qcon-san-francisco-2026", "name": "QCon San Francisco 2026", "dates": "Nov 16–20, 2026",
    "start_date": "2026-11-16", "end_date": "2026-11-20", "location": "San Francisco, CA",
    "clock_start": "2026-11-16T08:30", "url": "https://qconsf.com/",
}
TALK = ("CREATE (:Talk {code: $code, title: $title, type: 'Keynote', day: $day, date: $date, start: '09:00', end: '09:30',"
        " start_min: $start, end_min: $end, room: 'Main'}), (:Concept {id: $concept, name: $concept, definition: 'x'})")


def fresh(name):
    g = connect(name, local=True)
    try:
        g.delete()
    except Exception:  # nothing to delete
        pass
    return connect(name, local=True)


def count_attendees(g, code):
    return g.query("MATCH (a:Attendee {code: $c}) RETURN count(a)", {"c": code}).result_set[0][0]


@pytest.fixture
def world(monkeypatch):
    try:
        connect(REG, local=True).query("RETURN 1")
    except Exception as e:
        pytest.skip(f"FalkorDB not reachable: {e}")
    reg, a, b = fresh(REG), fresh(A), fresh(B)
    for g, conf, code, date in ((a, None, "UNI1", "2026-10-28"), (b, QCON, "QCON1", "2026-11-16")):
        ensure_schema(g)
        upsert_conference(g, conf)
        start = to_minutes(date, "09:00")
        g.query(TALK, {"code": code, "title": f"{code} keynote", "day": "Monday", "date": date,
                       "start": start, "end": start + 30, "concept": code.lower()})
    registry.ensure_universe(reg)
    registry.set_status(reg, registry.UNIVERSE_ID, graph=A)
    qcon = registry.upsert_found(reg, QCON)
    registry.set_status(reg, qcon["id"], graph=B, status="ready", clock_start=QCON["clock_start"])
    monkeypatch.setattr(api, "registry", lambda: reg)
    graphs = {A: a, public_name(A): a, B: b, public_name(B): b}
    monkeypatch.setattr(api, "_graphs", graphs)
    yield SimpleNamespace(reg=reg, a=a, b=b, graphs=graphs, qcon=qcon["id"], client=TestClient(api.app))
    for g in (reg, a, b):
        g.delete()


def test_flow_and_talks_never_mix(world):
    c = world.client
    assert [t["code"] for t in c.get(f"/api/talks?conf={world.qcon}").json()] == ["QCON1"]
    codes = {n["code"] for n in c.get("/api/flow", headers={"X-Conference": world.qcon}).json()["nodes"]}
    assert codes == {"QCON1"}
    assert [t["code"] for t in c.get("/api/talks").json()] == ["UNI1"]  # no conference given: Universe
    assert c.get("/api/clock", params={"conf": world.qcon}).json() == {"now": QCON["clock_start"], "conference": QCON["name"]}
    assert c.get("/api/health", params={"conf": world.qcon}).json()["graph"] == B


def test_query_beats_header(world):
    talks = world.client.get("/api/talks", params={"conf": world.qcon}, headers={"X-Conference": registry.UNIVERSE_ID}).json()
    assert [t["code"] for t in talks] == ["QCON1"]


def test_unbuilt_conference_is_409(world):
    found = registry.upsert_found(world.reg, {"name": "AI Engineer Summit", "url": "https://ai.engineer/", "start_date": "2026-11-10"})
    r = world.client.get(f"/api/talks?conf={found['id']}")
    assert r.status_code == 409 and r.json()["detail"] == "This conference's map isn't built yet"


def test_unknown_conference_is_404(world):
    r = world.client.get("/api/talks?conf=no-such-conference")
    assert r.status_code == 404 and r.json()["detail"] == "Unknown conference"


def test_profile_follows_the_attendee_across_conferences(world):
    c = world.client
    code = c.post(f"/api/attendees?conf={registry.UNIVERSE_ID}").json()["code"]
    assert registry.account_exists(world.reg, code) and count_attendees(world.a, code) == 1
    assert c.put(f"/api/attendees/{code}/profile?conf={registry.UNIVERSE_ID}",
                 json={"role": "Dev", "experience": "some", "interests": ["MCP"]}).status_code == 200
    assert registry.get_profile(world.reg, code)["experience"] == "some"
    r = c.get(f"/api/attendees/{code}?conf={world.qcon}")
    assert r.status_code == 200 and r.json()["profile"]["experience"] == "some"
    # The QCon node starts at QCon's clock, not Universe's.
    clock = world.b.query("MATCH (a:Attendee {code: $c}) RETURN a.clock_min", {"c": code}).result_set[0][0]
    assert clock == to_minutes("2026-11-16", "08:30")
    # A later change made at QCon reaches Universe.
    c.put(f"/api/attendees/{code}/profile?conf={world.qcon}", json={"experience": "experienced"})
    assert c.get(f"/api/attendees/{code}").json()["profile"]["experience"] == "experienced"


def test_unknown_attendee_is_404(world):
    assert world.client.get(f"/api/attendees/NOPE-NOPE-NOPE?conf={world.qcon}").status_code == 404
    assert count_attendees(world.b, "NOPE-NOPE-NOPE") == 0


def test_forget_me_removes_everywhere(world):
    c = world.client
    code = c.post("/api/attendees").json()["code"]
    assert c.get(f"/api/attendees/{code}?conf={world.qcon}").status_code == 200
    assert count_attendees(world.b, code) == 1
    assert c.delete(f"/api/attendees/{code}").json() == {"deleted": code}
    assert count_attendees(world.a, code) == 0 and count_attendees(world.b, code) == 0
    assert not registry.account_exists(world.reg, code)
    assert c.get(f"/api/attendees/{code}").status_code == 404


def test_existing_universe_attendee_is_migrated(world):
    world.a.query("CREATE (:Attendee {code: 'OLD1-OLD1-OLD1', experience: 'new', clock_min: $m})",
                  {"m": to_minutes("2026-10-28", "08:30")})
    api.migrate_accounts(world.reg, world.a)
    api.migrate_accounts(world.reg, world.a)  # running again adds nothing
    assert registry.account_exists(world.reg, "OLD1-OLD1-OLD1")
    assert world.reg.query("MATCH (a:Account) RETURN count(a)").result_set[0][0] == 1
    assert registry.get_profile(world.reg, "OLD1-OLD1-OLD1")["experience"] == "new"
    assert world.client.get("/api/attendees/OLD1-OLD1-OLD1").status_code == 200
    r = world.client.get(f"/api/attendees/OLD1-OLD1-OLD1?conf={world.qcon}")
    assert r.status_code == 200 and r.json()["profile"]["experience"] == "new"


def test_startup_marks_interrupted_builds(world):
    registry.set_status(world.reg, world.qcon, status="building")  # a retry of a built map
    first = registry.upsert_found(world.reg, {"name": "AI Engineer Code Summit 2026", "url": "https://ai.engineer/"})
    registry.set_status(world.reg, first["id"], status="building")  # a first build
    # startup points Universe back at its real graph name
    world.graphs.update({settings.graph_name: world.a, public_name(settings.graph_name): world.a})
    with TestClient(api.app):
        pass
    assert registry.get(world.reg, world.qcon)["status"] == "ready"  # the map stays open
    assert registry.get(world.reg, first["id"])["status"] == "failed"
    assert registry.get(world.reg, registry.UNIVERSE_ID)["status"] == "ready"


def test_profile_the_agent_saves_reaches_the_account(world, monkeypatch):
    def fake_agent(graph, code, message, history, public=None, page="talk"):
        assert graph is world.b and public is world.b
        planner.set_profile(graph, code, "SRE", "experienced", ["latency"])
        return {"reply": "saved", "trace": []}

    monkeypatch.setattr(api, "run_agent", fake_agent)
    code = world.client.post("/api/attendees").json()["code"]
    world.client.post(f"/api/agent?conf={world.qcon}", json={"attendee": code, "message": "I'm an SRE"})
    assert registry.get_profile(world.reg, code)["experience"] == "experienced"
    assert world.client.get(f"/api/attendees/{code}").json()["profile"]["role"] == "SRE"
