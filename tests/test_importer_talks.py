"""Talk pages, end times, levels and the right-event check; nothing is kept that the page does not say."""

from collections import Counter
from pathlib import Path

from throughline.importer import (Page, check_event, duration_minutes, enrich, finish_times, level_num,
                                  parse_page, talk_code, to_talks)

SITES = Path(__file__).parent / "fixtures" / "sites"
TALK_URL = "https://qconsf.com/presentations/nov2026/apis-cant-afford-be-wrong"
TITLE = "APIs That Can't Afford to Be Wrong: Lessons from Moving Money"
ON_PAGE = "Card networks give you three seconds to auth or decline."


def talk_page() -> Page:
    return parse_page(TALK_URL, (SITES / "qcon_talk.html").read_text())


def raw_talk(**extra):
    return {"title": TITLE, "date": "2026-11-16", "time_text": "10:35AM PST", "start": "10:35", "end": None,
            "duration_text": None, "room": "Pacific DEKJ", "track": "APIs", "type": "talk", "level": None,
            "speakers": [{"name": "Fawziyah Alebiosu", "company": "Imprint"}], "abstract": "Short teaser.",
            "detail_url": TALK_URL, "sponsored": False, **extra}


def test_duration_gives_end_time():
    talks = [raw_talk(duration_text="(50 minutes)")]
    assert finish_times(talks) == Counter()
    assert talks[0]["end"] == "11:25"


def test_duration_formats():
    assert duration_minutes("(50 minutes)") == 50
    assert duration_minutes("1 hour 15 minutes") == 75
    assert duration_minutes("90 min") == 90
    assert duration_minutes("soon") is None


def test_talk_without_end_or_duration_is_dropped():
    talks = [raw_talk()]
    assert finish_times(talks) == Counter({"no_time": 1})
    assert talks == []


def test_duration_past_midnight_is_dropped():
    talks = [raw_talk(start="23:30", duration_text="60 minutes")]
    assert finish_times(talks) == Counter({"no_time": 1})


def test_detail_page_abstract_replaces_teaser():
    talk = raw_talk()
    answer = {"abstract": ON_PAGE, "time_text": "10:35AM PST", "duration_text": "(50 minutes)"}
    assert enrich([talk], fetch=lambda url: talk_page(), ask=lambda *a: answer) == Counter()
    assert talk["abstract"] == ON_PAGE
    assert talk["duration_text"] == "(50 minutes)"
    assert talk["end"] == "11:25"


def test_abstract_not_on_page_keeps_teaser():
    talk = raw_talk()
    answer = {"abstract": "A lovely invented paragraph about nothing.", "time_text": None,
              "duration_text": "(75 minutes)"}
    enrich([talk], fetch=lambda url: talk_page(), ask=lambda *a: answer)
    assert talk["abstract"] == "Short teaser."
    assert talk["duration_text"] is None  # "75 minutes" is not on the page either
    assert talk["end"] is None


def test_failed_fetch_is_counted():
    def boom(url):
        raise RuntimeError("down")

    talks = [raw_talk(), raw_talk(detail_url=None, title="Other")]
    assert enrich(talks, fetch=boom, ask=lambda *a: {}) == Counter({"detail_failed": 1})
    assert talks[0]["abstract"] == "Short teaser."


def test_placeholder_abstract_becomes_empty():
    out = to_talks("c1", [raw_talk(abstract="Details coming soon", end="11:25")])
    assert out[0]["abstract"] == ""


def test_level_mapping():
    assert level_num("Advanced Topic") == 300
    assert level_num("Beginner") == 100
    assert level_num("Level 200: Intermediate") == 200
    assert level_num("Level 300") == 300
    assert level_num(None) is None


def test_talk_code_is_stable():
    code = talk_code("c1", TITLE)
    assert code == talk_code("c1", TITLE)
    assert len(code) == 8
    assert code != talk_code("c1", "Another talk")


def test_wrong_year_schedule_is_rejected():
    talks = [raw_talk(date="2025-11-20") for _ in range(10)]
    assert check_event(talks, "2026-11-10", "2026-11-12") == (
        [], "The schedule we found is for a different event (dates Nov 20, 2025)")


def test_wrong_event_in_the_same_month_names_its_days():
    # QCon's schedule pasted for AI Engineer (Nov 10-12): "dates Nov 2026" would read like the same event.
    talks = [raw_talk(date=d) for d in ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-20"] * 3]
    assert check_event(talks, "2026-11-10", "2026-11-12") == (
        [], "The schedule we found is for a different event (dates Nov 16–20, 2026)")


def test_right_event_keeps_talks_within_a_day():
    talks = [raw_talk(date=d) for d in ["2026-11-09", "2026-11-11", "2026-11-12", "2026-11-13"] * 3]
    kept, reason = check_event(talks, "2026-11-10", "2026-11-12")
    assert reason is None and len(kept) == 12
    assert check_event(talks, None, None) == (talks, None)


def test_to_talks_matches_catalog_shape():
    out = to_talks("c1", [raw_talk(end="11:25", level="Advanced Topic")], page_url="https://x.example/s")
    t = out[0]
    assert t["code"] == talk_code("c1", TITLE) and t["session_id"] is None
    assert (t["day"], t["start_min"], t["end_min"] - t["start_min"]) == ("Monday", t["start_min"], 50)
    assert t["level_num"] == 300 and t["topics"] == ["APIs"] and t["url"] == TALK_URL
    assert t["speakers"] == [{"name": "Fawziyah Alebiosu", "company": "Imprint", "title": ""}]


def test_malformed_times_are_dropped_not_raised():
    talks = [raw_talk(date="Nov 16", end="11:25"), raw_talk(end="9:30"), raw_talk(end="11:25AM"),
             raw_talk(end="10:00"), raw_talk(end="11:25")]
    assert finish_times(talks) == Counter({"no_time": 4})
    assert len(talks) == 1


def test_repeated_title_gets_one_code_per_showing():
    a, b = raw_talk(date="2026-11-16", end="11:25"), raw_talk(date="2026-11-17", end="11:25")
    codes = [t["code"] for t in to_talks("c1", [a, b])]
    assert len(set(codes)) == 2
    unique = to_talks("c1", [a, raw_talk(title="Other", end="11:25")])
    assert unique[0]["code"] == talk_code("c1", unique[0]["title"])


def test_placeholders_ignore_trailing_punctuation():
    for text in ("Details coming soon.", "TBA!"):
        assert to_talks("c1", [raw_talk(abstract=text, end="11:25")])[0]["abstract"] == ""


def test_check_event_with_only_a_start_date():
    kept, reason = check_event([raw_talk(date="2026-11-16")], "2026-11-16", None)
    assert len(kept) == 1 and reason is None
    assert check_event([raw_talk(date="2025-11-16")], "2026-11-16", None)[1] is not None


def test_detail_range_replaces_listing_end_and_duration_needs_page():
    talk = raw_talk(end="11:00")
    page = Page(TALK_URL, "", "Monday 10:35AM - 11:25AM (50 minutes)", [])
    enrich([talk], fetch=lambda u: page,
           ask=lambda *a: {"abstract": None, "time_text": "10:35AM - 11:25AM", "duration_text": None})
    assert talk["end"] == "11:25"


def test_same_title_at_the_same_time_gets_one_code_per_room():
    a = raw_talk(title="Sponsored session", end="11:25", room="Marina")
    b = raw_talk(title="Sponsored session", end="11:25", room="Pacific LM")
    codes = [t["code"] for t in to_talks("c1", [a, b])]
    assert len(set(codes)) == 2
    assert codes == [t["code"] for t in to_talks("c1", [dict(a), dict(b)])]  # stable


def test_entries_that_still_share_a_code_are_kept_once():
    # Same title, date, start and room: one Talk node. Kept counts distinct talks; the rest are "duplicate".
    counts = Counter()
    out = to_talks("c1", [raw_talk(end="11:25"), raw_talk(end="11:25", abstract="Longer teaser.")], counts=counts)
    assert len(out) == 1 and counts == Counter({"duplicate": 1})


def test_check_event_with_only_a_start_date_uses_the_talks_last_day():
    # A three-day conference whose search result gave only its first day is not a different event.
    talks = [raw_talk(date=d) for d in ["2026-11-16", "2026-11-17", "2026-11-18"] * 3]
    kept, reason = check_event(talks, "2026-11-16", None)
    assert reason is None and len(kept) == 9
    assert check_event([raw_talk(date="2026-11-14")], "2026-11-16", None)[1] is not None  # before it starts
    assert check_event([raw_talk(date="2026-12-30")], "2026-11-16", None)[1] is not None  # past start + 31 days
