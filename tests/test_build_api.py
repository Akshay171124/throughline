"""The build endpoints, nearby results with registry status, Google redirect links, readings on first open."""

import socket
import threading
from datetime import date

import pytest
from fastapi.testclient import TestClient

from throughline import api, briefing, build, nearby, registry
from throughline.graph import connect

from .test_api_scope import world  # noqa: F401  (the two-conference fixture)


def test_build_endpoint_validates_and_starts(world, monkeypatch):
    calls = []

    def start(reg, conf_id, schedule_url=None, deps=None):
        calls.append((conf_id, schedule_url))
        return {**registry.get(reg, conf_id), "status": "building"}

    monkeypatch.setattr(build, "start", start)
    c = world.client
    assert c.post("/api/conferences/no-such/build", json={}).status_code == 404
    assert c.get("/api/conferences/no-such/build").status_code == 404
    assert c.post(f"/api/conferences/{world.qcon}/build", json={"schedule_url": "javascript:x"}).status_code == 422
    assert calls == []
    r = c.post(f"/api/conferences/{world.qcon}/build", json={"schedule_url": "https://qconsf.com/schedule"})
    assert r.status_code == 200 and r.json()["status"] == "building"
    assert calls == [(world.qcon, "https://qconsf.com/schedule")]
    r = c.post(f"/api/conferences/{registry.UNIVERSE_ID}/build", json={})
    assert r.status_code == 409 and r.json()["detail"] == "This conference's map is maintained separately."
    assert len(calls) == 1


def test_build_status_and_conference_lists(world):
    c = world.client
    found = registry.upsert_found(world.reg, {"name": "AI Engineer Summit", "url": "https://ai.engineer/", "start_date": "2026-11-10"})
    status = c.get(f"/api/conferences/{found['id']}/build").json()
    assert set(status) == {"status", "step", "counts", "reason", "checked_at", "talks"} and status["status"] == "none"
    listing = c.get("/api/conferences").json()
    assert listing["current"]["id"] == registry.UNIVERSE_ID
    assert {x["id"] for x in listing["loaded"]} == {registry.UNIVERSE_ID, world.qcon}
    assert {x["id"] for x in listing["all"]} == {registry.UNIVERSE_ID, world.qcon, found["id"]}
    assert {"id", "name", "dates", "location", "talks", "status", "counts"} <= set(listing["loaded"][0])


def test_forget_me_reaches_unbuilt_graphs_too(world):
    registry.set_status(world.reg, world.qcon, status="failed")  # a failed retry still has a graph
    code = world.client.post("/api/attendees").json()["code"]
    world.b.query("MERGE (a:Attendee {code: $c})", {"c": code})
    world.client.delete(f"/api/attendees/{code}")
    assert world.b.query("MATCH (a:Attendee {code: $c}) RETURN count(a)", {"c": code}).result_set[0][0] == 0


def test_google_redirects_are_unwrapped():
    assert nearby._unwrap("https://www.google.com/url?q=https%3A%2F%2Fqconsf.com%2F&sa=U") == "https://qconsf.com/"
    assert nearby._unwrap("https://www.google.com/url?url=https%3A%2F%2Fqconsf.com%2F") == "https://qconsf.com/"
    assert nearby._unwrap("https://www.google.com/goto?url=CAESUAHr") is None
    assert nearby._unwrap("https://www.google.com/url?q=javascript:x") is None
    assert nearby._unwrap("https://www.google.com/search?q=qcon") is None
    assert nearby._unwrap("https://qconsf.com/") == "https://qconsf.com/"


def test_extract_grounds_on_unwrapped_urls(monkeypatch):
    seen = {}

    class Fake:
        def __init__(self, **kw):
            self.chat = self
            self.completions = self

        def create(self, **kw):
            seen["prompt"] = kw["messages"][1]["content"]
            body = '{"conferences": [{"name": "QCon SF", "dates": "", "start_date": "2026-11-16", "location": "", "url": "https://qconsf.com/", "snippet": ""}]}'
            return type("R", (), {"choices": [type("C", (), {"message": type("M", (), {"content": body})()})()]})()

    monkeypatch.setattr(nearby, "OpenAI", Fake)
    results = [{"title": "QCon", "url": "https://www.google.com/url?q=https%3A%2F%2Fqconsf.com%2F", "snippet": ""},
               {"title": "x", "url": "https://www.google.com/search?q=x", "snippet": ""}]
    out = nearby._extract("San Francisco", date(2026, 10, 24), results)
    assert [c["url"] for c in out] == ["https://qconsf.com/"]
    assert "google.com" not in seen["prompt"]


def test_nearby_results_carry_registry_status(monkeypatch, tmp_path):
    monkeypatch.setattr(nearby, "CACHE_FILE", tmp_path / "nearby.json")
    monkeypatch.setattr(nearby, "_search", lambda place, today: ["r"])
    monkeypatch.setattr(nearby, "_extract", lambda place, today, results: [
        {"name": "QCon San Francisco 2026", "dates": "", "start_date": "2026-11-16", "location": "SF", "url": "https://qconsf.com/", "snippet": ""}])
    entry = {"id": "qcon-san-francisco-2026", "status": "not_found", "reason": "r", "checked_at": "2026-10-25T00:00:00+00:00", "counts": {}}
    out = nearby.nearby(lambda found: entry, place="San Francisco")
    c = out["conferences"][0]
    assert (c["id"], c["status"], c["reason"], c["checked_at"], c["counts"]) == ("qcon-san-francisco-2026", "not_found", "r", entry["checked_at"], {})
    assert c["loaded"] is False


def test_briefing_builds_on_first_open(world, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    world.b.query("MATCH (t:Talk {code: 'QCON1'}) SET t.abstract = 'About tracing.'")
    world.b.query("CREATE (:Talk {code: 'EMPTY1', title: 'No abstract', abstract: ''})")
    gate, built, stored = threading.Event(), [], threading.Event()

    def fake_build(client, g, code):
        built.append(code)
        gate.wait(5)
        return {"code": code, "summary": "A summary.", "summary_source": "s", "readings": [], "fetched_at": "t"}

    def fake_store(g, b):
        stored.set()

    monkeypatch.setattr(briefing, "build", fake_build)
    monkeypatch.setattr(briefing, "store", fake_store)
    c = world.client
    first = c.get(f"/api/talks/QCON1/briefing?conf={world.qcon}").json()
    second = c.get(f"/api/talks/QCON1/briefing?conf={world.qcon}").json()
    assert first["status"] == "building" and second["status"] == "building"
    assert c.get(f"/api/talks/EMPTY1/briefing?conf={world.qcon}").json()["status"] == "none"
    gate.set()
    assert stored.wait(5)
    assert built == ["QCON1"]


def test_briefing_failure_returns_to_missing(world, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    world.b.query("MATCH (t:Talk {code: 'QCON1'}) SET t.abstract = 'About tracing.'")
    done = threading.Event()

    def boom(client, g, code):
        done.set()
        raise RuntimeError("search failed")

    monkeypatch.setattr(briefing, "build", boom)
    c = world.client
    assert c.get(f"/api/talks/QCON1/briefing?conf={world.qcon}").json()["status"] == "building"
    assert done.wait(5)
    for t in list(briefing._running.values()):
        t.join(5)
    assert c.get(f"/api/talks/QCON1/briefing?conf={world.qcon}").json()["status"] == "building"  # a later open retries


def test_build_refuses_unsafe_schedule_links(world, monkeypatch):
    calls = []
    monkeypatch.setattr(build, "start", lambda reg, cid, url=None, deps=None: calls.append(url) or registry.get(reg, cid))
    hosts = {"internal.example": "10.0.0.9", "public.example": "93.184.216.34"}

    def resolve(host, port):
        if host not in hosts:
            raise socket.gaierror("nope")
        return [(0, 0, 0, "", (hosts[host], 0))]

    monkeypatch.setattr(api, "_resolver", lambda: resolve)
    post = lambda url: world.client.post(f"/api/conferences/{world.qcon}/build", json={"schedule_url": url})
    for bad in ("http://127.0.0.1/x", "http://10.0.0.5/", "http://internal.example/s"):
        r = post(bad)
        assert r.status_code == 422 and r.json()["detail"] == "That link can't be fetched safely."
    assert calls == []
    assert post("https://public.example/schedule").status_code == 200
    assert post("https://unresolvable.example/").status_code == 200  # the build reports a host that doesn't resolve
    assert calls == ["https://public.example/schedule", "https://unresolvable.example/"]


def test_google_redirects_relative_and_other_domains():
    assert nearby._unwrap("/url?q=https%3A%2F%2Fqconsf.com%2F") == "https://qconsf.com/"
    assert nearby._unwrap("/goto?url=CAES") is None
    assert nearby._unwrap("https://www.google.co.uk/url?q=https://x.org/") == "https://x.org/"
    assert nearby._unwrap("https://www.google.de/search?q=x") is None
    assert nearby._unwrap("https://notgoogle.com/url?q=https://x.org/") == "https://notgoogle.com/url?q=https://x.org/"


def test_extract_lists_a_site_reached_twice_once(monkeypatch):
    seen = {}

    class Fake:
        def __init__(self, **kw):
            self.chat = self
            self.completions = self

        def create(self, **kw):
            seen["prompt"] = kw["messages"][1]["content"]
            return type("R", (), {"choices": [type("C", (), {"message": type("M", (), {"content": '{"conferences": []}'})()})()]})()

    monkeypatch.setattr(nearby, "OpenAI", Fake)
    nearby._extract("SF", date(2026, 10, 24), [
        {"title": "A", "url": "https://qconsf.com/", "snippet": ""},
        {"title": "B", "url": "https://www.google.com/url?q=https%3A%2F%2Fqconsf.com%2F", "snippet": ""}])
    assert seen["prompt"].count("URL: https://qconsf.com/") == 1
