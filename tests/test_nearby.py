"""Nearby-conference helpers that don't need the network."""

from datetime import date

from throughline import nearby

TODAY, END = date(2026, 10, 24), date(2026, 12, 23)
LOADED = [{"id": "universe26", "name": "GitHub Universe 2026", "dates": "Oct 28–29, 2026",
           "start_date": "2026-10-28", "location": "San Francisco, CA", "talks": 125}]


def test_date_window_drops_past_and_far_future_events():
    assert not nearby._in_window("2026-06-24", TODAY, END)  # past (the model let this through once)
    assert nearby._in_window("2026-11-10", TODAY, END)
    assert nearby._in_window("2026-10-22", TODAY, END)  # already under way
    assert not nearby._in_window("2027-03-01", TODAY, END)
    assert nearby._in_window("", TODAY, END)  # unknown dates are kept and shown as unknown


def test_loaded_conference_matching_is_by_distinctive_words():
    assert nearby._loaded(LOADED, "GitHub Universe 2026: the developer event")["id"] == "universe26"
    assert nearby._loaded(LOADED, "QCon San Francisco 2026") is None
    assert nearby._loaded(LOADED, "Universe") is None  # one shared word isn't enough


def test_cached_results_are_merged_and_loaded_ones_listed_first(monkeypatch, tmp_path):
    monkeypatch.setattr(nearby, "CACHE_FILE", tmp_path / "nearby.json")
    runs = iter([
        [{"name": "QCon San Francisco 2026", "dates": "Nov 16-18", "start_date": "2026-11-16",
          "location": "San Francisco, CA", "url": "https://qcon", "snippet": ""}],
        [{"name": "AI Engineer Conference", "dates": "Nov 10-12", "start_date": "2026-11-10",
          "location": "San Francisco, CA", "url": "https://aie", "snippet": ""}],
    ])
    monkeypatch.setattr(nearby, "_search", lambda place, today: ["results"])
    monkeypatch.setattr(nearby, "_extract", lambda place, today, results: next(runs))
    first = nearby.nearby(LOADED, place="San Francisco, CA")
    cache = nearby._read_cache()
    cache["san francisco, ca"]["ts"] = 0  # expire, so the next call searches again
    nearby._write_cache(cache)
    second = nearby.nearby(LOADED, place="San Francisco, CA")
    names = [c["name"] for c in second["conferences"]]
    assert names[0] == "GitHub Universe 2026" and second["conferences"][0]["loaded"]
    assert {"QCon San Francisco 2026", "AI Engineer Conference"} <= set(names)  # thin second run didn't wipe the first
    assert [c["name"] for c in first["conferences"]][:2] == ["GitHub Universe 2026", "QCon San Francisco 2026"]


def test_no_place_is_a_clear_error():
    assert nearby.nearby(LOADED)["error"]
