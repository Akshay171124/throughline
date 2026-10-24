"""Compare the graph's day plans with the 15-talk baseline hand-checked the evening before.

Each expected teacher is matched, missed or new. "New" teachers aren't automatically
wrong (the hand check missed one too), so they're listed for a person to check.

  uv run python -m throughline.evaluate
"""

import json

from .config import ROOT
from .graph import connect
from .planner import learning_path, plan_day

BASELINE = ROOT / "checks" / "prerequisite-baseline.json"


def evaluate(g) -> dict:
    rows = []
    for entry in json.loads(BASELINE.read_text())["talks"]:
        path = learning_path(g, entry["code"])
        plan = plan_day(g, entry["code"])
        planned = {s["learn_at"]["code"] for s in plan["plan"] if s["learn_at"]["kind"] == "talk"}
        # Any talk that teaches a step before the target starts counts, not only the one the greedy plan picked.
        teaching = {
            r[0]
            for step in path["steps"]
            for r in g.query(
                "MATCH (:Concept {id: $c})<-[:TEACHES]-(t:Talk), (target:Talk {code: $target}) "
                "WHERE t.end_min <= target.start_min AND t.code <> $target RETURN t.code",
                {"c": step["concept"], "target": entry["code"]},
            ).result_set
        }
        expected = set(entry["expected_teachers"])
        rows.append({
            "code": entry["code"], "title": entry["title"], "rating": entry["rating"],
            "steps": [s["name"] for s in path["steps"]], "planned": sorted(planned),
            "matched": sorted(expected & teaching), "missed": sorted(expected - teaching),
            "new": sorted(teaching - expected), "ready": path["ready"],
        })
    with_teachers = [r for r in rows if r["rating"] in ("strong", "usable", "partial")]
    found = sum(1 for r in with_teachers if r["matched"])
    none_needed = [r for r in rows if r["rating"] == "none_needed"]
    return {
        "rows": rows,
        "summary": {
            "talks_with_expected_teachers": len(with_teachers),
            "found_at_least_one_expected_teacher": found,
            "expected_teachers_matched": sum(len(r["matched"]) for r in rows),
            "expected_teachers_total": sum(len(r["matched"]) + len(r["missed"]) for r in rows),
            "none_needed_correctly_ready": sum(1 for r in none_needed if r["ready"]),
            "none_needed_total": len(none_needed),
        },
    }


if __name__ == "__main__":
    result = evaluate(connect())
    for r in result["rows"]:
        mark = "✓" if r["matched"] or (r["rating"] == "none_needed" and r["ready"]) else "·"
        print(f"{mark} {r['code']} [{r['rating']}] {r['title'][:55]}")
        print(f"    path: {r['steps'] or 'You are ready'}")
        print(f"    matched {r['matched']} missed {r['missed']} new {r['new'][:6]}")
    print(json.dumps(result["summary"], indent=2))
