import json

import pytest

from throughline.catalog import clean_text, extract_items, normalize_items, to_minutes
from throughline.config import ROOT, settings


@pytest.fixture(scope="module")
def talks():
    raw = json.loads(settings.raw_snapshot.read_text(encoding="utf-8"))
    return normalize_items(extract_items(raw))


def test_keeps_the_125_talks_from_the_friday_checks(talks):
    assert len(talks) == 125


def test_every_baseline_talk_is_present(talks):
    baseline = json.loads((ROOT / "checks" / "prerequisite-baseline.json").read_text())
    codes = {t["code"] for t in talks}
    expected = set()
    for entry in baseline["talks"]:
        expected |= {entry["code"], *entry["expected_teachers"], *entry["later_alternatives"]}
    assert expected <= codes, expected - codes


def test_no_socials_or_duplicates(talks):
    assert not {t["type"] for t in talks} & {"Social", "Special Event", "Session After Party"}
    keys = [(t["title"].lower(), t["date"]) for t in talks]
    assert len(keys) == len(set(keys))


def test_times_rooms_and_abstracts_are_usable(talks):
    for t in talks:
        assert t["start_min"] < t["end_min"], t["code"]
        assert t["room"], t["code"]
        assert t["abstract"] and "<p>" not in t["abstract"], t["code"]


def test_known_talk_is_parsed_correctly(talks):
    talk = next(t for t in talks if t["code"] == "BLD1428W")
    assert talk["title"].startswith("Own your Copilot")
    assert (talk["date"], talk["start"], talk["end"]) == ("2026-10-29", "11:30", "13:00")
    assert talk["level_num"] == 300
    assert "No beginner basics" in talk["abstract"]


def test_clean_text_and_minutes():
    assert clean_text("<p>It&#39;s  <b>here</b></p>") == "It's here"
    assert to_minutes("2026-10-28", "09:30") - to_minutes("2026-10-28", "08:30") == 60
