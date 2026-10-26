"""The registry graph: which conferences exist, their build status, and attendee accounts.

Conference schedules live in their own graphs; this small one only lists them. Accounts live here
too, so one code works across every conference.
"""

import json
import re
from datetime import date, timedelta
from urllib.parse import urlparse

from falkordb import Graph

from .config import settings
from .graph import connect
from .planner import EXPERIENCE_LEVELS, _now

REGISTRY = "throughline_registry"
UNIVERSE_ID = "universe26"

STATUSES = ("none", "building", "ready", "partial", "failed", "not_found")
FIELDS = ["id", "name", "dates", "start_date", "end_date", "location", "url", "schedule_url",
          "graph", "status", "step", "counts", "reason", "checked_at", "clock_start", "talks"]
SETTABLE = set(FIELDS) - {"id"}


def registry_graph(local: bool = False) -> Graph:
    return connect(REGISTRY, local=local)


def conference_id(name: str, start_date: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not re.search(r"\b\d{4}\b", name) and start_date[:4].isdigit():
        slug = f"{slug}-{start_date[:4]}"
    return slug


def _words(name: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", name.lower()) if len(w) > 3}


def _names_match(name: str, other: str) -> bool:
    """Same event if the names are the same, or share enough distinctive words (one shared word isn't enough)."""
    same = re.findall(r"[a-z0-9]+", name.lower())
    if same and same == re.findall(r"[a-z0-9]+", other.lower()):  # "AI Dev 26 x SF" has no long word to share
        return True
    words, ow = _words(name), _words(other)
    return bool(words and ow and len(words & ow) >= min(2, len(ow)))


def _domain(url: str) -> str:
    host = urlparse(url or "").hostname or ""
    return host.removeprefix("www.")


def same_conference(a: dict, b: dict) -> bool:
    """With dates on both sides: overlapping dates, and the same website (or similar names if a website is missing).
    Without dates on a side: similar names."""
    names = _names_match(a.get("name", ""), b.get("name", ""))
    if not a.get("start_date") or not b.get("start_date"):
        return names
    da, db = _domain(a.get("url", "")), _domain(b.get("url", ""))
    if not (da == db if da and db else names):
        return False
    a_end, b_end = a.get("end_date") or a["start_date"], b.get("end_date") or b["start_date"]
    return a["start_date"] <= b_end and b["start_date"] <= a_end


MONTH_NAMES = ("january", "february", "march", "april", "may", "june", "july", "august", "september",
               "october", "november", "december")
_ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_RANGE = re.compile(r"\s*(?:[-–—]|\bto\b|\bthrough\b|\buntil\b)\s*", re.I)
MAX_DAYS = 31


def _month(word: str) -> int | None:
    word = word.lower().rstrip(".")
    return next((i for i, name in enumerate(MONTH_NAMES, 1) if len(word) >= 3 and name.startswith(word)), None)


def end_date_from(dates: str, start_date: str) -> str:
    """The last day of a range like "November 16-20, 2026" or "Oct 30–Nov 2", as YYYY-MM-DD; "" if the
    text gives no range. The nearby search states only a start date, so the end is read from its words.
    Missing month or year come from the start date; an end before the start or a month after it is refused."""
    try:
        start = date.fromisoformat((start_date or "")[:10])
    except ValueError:
        return ""
    text = dates or ""
    iso = _ISO.findall(text)
    if len(iso) == 1:  # one ISO date is a single day, not a range ("2026-11-05" must not read as the 11th)
        return ""
    if len(iso) >= 2:
        candidates = [iso[-1]]
    else:
        parts = _RANGE.split(text, maxsplit=1)
        if len(parts) < 2:
            return ""
        tail = parts[1]
        day = re.search(r"(?<![\d:])(\d{1,2})(?![\d:])", tail)  # not the hour or minutes of a time
        if not day:
            return ""
        month = next((m for w in re.findall(r"[A-Za-z]+\.?", tail) if (m := _month(w))), start.month)
        year = re.search(r"\b(\d{4})\b", tail)
        years = [int(year.group(1))] if year else [start.year, start.year + 1]
        candidates = []
        for y in years:
            try:
                candidates.append(date(y, month, int(day.group(1))).isoformat())
            except ValueError:
                pass
    for candidate in candidates:
        end = date.fromisoformat(candidate)
        if start <= end <= start + timedelta(days=MAX_DAYS):
            return candidate
    return ""


# --- conferences -------------------------------------------------------------

def _entry(row: list) -> dict:
    d = dict(zip(FIELDS, row))
    d["counts"] = json.loads(d["counts"]) if d["counts"] else {}
    d["talks"] = d["talks"] or 0
    return d


_RETURN = "RETURN " + ", ".join(f"c.{f}" for f in FIELDS)


def list_conferences(reg: Graph) -> list[dict]:
    rows = reg.query(f"MATCH (c:Conference) {_RETURN} ORDER BY c.start_date").result_set
    return [_entry(r) for r in rows]


def get(reg: Graph, conf_id: str) -> dict | None:
    rows = reg.query(f"MATCH (c:Conference {{id: $id}}) {_RETURN}", {"id": conf_id}).result_set
    return _entry(rows[0]) if rows else None


def ensure_universe(reg: Graph) -> dict:
    reg.query(
        """
        MERGE (c:Conference {id: $id})
        SET c.name = $name, c.dates = $dates, c.start_date = $start, c.end_date = $end, c.location = $location,
            c.graph = 'throughline', c.status = 'ready', c.clock_start = $clock
        """,
        {"id": settings.conference_id, "name": settings.conference_name, "dates": settings.conference_dates,
         "start": settings.conference_start, "end": settings.conference_end, "location": settings.conference_location,
         "clock": settings.clock_start},
    )
    return get(reg, settings.conference_id)


def upsert_found(reg: Graph, found: dict) -> dict:
    """The existing entry when this is the same conference, else a new one (status none)."""
    existing = list_conferences(reg)
    found = {**found, "end_date": found.get("end_date") or end_date_from(found.get("dates", ""), found.get("start_date", ""))}
    match = next((c for c in existing if same_conference(c, found)), None)
    if match:
        end = end_date_from(match["dates"] or found.get("dates", ""), match["start_date"])
        if not match["end_date"] and end and match["id"] != UNIVERSE_ID:  # saved before end dates were read
            reg.query("MATCH (c:Conference {id: $id}) SET c.end_date = $end", {"id": match["id"], "end": end})
            match = get(reg, match["id"])
        return match
    base = conference_id(found["name"], found.get("start_date", ""))
    taken = {c["id"] for c in existing}
    cid, n = base, 2
    while cid in taken:
        cid, n = f"{base}-{n}", n + 1
    reg.query(
        """
        CREATE (:Conference {id: $id, name: $name, dates: $dates, start_date: $start, end_date: $end,
                             location: $location, url: $url, graph: $graph, status: 'none'})
        """,
        {"id": cid, "name": found["name"], "dates": found.get("dates", ""), "start": found.get("start_date", ""),
         "end": found.get("end_date", ""), "location": found.get("location", ""), "url": found.get("url", ""),
         "graph": ""},  # a build assigns the graph name
    )
    return get(reg, cid)


def set_status(reg: Graph, conf_id: str, **fields) -> dict:
    unknown = set(fields) - SETTABLE
    if unknown:
        raise ValueError(f"unknown conference fields: {sorted(unknown)}")
    if fields.get("status", "none") not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    if "counts" in fields:
        fields["counts"] = json.dumps(fields["counts"])
    reg.query("MATCH (c:Conference {id: $id}) SET c += $fields", {"id": conf_id, "fields": {**fields, "checked_at": _now()}})
    return get(reg, conf_id)


def mark_interrupted(reg: Graph) -> int:
    """A build can't survive a restart; anything still marked building didn't finish."""
    rows = reg.query(
        """
        MATCH (c:Conference {status: 'building'})
        SET c.status = 'failed', c.reason = 'The build was interrupted', c.checked_at = $at
        RETURN count(c)
        """,
        {"at": _now()},
    ).result_set
    return rows[0][0]


# --- accounts ----------------------------------------------------------------

def create_account(reg: Graph, code: str) -> None:
    reg.query("CREATE (:Account {code: $code, created_at: $at})", {"code": code, "at": _now()})


def account_exists(reg: Graph, code: str) -> bool:
    return reg.query("MATCH (a:Account {code: $code}) RETURN count(a)", {"code": code}).result_set[0][0] > 0


def delete_account(reg: Graph, code: str) -> None:
    reg.query("MATCH (a:Account {code: $code}) DETACH DELETE a", {"code": code})


def set_profile(reg: Graph, code: str, role: str = "", experience: str = "", interests: list[str] | None = None) -> dict:
    if experience not in EXPERIENCE_LEVELS:
        raise ValueError(f"experience must be one of {EXPERIENCE_LEVELS[1:]}")
    clean = [i.strip()[:40] for i in (interests or []) if i and i.strip()][:10]
    reg.query(
        """
        MATCH (a:Account {code: $code})
        SET a.role = $role, a.experience = $experience, a.interests = $interests, a.profile_updated_at = $at
        """,
        {"code": code, "role": (role or "").strip()[:60], "experience": experience, "interests": clean, "at": _now()},
    )
    return get_profile(reg, code)


def get_profile(reg: Graph, code: str) -> dict:
    rows = reg.query(
        "MATCH (a:Account {code: $code}) RETURN a.role, a.experience, a.interests, a.profile_updated_at", {"code": code}
    ).result_set
    if not rows or rows[0][3] is None:
        return {}
    role, experience, interests, updated_at = rows[0]
    return {"role": role or "", "experience": experience or "", "interests": interests or [], "updated_at": updated_at}
