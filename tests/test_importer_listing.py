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
    text = ("Mon 16 Monday Nov 16 9:00AM Talk Tuesday Nov 17 9:00AM Talk Monday, November 16th, 2026 07:15AM PST "
            "Badge Tuesday 17 November 10:00 talks Thu, Nov 19 11:00AM Saturn 16 November 12:00PM")
    days = [(d, h) for _, d, h in day_headings(text)]
    assert days == [("2026-11-16", "Monday Nov 16"), ("2026-11-17", "Tuesday Nov 17"),
                    ("2026-11-16", "Monday, November 16th, 2026"), ("2026-11-17", "Tuesday 17 November"),
                    ("2026-11-19", "Thu, Nov 19")]
    plain = "November 20, 2026 9:00AM Talk Nov 21 9:00AM Talk 22 November 2026 9:00AM Talk"
    assert [(d, h) for _, d, h in day_headings(plain)] == [
        ("2026-11-20", "November 20, 2026"), ("2026-11-21", "Nov 21"), ("2026-11-22", "22 November 2026")]
    assert day_headings("Talk One at 9:00AM, released on March 3, 2020") == []
    assert day_headings("Released on March 3, 2020. Talk One at 9:00AM") == []  # one plain date is not a schedule


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


# --- a heading counts only if a talk time follows it before the next heading: tab bars are not days ---

TABS = "Mon Nov 16 Tue Nov 17 Wed Nov 18 Filters Track Room "
FILLER = "Hallway notes and venue details. " * 40
TAB_TALKS = [("Shipping Search at Scale", "9:00AM", "09:00", "2026-11-16"),
             ("Retries Without Regret", "10:00AM", "10:00", "2026-11-16"),
             ("Feature Flags in Anger", "9:30AM", "09:30", "2026-11-17"),
             ("Paging Less, Sleeping More", "11:00AM", "11:00", "2026-11-17"),
             ("Closing Keynote: The Long Tail", "4:00PM", "16:00", "2026-11-18")]


def tab_bar_page() -> Page:
    days = {"2026-11-16": "November 16, 2026", "2026-11-17": "November 17, 2026", "2026-11-18": "November 18, 2026"}
    text, last = TABS, None
    for title, time_text, _, date in TAB_TALKS:
        if date != last:
            text += f"{FILLER}{days[date]} "
            last = date
        text += f"{title} {time_text} PST Room 1 "
    return Page(QCON, "", text, [])


def tab_talks() -> list[dict]:
    return [raw_talk(title, f"{time_text} PST", start, date=date) for title, time_text, start, date in TAB_TALKS]


def test_a_tab_bar_is_not_a_day_heading():
    from throughline.importer import day_headings
    page = tab_bar_page()
    assert [(d, h) for _, d, h in day_headings(page.text)] == [
        ("2026-11-16", "November 16, 2026"), ("2026-11-17", "November 17, 2026"), ("2026-11-18", "November 18, 2026")]
    kept, dropped = verify_listing(page, tab_talks())
    assert [(t["title"], t["date"]) for t in kept] == [(t[0], t[3]) for t in TAB_TALKS] and not dropped


def test_a_chunk_after_a_tab_bar_gets_the_body_heading():
    from throughline.importer import _spans
    page, seen = tab_bar_page(), []

    def ask(system, user, schema):
        seen.append(user)
        return {"talks": []}

    read_listing(page, ask=ask, chunk_chars=1400)
    tuesday, wednesday = page.text.index("November 17, 2026"), page.text.index("November 18, 2026")
    starts = [start for start, _ in _spans(page.text, 1400)]
    assert "Day context" not in seen[0]
    assert [u.split("\n", 1)[0] for u, start in zip(seen, starts) if tuesday < start < wednesday] == \
        ["Day context: November 17, 2026 (the last day heading before this part of the page)"]


def test_a_talk_under_the_wrong_body_heading_is_still_dropped():
    talks = tab_talks()
    talks[2] = {**talks[2], "date": "2026-11-16"}  # a Tuesday talk read as Monday
    kept, dropped = verify_listing(tab_bar_page(), talks)
    assert "Feature Flags in Anger" not in [t["title"] for t in kept] and len(kept) == 4
    assert dropped == Counter({"date_not_on_page": 1})


def test_tabs_over_numbered_days_mean_no_day_headings():
    from throughline.importer import day_headings
    text = (f"{TABS}Day 1 Shipping Search at Scale 9:00AM PST Retries Without Regret 10:00AM PST "
            f"Day 2 Feature Flags in Anger 9:30AM PST Paging Less, Sleeping More 11:00AM PST")
    page = Page(QCON, "", text, [])
    assert day_headings(page.text) == []
    kept, dropped = verify_listing(page, tab_talks()[:4])
    assert len(kept) == 4 and not dropped


def test_qcon_filter_bar_is_not_a_day_heading():
    from throughline.importer import day_headings
    assert [(d, h) for _, d, h in day_headings(qcon_page().text)] == [
        ("2026-11-16", "Monday, November 16th, 2026"), ("2026-11-17", "Tuesday, November 17th, 2026"),
        ("2026-11-18", "Wednesday, November 18th, 2026"), ("2026-11-19", "Thursday, November 19th, 2026"),
        ("2026-11-20", "Friday, November 20th, 2026")]


def test_a_plain_date_in_running_text_does_not_split_a_named_day():
    from throughline.importer import day_headings
    text = ("Monday, November 16th, 2026 9:00AM PST Talk One. Early pricing ends November 17th, register now. "
            "10:00AM PST Talk Two Tuesday, November 17th, 2026 9:00AM PST Talk Three")
    page = Page(QCON, "", text, [])
    assert [h for _, _, h in day_headings(text)] == ["Monday, November 16th, 2026", "Tuesday, November 17th, 2026"]
    kept, dropped = verify_listing(page, [raw_talk("Talk Two", "10:00AM PST", "10:00", date="2026-11-16")])
    assert len(kept) == 1 and not dropped


def test_a_plain_date_right_under_a_named_day_does_not_hide_it():
    from throughline.importer import day_headings
    text = ("Monday, November 16th, 2026 Early pricing ends Nov 10. 9:00AM PST Talk One "
            "Tuesday, November 17th, 2026 9:00AM PST Talk Two")
    assert [h for _, _, h in day_headings(text)] == ["Monday, November 16th, 2026", "Tuesday, November 17th, 2026"]


def test_a_tab_bar_over_unheaded_talks_means_no_day_headings():
    from throughline.importer import day_headings
    page = Page(QCON, "", "Mon Nov 16 Tue Nov 17 Wed Nov 18 Filters Talk A 9:00AM Talk B 10:00AM Talk C 11:00AM", [])
    assert day_headings(page.text) == []
    talks = [raw_talk("Talk A", "9:00AM", "09:00", date="2026-11-16"),
             raw_talk("Talk B", "10:00AM", "10:00", date="2026-11-17"),
             raw_talk("Talk C", "11:00AM", "11:00", date="2026-11-18")]
    kept, dropped = verify_listing(page, talks)
    assert [(t["title"], t["date"]) for t in kept] == [(t["title"], t["date"]) for t in talks] and not dropped
    seen = []
    read_listing(page, ask=lambda system, user, schema: seen.append(user) or {"talks": []})
    assert seen and not any("Day context" in u for u in seen)
