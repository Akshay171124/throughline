"""The registry graph: conferences with build status, and attendee accounts."""

import pytest

from throughline import registry
from throughline.graph import connect

AIE = {"name": "AI Engineer World's Fair", "url": "https://ai.engineer/", "start_date": "2026-11-10", "end_date": "2026-11-12"}
AIE_DETAIL = {"name": "AI Engineer Summit", "url": "https://ai.engineer/code/2026", "start_date": "2026-11-10"}


@pytest.fixture
def reg():
    try:
        graph = connect("throughline_test_registry", local=True)
        graph.query("RETURN 1")
    except Exception as e:
        pytest.skip(f"FalkorDB not reachable: {e}")
    yield graph
    graph.delete()


def test_conference_id_slugs_and_adds_year():
    assert registry.conference_id("QCon San Francisco", "2026-11-16") == "qcon-san-francisco-2026"
    assert registry.conference_id("QCon San Francisco 2026", "2026-11-16") == "qcon-san-francisco-2026"


def test_same_conference_by_domain_and_dates():
    assert registry.same_conference(AIE, AIE_DETAIL)
    assert not registry.same_conference(AIE, {**AIE_DETAIL, "start_date": "2026-06-03"})


def test_same_conference_falls_back_to_names_without_dates():
    assert registry.same_conference({"name": "GitHub Universe 2026", "url": "https://a.com"}, {"name": "GitHub Universe", "url": "https://b.com", "start_date": ""})
    assert not registry.same_conference({"name": "QCon San Francisco", "url": ""}, {"name": "GitHub Universe 2026", "url": ""})


def test_upsert_found_merges_duplicates(reg):
    registry.ensure_universe(reg)
    first = registry.upsert_found(reg, AIE)
    second = registry.upsert_found(reg, AIE_DETAIL)
    assert first["id"] == second["id"] and first["status"] == "none"
    assert len(registry.list_conferences(reg)) == 2  # Universe + AI Engineer


def test_same_conference_needs_overlapping_dates_even_by_name():
    last_year = {"name": "GitHub Universe 2025", "url": "https://githubuniverse.com/", "start_date": "2025-10-28", "end_date": "2025-10-29"}
    this_year = {"name": "GitHub Universe 2026", "url": "", "start_date": "2026-10-28", "end_date": "2026-10-29"}
    assert not registry.same_conference(last_year, this_year)


def test_new_entries_have_no_graph_until_built(reg):
    c = registry.upsert_found(reg, AIE)
    assert c["graph"] == "" and c["status"] == "none"


def test_upsert_found_matches_universe_without_a_url(reg):
    registry.ensure_universe(reg)
    found = {"name": "GitHub Universe 2026", "url": "https://githubuniverse.com/", "start_date": "2026-10-28", "end_date": "2026-10-29"}
    assert registry.upsert_found(reg, found)["id"] == "universe26"
    assert len(registry.list_conferences(reg)) == 1


def test_ensure_universe(reg):
    u = registry.ensure_universe(reg)
    assert u["id"] == registry.UNIVERSE_ID and u["status"] == "ready" and u["graph"] == "throughline" and u["clock_start"]
    registry.ensure_universe(reg)
    assert len(registry.list_conferences(reg)) == 1


def test_set_status_round_trips_counts(reg):
    c = registry.upsert_found(reg, AIE)
    assert c["checked_at"] is None
    registry.set_status(reg, c["id"], status="partial", counts={"kept": 12, "no_time": 8})
    got = registry.get(reg, c["id"])
    assert got["status"] == "partial" and got["counts"] == {"kept": 12, "no_time": 8} and got["checked_at"]


def test_mark_interrupted(reg):
    c = registry.upsert_found(reg, AIE)
    registry.set_status(reg, c["id"], status="building")
    assert registry.mark_interrupted(reg) == 1
    got = registry.get(reg, c["id"])
    assert got["status"] == "failed" and got["reason"] == "The build was interrupted"
    assert registry.mark_interrupted(reg) == 0


def test_account_profile_round_trip(reg):
    registry.create_account(reg, "ABCD-EFGH-JKMN")
    assert registry.account_exists(reg, "ABCD-EFGH-JKMN") and not registry.account_exists(reg, "NOPE")
    assert registry.get_profile(reg, "ABCD-EFGH-JKMN") == {}
    saved = registry.set_profile(reg, "ABCD-EFGH-JKMN", " Developer ", "some", ["MCP", " "])
    assert registry.get_profile(reg, "ABCD-EFGH-JKMN") == saved
    assert saved["role"] == "Developer" and saved["experience"] == "some" and saved["interests"] == ["MCP"] and saved["updated_at"]
    with pytest.raises(ValueError):
        registry.set_profile(reg, "ABCD-EFGH-JKMN", "x", "guru", [])
    registry.delete_account(reg, "ABCD-EFGH-JKMN")
    assert not registry.account_exists(reg, "ABCD-EFGH-JKMN")


@pytest.mark.parametrize("dates, start, end", [
    ("November 16-20, 2026", "2026-11-16", "2026-11-20"),
    ("Nov 10–12, 2026", "2026-11-10", "2026-11-12"),
    ("Oct 30–Nov 2, 2026", "2026-10-30", "2026-11-02"),
    ("Dec 30, 2026 – Jan 2, 2027", "2026-12-30", "2027-01-02"),
    ("16-20 November 2026", "2026-11-16", "2026-11-20"),
    ("2026-11-16 to 2026-11-18", "2026-11-16", "2026-11-18"),
    ("Sept 29 - Oct 1", "2026-09-29", "2026-10-01"),
    ("29 October 2026", "2026-10-29", ""),  # one day: no range to read
    ("November 2026", "2026-11-01", ""),
    ("Nov 20-16, 2026", "2026-11-20", ""),  # ends before it starts: not trusted
    ("Nov 16-20, 2026", "", ""),  # no start date to anchor it
])
def test_end_date_from_the_dates_text(dates, start, end):
    assert registry.end_date_from(dates, start) == end


def test_upsert_found_reads_the_end_date_from_the_dates_text(reg):
    # The nearby search gives only a start date; "November 16-20" still means the conference runs to the 20th.
    qcon = {"name": "QCon San Francisco 2026", "dates": "November 16-20, 2026", "url": "https://qconsf.com/",
            "start_date": "2026-11-16"}
    assert registry.upsert_found(reg, qcon)["end_date"] == "2026-11-20"


def test_upsert_found_fills_a_missing_end_date_on_an_existing_entry(reg):
    qcon = {"name": "QCon San Francisco 2026", "dates": "November 16-20, 2026", "url": "https://qconsf.com/",
            "start_date": "2026-11-16"}
    registry.upsert_found(reg, {**qcon, "dates": ""})  # saved before the end date was read
    entry = registry.upsert_found(reg, qcon)
    assert entry["end_date"] == "2026-11-20"
    assert registry.get(reg, entry["id"])["end_date"] == "2026-11-20"
