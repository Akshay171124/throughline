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
    assert [t["detail_url"] for t in verify_listing(page, [good])[0]] == ["https://qconsf.com/talk/1"]
    assert [t["detail_url"] for t in verify_listing(page, [bad])[0]] == [None]
    kept, dropped = verify_listing(page, [bad, good])  # one talk read twice: the checked link wins
    assert [t["detail_url"] for t in kept] == ["https://qconsf.com/talk/1"]
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


def test_title_matches_whole_words_only():
    kept, dropped = verify_listing(qcon_page(), [raw_talk("ag"), raw_talk(TITLE)])
    assert [t["title"] for t in kept] == [TITLE]
    assert dropped == Counter({"title_not_on_page": 1})


def test_time_matches_whole_token():
    page = Page("u", "", "Talk A 11:35 PM", [])
    kept, dropped = verify_listing(page, [raw_talk("Talk A", "1:35 PM", "13:35")])
    assert kept == []
    assert dropped == Counter({"time_not_on_page": 1})


def test_unparseable_time_is_dropped_even_with_no_start():
    page = Page("u", "", "Talk A TBA", [])
    kept, dropped = verify_listing(page, [raw_talk("Talk A", "TBA", None)])
    assert kept == []
    assert dropped == Counter({"time_not_on_page": 1})


def test_abstract_kept_only_if_on_page():
    page = qcon_page()
    sentence = page.text[page.text.index(TITLE) + len(TITLE) + 200:][:120].strip()
    sentence = sentence[sentence.index(" ") + 1: sentence.rindex(" ")]
    kept, _ = verify_listing(page, [raw_talk(TITLE, abstract="An invented abstract nobody wrote.")])
    assert kept[0]["abstract"] == ""
    kept, _ = verify_listing(page, [raw_talk(TITLE, abstract=sentence)])
    assert kept[0]["abstract"] == sentence


def test_end_comes_from_the_verified_time_range_and_duration_must_be_on_page():
    page = Page(QCON, "", "Monday 10:35AM - 11:25AM Talk One Monday 2:00PM Talk Two (50 minutes)", [])
    raw = [raw_talk("Talk One", time_text="10:35AM - 11:25AM", end="9:30", duration_text="(99 minutes)"),
           raw_talk("Talk Two", time_text="2:00PM", start="14:00", end="11:25AM", duration_text="(50 minutes)")]
    kept, _ = verify_listing(page, raw)
    assert [(t["end"], t["duration_text"]) for t in kept] == [("11:25", None), (None, "(50 minutes)")]


SESSION_TEXT = ("Monday Nov 16 10:35AM PST Sponsored session Marina Sponsored session Pacific LM "
                "10:35AM PST Agent Evals in Practice Marina ")
S1, S2 = "https://qconsf.com/presentation/nov2026/sponsored-session", "https://qconsf.com/presentation/nov2026/sponsored-session-2"
EVALS = "https://qconsf.com/p/agent-evals"


def session_page() -> Page:
    words = " ".join(f"w{i}" for i in range(400))
    return Page(QCON, "", SESSION_TEXT + words, [("Sponsored session", S1), ("Sponsored session", S2), ("Agent Evals", EVALS)])


def test_one_talk_read_twice_with_unchecked_fields_stays_one_talk():
    # The review's probe: a talk on a chunk seam, read again with a mangled link and a reworded room.
    # Fields the page doesn't vouch for must never split a talk (it became 3, two with one code).
    page = session_page()
    a = raw_talk("Agent Evals in Practice", room="Marina", detail_url=EVALS)
    b = raw_talk("Agent Evals in Practice", room="Marina", detail_url="https://qconsf.com/p/agent-evals-in-practice")
    c = raw_talk("Agent Evals in Practice", room="Marina Ballroom", detail_url=None)
    answers = iter([{"talks": [a]}, {"talks": [b, c]}])
    raw = read_listing(page, ask=lambda *x: next(answers, {"talks": []}), chunk_chars=1000)
    kept, dropped = verify_listing(page, raw)
    assert [(t["title"], t["room"], t["detail_url"]) for t in kept] == [("Agent Evals in Practice", "Marina", EVALS)]
    assert dropped == Counter()  # the copies are the same talk, not drops


def test_same_titled_sessions_with_page_rooms_or_links_stay_apart():
    # QCon lists nine "Sponsored session" slots, two at the same time on Monday in different rooms.
    page = session_page()
    by_link = [raw_talk("Sponsored session", room=None, detail_url=S1), raw_talk("Sponsored session", room=None, detail_url=S2)]
    by_room = [raw_talk("Sponsored session", room="Marina", detail_url=None),
               raw_talk("Sponsored session", room="Pacific LM", detail_url=None)]
    for pair in (by_link, by_room):
        kept, _ = verify_listing(page, pair)
        assert len(kept) == 2
    # A copy without its link, or with a room the page doesn't name, is one of the two, not a third.
    kept, _ = verify_listing(page, by_link + [raw_talk("Sponsored session", room="Hall Z", detail_url=None)])
    assert len(kept) == 2


def test_a_talk_seen_twice_is_dropped_once():
    kept, dropped = verify_listing(session_page(), [raw_talk("Invented Talk"), raw_talk("Invented Talk", room="Marina")])
    assert kept == [] and dropped == Counter({"title_not_on_page": 1})



# --- talk dates are checked in code against the page's day headings (ruling R23) ---

STARTUP = "Transitioning From a Startup to a Mature Platform"  # a Tuesday talk early in the second chunk


def test_day_headings_are_read_from_the_page():
    from throughline.importer import day_headings
    text = ("Mon 16 Monday Nov 16 Tue 17 Tuesday Nov 17 Monday, November 16th, 2026 07:15AM PST Badge "
            "Tuesday 17 November talks Thu, Nov 19 Saturn 16 November")
    days = [(d, h) for _, d, h in day_headings(text)]
    assert days == [("2026-11-16", "Monday Nov 16"), ("2026-11-17", "Tuesday Nov 17"),
                    ("2026-11-16", "Monday, November 16th, 2026"), ("2026-11-17", "Tuesday 17 November"),
                    ("2026-11-19", "Thu, Nov 19")]
    assert day_headings("Talk One at 9:00AM, released on March 3, 2020") == []


def test_each_chunk_gets_the_day_it_starts_in():
    page, seen = qcon_page(), []

    def ask(system, user, schema):
        seen.append(user)
        return {"talks": []}

    read_listing(page, ask=ask, chunk_chars=20000)
    assert len(seen) == 2
    assert "Day context" not in seen[0]
    assert seen[1].startswith("Day context: Tuesday, November 17th, 2026")
    assert STARTUP in seen[1][:2000]


def test_a_talk_date_must_match_the_day_heading_above_it():
    page = qcon_page()
    tuesday = raw_talk(STARTUP, "02:45PM PST", "14:45", date="2026-11-17")
    kept, dropped = verify_listing(page, [tuesday])
    assert [(t["title"], t["date"]) for t in kept] == [(STARTUP, "2026-11-17")] and not dropped
    kept, dropped = verify_listing(page, [{**tuesday, "date": "2026-11-16"}])
    assert kept == [] and dropped == Counter({"date_not_on_page": 1})


def test_a_seam_talk_read_with_two_dates_is_one_talk():
    page = qcon_page()
    tuesday = raw_talk(STARTUP, "02:45PM PST", "14:45", date="2026-11-17")
    kept, dropped = verify_listing(page, [{**tuesday, "date": "2026-11-16"}, tuesday])
    assert [(t["title"], t["date"]) for t in kept] == [(STARTUP, "2026-11-17")]
    assert dropped == Counter()  # the misdated copy is the same talk, not something left out


def test_without_day_headings_dates_are_not_checked():
    page = Page(QCON, "", "Talk One at 9:00AM and Talk Two at 10:00AM", [])
    kept, dropped = verify_listing(page, [raw_talk("Talk One", "9:00AM", "09:00", date="2031-01-01")])
    assert [t["date"] for t in kept] == ["2031-01-01"] and not dropped
