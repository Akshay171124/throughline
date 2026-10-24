"""Turn the GitHub Universe 2026 catalog feed (RainFocus) into clean talk records.

Whatever fetches the feed (Bright Data's Browser API, or the plain-request
fallback) hands its raw items to `normalize_items`, and the result is written
as the talks snapshot that the graph loader reads.

Run `python -m throughline.catalog` to rebuild the snapshot from the raw file.
"""

import calendar
import html
import json
import re
from datetime import datetime
from pathlib import Path

from .config import settings

# Sessions that aren't talks you could learn from.
EXCLUDED_TYPES = {"Social", "Special Event", "Session After Party"}
SESSION_URL = (
    "https://reg.githubuniverse.com/flow/github/universe26/attendee-portal"
    "/page/sessioncatalog/session/{session_id}"
)


def clean_text(text: str | None) -> str:
    """Strip HTML tags, decode entities and collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def to_minutes(date: str, hhmm: str) -> int:
    """Conference-local wall-clock time as minutes since the epoch (no timezone)."""
    moment = datetime.strptime(f"{date} {hhmm}", "%Y-%m-%d %H:%M")
    return calendar.timegm(moment.timetuple()) // 60


def extract_items(payload) -> list[dict]:
    """Find the list of session items anywhere inside a feed response."""
    if isinstance(payload, dict):
        if isinstance(payload.get("items"), list):
            return payload["items"]
        children = payload.values()
    elif isinstance(payload, list):
        children = payload
    else:
        return []
    for child in children:
        items = extract_items(child)
        if items:
            return items
    return []


def _attr(item: dict, name: str) -> list[str]:
    return [a["value"] for a in item.get("attributevalues") or [] if a.get("attribute") == name]


def _level_num(level: str | None) -> int | None:
    match = re.match(r"Level (\d+)", level or "")
    return int(match.group(1)) if match else None


def normalize_items(items: list[dict]) -> list[dict]:
    """Keep published talks, drop socials and duplicates, and flatten each one."""
    talks, seen = [], set()
    for item in items:
        if not item.get("published"):
            continue
        session_type = (_attr(item, "Session type") or [None])[0]
        if session_type in EXCLUDED_TYPES:
            continue
        slot = (item.get("times") or [{}])[0]
        date, start, end = slot.get("date"), slot.get("startTime"), slot.get("endTime")
        if not (date and start and end):
            continue
        title = clean_text(item.get("title"))
        key = (title.lower(), date)
        if key in seen:  # the catalog lists some sessions twice
            continue
        seen.add(key)
        level = (_attr(item, "Level") or [None])[0]
        speakers = [
            {
                "name": p.get("fullName") or f"{p.get('firstName', '')} {p.get('lastName', '')}".strip(),
                "company": p.get("companyName") or "",
                "title": p.get("jobTitle") or "",
            }
            for p in item.get("participants") or []
            if p.get("published", True) is not False
        ]
        talks.append({
            "code": item.get("code"),
            "session_id": item.get("sessionID"),
            "title": title,
            "type": session_type,
            "level": level,
            "level_num": _level_num(level),
            "topics": _attr(item, "Topic"),
            "sponsor": bool(_attr(item, "Sponsor Session?")),
            "date": date,
            "day": slot.get("dayName"),
            "start": start,
            "end": end,
            "start_min": to_minutes(date, start),
            "end_min": to_minutes(date, end),
            "room": slot.get("room") or "",
            "speakers": speakers,
            "abstract": clean_text(item.get("abstract")),
            "url": SESSION_URL.format(session_id=item.get("sessionID")),
        })
    talks.sort(key=lambda t: (t["start_min"], t["code"]))
    return talks


def write_snapshot(talks: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        for talk in talks:
            f.write(json.dumps(talk, ensure_ascii=False) + "\n")


def read_snapshot(path: Path = settings.talks_snapshot) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


if __name__ == "__main__":
    raw = json.loads(settings.raw_snapshot.read_text(encoding="utf-8"))
    talks = normalize_items(extract_items(raw))
    write_snapshot(talks, settings.talks_snapshot)
    print(f"{len(talks)} talks -> {settings.talks_snapshot}")
