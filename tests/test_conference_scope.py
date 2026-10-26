import pytest

from throughline.agent import conference_of, system_prompt, tools_for
from throughline.catalog import to_minutes
from throughline.config import settings
from throughline.graph import connect, upsert_conference
from throughline.planner import attendee_clock, default_clock, new_attendee

QCON = {
    "id": "qcon-san-francisco-2026", "name": "QCon San Francisco 2026", "dates": "Nov 16–20, 2026",
    "start_date": "2026-11-16", "end_date": "2026-11-20", "location": "San Francisco, CA",
    "clock_start": "2026-11-16T08:30", "url": "https://qconsf.com/",
}


def fresh_graph():
    try:
        g = connect("throughline_test_scope", local=True)
        g.query("RETURN 1")
    except Exception as e:  # FalkorDB isn't running
        pytest.skip(f"FalkorDB not reachable: {e}")
    try:
        g.delete()
    except Exception:
        pass
    return connect("throughline_test_scope", local=True)


@pytest.fixture
def graph():
    g = fresh_graph()
    upsert_conference(g, QCON)
    yield g
    g.delete()


@pytest.fixture
def empty_graph():
    g = fresh_graph()
    g.query("RETURN 1")
    yield g
    g.delete()


def test_new_attendee_starts_at_the_graphs_clock(graph):
    assert attendee_clock(graph, new_attendee(graph)) == to_minutes("2026-11-16", "08:30")


def test_system_prompt_names_the_graphs_conference(graph):
    assert "QCon San Francisco 2026 (Nov 16–20, 2026, San Francisco, CA)" in system_prompt(conference_of(graph))


def test_graph_without_conference_falls_back_to_settings(empty_graph):
    assert default_clock(empty_graph) == to_minutes(*settings.clock_start.split("T"))
    assert conference_of(empty_graph)["name"] == settings.conference_name


def test_conference_node_without_clock_falls_back_to_settings(empty_graph):
    empty_graph.query("CREATE (:Conference {id: 'old', name: 'Old Name'})")
    assert default_clock(empty_graph) == to_minutes(*settings.clock_start.split("T"))
    conf = conference_of(empty_graph)
    assert conf["name"] == "Old Name"
    assert conf["location"] == settings.conference_location


def add_talks(g, days):
    for i, (date, day) in enumerate(days):
        g.query("CREATE (:Talk {code: $c, date: $d, day: $day})", {"c": f"T{i}", "d": date, "day": day})


def search_enum(conf):
    tool = next(t for t in tools_for(conf) if t["function"]["name"] == "search_talks")
    return tool["function"]["parameters"]["properties"]["day"]["enum"]


def test_universe_days_keep_the_current_wording(empty_graph):
    add_talks(empty_graph, [("2026-10-29", "Thursday"), ("2026-10-28", "Wednesday"), ("2026-10-28", "Wednesday")])
    conf = conference_of(empty_graph)
    assert conf["days"] == [{"date": "2026-10-28", "day": "Wednesday"}, {"date": "2026-10-29", "day": "Thursday"}]
    assert ("Times: start_min/end_min are minutes. Day 1 is Wednesday 2026-10-28, day 2 Thursday 2026-10-29.\n"
            in system_prompt(conf))
    assert search_enum(conf) == ["Wednesday", "Thursday", "any"]


def test_other_conference_days_follow_its_talks(empty_graph):
    add_talks(empty_graph, [("2026-11-16", "Monday"), ("2026-11-17", "Tuesday")])
    conf = conference_of(empty_graph)
    assert "Day 1 is Monday 2026-11-16, day 2 Tuesday 2026-11-17." in system_prompt(conf)
    assert search_enum(conf) == ["Monday", "Tuesday", "any"]


def test_no_talks_means_no_day_sentence(empty_graph):
    conf = conference_of(empty_graph)
    assert conf["days"] == []
    assert "Day 1" not in system_prompt(conf)
    assert search_enum(conf) == ["any"]
