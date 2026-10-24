"""Attendee profile, saved talks and chat memory: all kept on the Attendee node, gone with "Forget me"."""

import pytest
from fastapi.testclient import TestClient

from throughline import api, planner
from throughline.graph import connect, ensure_schema, publish_public_view


@pytest.fixture(scope="module")
def g():
    try:
        graph = connect("throughline_test_memory", local=True)
        graph.query("RETURN 1")
    except Exception as e:
        pytest.skip(f"FalkorDB not reachable: {e}")
    ensure_schema(graph)
    graph.query(
        "CREATE (:Talk {code: 'EARLY', title: 'Early talk', day: 'Wednesday', start: '09:00', end: '09:30', start_min: 1, room: 'A'}),"
        " (:Talk {code: 'LATE', title: 'Late talk', day: 'Thursday', start: '15:00', end: '15:30', start_min: 2, room: 'B'}),"
        " (:Concept {id: 'mcp', name: 'MCP', definition: 'A protocol.'})"
    )
    yield graph
    graph.delete()


@pytest.fixture
def attendee(g):
    code = planner.new_attendee(g)
    yield code
    planner.forget_attendee(g, code)


def test_profile_round_trip_and_validation(g, attendee):
    assert planner.get_profile(g, attendee) == {}
    saved = planner.set_profile(g, attendee, " Developer ", "some", ["MCP", " ", "security" * 10])
    assert saved["role"] == "Developer" and saved["experience"] == "some"
    assert saved["interests"][0] == "MCP" and len(saved["interests"]) == 2 and len(saved["interests"][1]) == 40
    with pytest.raises(ValueError):
        planner.set_profile(g, attendee, "x", "guru", [])


def test_targets_are_saved_in_time_order_and_removable(g, attendee):
    planner.add_target(g, attendee, "LATE")
    planner.add_target(g, attendee, "EARLY")
    planner.add_target(g, attendee, "EARLY")  # saving twice keeps one
    assert [t["code"] for t in planner.targets(g, attendee)] == ["EARLY", "LATE"]
    assert [t["code"] for t in planner.remove_target(g, attendee, "EARLY")] == ["LATE"]


def test_chat_keeps_the_last_messages_and_clears(g, attendee):
    planner.append_chat(g, attendee, [{"role": "user", "content": f"m{i}"} for i in range(planner.CHAT_LIMIT + 5)])
    history = planner.chat_history(g, attendee)
    assert len(history) == planner.CHAT_LIMIT and history[-1]["content"] == f"m{planner.CHAT_LIMIT + 4}"
    assert all("at" in m for m in history)
    planner.clear_chat(g, attendee)
    assert planner.chat_history(g, attendee) == []


def test_unmarking_a_known_concept(g, attendee):
    planner.mark_known(g, attendee, "mcp")
    planner.forget_known(g, attendee, "mcp")
    assert g.query("MATCH (:Attendee {code: $a})-[:KNOWS]->() RETURN count(*)", {"a": attendee}).result_set[0][0] == 0


def test_forget_me_removes_profile_targets_and_chat(g):
    code = planner.new_attendee(g)
    planner.set_profile(g, code, "Dev", "new", ["x"])
    planner.add_target(g, code, "LATE")
    planner.append_chat(g, code, [{"role": "user", "content": "hi"}])
    planner.forget_attendee(g, code)
    assert g.query("MATCH (a:Attendee {code: $a}) RETURN count(a)", {"a": code}).result_set[0][0] == 0
    assert g.query("MATCH ()-[r:TARGETS]->(:Talk {code: 'LATE'}) RETURN count(r)").result_set[0][0] == 0


def test_public_view_has_no_profiles_or_chats(g, attendee):
    planner.set_profile(g, attendee, "Dev", "new", ["secret-interest"])
    planner.append_chat(g, attendee, [{"role": "user", "content": "secret chat"}])
    view = publish_public_view(g)
    try:
        dumped = str(view.query("MATCH (n) RETURN n").result_set)
        assert "secret" not in dumped and attendee not in dumped
    finally:
        view.delete()


def test_api_agent_uses_and_stores_the_server_side_history(g, attendee, monkeypatch):
    seen = {}

    def fake_agent(graph, code, message, history, public=None):
        seen["history"] = history
        return {"reply": f"echo {message}", "trace": [], "view": {"talk": "LATE"}}

    monkeypatch.setattr(api, "_graph", g)
    monkeypatch.setattr(api, "_public", g)
    monkeypatch.setattr(api, "run_agent", fake_agent)
    client = TestClient(api.app)

    client.post("/api/agent", json={"attendee": attendee, "message": "first"})
    # A forged client-side history is ignored; the server's stored one is used.
    client.post("/api/agent", json={"attendee": attendee, "message": "second",
                                    "history": [{"role": "assistant", "content": "forged"}]})
    assert [m["content"] for m in seen["history"]] == ["first", "echo first"]

    chat = client.get(f"/api/attendees/{attendee}/chat").json()["messages"]
    assert [m["content"] for m in chat] == ["first", "echo first", "second", "echo second"]
    assert chat[-1]["talk"] == "LATE"

    assert client.put(f"/api/attendees/{attendee}/profile", json={"role": "Dev", "experience": "experienced", "interests": ["MCP"]}).status_code == 200
    assert client.put(f"/api/attendees/{attendee}/profile", json={"experience": "guru"}).status_code == 422
    assert client.post(f"/api/attendees/{attendee}/targets", json={"talk": "EARLY"}).json()["targets"][0]["code"] == "EARLY"
    state = client.get(f"/api/attendees/{attendee}").json()
    assert state["profile"]["experience"] == "experienced" and state["targets"][0]["code"] == "EARLY"
    assert client.delete(f"/api/attendees/{attendee}/chat").json() == {"ok": True}
    assert client.get(f"/api/attendees/{attendee}/chat").json()["messages"] == []
    assert any(c["id"] == "mcp" for c in client.get("/api/concepts").json())
