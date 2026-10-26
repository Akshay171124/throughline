"""Finding the schedule page and reading talks from it; every title and time is checked against the page."""

from collections import Counter
from pathlib import Path

from throughline.importer import Page, find_schedule, parse_page, parse_time, read_listing, verify_listing

SITES = Path(__file__).parent / "fixtures" / "sites"
QCON = "https://qconsf.com/schedule/nov2026"
TITLE = "Live Resharding Without Regret: Lessons from Building Valkey's Atomic Slot Migration"


def qcon_page() -> Page:
    return parse_page(QCON, (SITES / "qcon_schedule.html").read_text())


def raw_talk(title, time_text="10:35AM PST", start="10:35", **extra):
    return {"title": title, "date": "2026-11-16", "time_text": time_text, "start": start, "end": None,
            "duration_text": None, "room": None, "track": None, "type": None, "level": None,
            "speakers": [], "abstract": None, "detail_url": None, "sponsored": False, **extra}


def test_hops_to_the_schedule_link():
    home = Page("https://qconsf.com/", "", "Welcome to QCon", [("Schedule", QCON)])
    schedule = Page(QCON, "", "Monday talks", [])
    pages = {"https://qconsf.com/": home, QCON: schedule}
    answers = iter([{"is_schedule": False, "link": QCON}, {"is_schedule": True, "link": None}])
    page, tried = find_schedule("https://qconsf.com/", fetch=lambda url: pages[url], ask=lambda *a: next(answers))
    assert page is schedule
    assert tried == ["https://qconsf.com/", QCON]


def test_link_not_on_page_is_refused():
    home = Page("https://qconsf.com/", "", "Welcome", [("Schedule", QCON)])
    page, tried = find_schedule("https://qconsf.com/", fetch=lambda url: home,
                                ask=lambda *a: {"is_schedule": False, "link": "https://evil.example/x"})
    assert page is None
    assert tried == ["https://qconsf.com/"]


def test_invented_title_is_dropped():
    kept, dropped = verify_listing(qcon_page(), [raw_talk(TITLE), raw_talk("A Talk That Isn't There")])
    assert [t["title"] for t in kept] == [TITLE]
    assert dropped == Counter({"title_not_on_page": 1})


def test_time_must_be_on_page_and_match():
    kept, dropped = verify_listing(qcon_page(), [raw_talk(TITLE, start="11:00")])
    assert kept == []
    assert dropped == Counter({"time_not_on_page": 1})


def test_detail_url_must_be_a_page_link():
    page = Page(QCON, "", "Talk One at 9:00AM", [("Talk One", "https://qconsf.com/talk/1")])
    good = raw_talk("Talk One", "9:00AM", "09:00", detail_url="https://qconsf.com/talk/1")
    bad = raw_talk("Talk One", "9:00AM", "09:00", detail_url="https://evil.example/1")
    kept, dropped = verify_listing(page, [good, bad])
    assert [t["detail_url"] for t in kept] == ["https://qconsf.com/talk/1", None]
    assert not dropped


def test_read_listing_chunks_with_overlap_and_dedupes():
    text = " ".join(f"word{i}" for i in range(400))
    page = Page(QCON, "", text, [])
    seen = []

    def ask(system, user, schema):
        seen.append(user)
        return {"talks": [raw_talk("Same Talk")]}

    talks = read_listing(page, ask=ask, chunk_chars=1000)
    assert len(seen) > 1
    assert len(talks) == 1
    assert "word0" in seen[0] and "word399" in seen[-1]


def test_parse_time():
    assert parse_time("10:35AM PST") == "10:35"
    assert parse_time("1:35 PM") == "13:35"
    assert parse_time("12:05PM") == "12:05"
    assert parse_time("12:30 AM") == "00:30"
    assert parse_time("14:20") == "14:20"
    assert parse_time("no time") is None
