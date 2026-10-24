"""The Throughline agent: an OpenAI model that can only answer through graph tools.

Every tool call is recorded in a trace (tool, arguments, the Cypher it ran and a
summary of the result) so the screen can show how each answer was reached.
`run_cypher` lets the agent query the graph directly, read-only (GraphRAG).
"""

import json
import re

from falkordb import Graph
from openai import OpenAI

from . import planner
from .config import settings

MAX_TOOL_ROUNDS = 8
MAX_ROWS = 25
# Words that say nothing about which talk someone means.
STOPWORDS = {
    "the", "and", "for", "with", "talk", "talks", "session", "workshop", "about", "what", "your", "you",
    "this", "that", "get", "ready", "from", "just", "came", "out", "one", "on", "how",
}

SCHEMA_NOTE = """Graph schema (FalkorDB, Cypher):
(:Talk {code, title, type, level, level_num, day, date, start, end, start_min, end_min, room, speakers, topics, abstract, url})
(:TimeSlot {key, date, start, end}), (:Conference {id, name}), (:Concept {id, name, aliases, definition}), (:Resource {url, title, minutes})
(:Attendee {code, clock_min})
(Talk)-[:IN_SLOT]->(TimeSlot), (Talk)-[:PART_OF]->(Conference)
(Talk)-[:REQUIRES {evidence, confidence, status}]->(Concept), (Talk)-[:TEACHES {evidence, confidence, status}]->(Concept)
(Concept)-[:DEPENDS_ON {support, via, evidence}]->(Concept), (Resource)-[:EXPLAINS]->(Concept)
(Attendee)-[:KNOWS {how, via}]->(Concept), (Attendee)-[:ATTENDED]->(Talk), (Attendee)-[:TARGETS]->(Talk)
Times: start_min/end_min are minutes, comparable with the attendee's clock_min. Day 1 is Wednesday 2026-10-28, day 2 Thursday 2026-10-29.
In patterns that look for a different talk, add WHERE a <> b."""

SYSTEM_PROMPT = f"""You are Throughline, a readiness agent for GitHub Universe 2026 (October 28-29, San Francisco).
You help one attendee get ready for talks they care about: what to learn first, in what order, and where to learn it before the talk starts.

Rules:
- Answer only from tool results. Never use your own knowledge about talks, speakers, times, rooms or concepts. If the tools don't give an answer, say you don't know.
- Start by calling get_attendee to learn the current conference time and what this attendee already knows.
- To find a talk the attendee names loosely ("the MCP security talk"), call search_talks.
- When they say they attended or just came out of a talk, call mark_attended. When they say they already know a concept, call mark_known.
- An empty learning path means they're ready: say "You're ready" and why.
- Mention talks by title, day and time, written like "Thursday 9:00 AM". Keep replies short: a few sentences or a short list.
- If search_talks returns several plausible talks and none clearly matches, ask which one they mean.
- Use run_cypher only for questions the other tools don't cover. It is read-only.

{SCHEMA_NOTE}"""


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required, "additionalProperties": False},
        },
    }


TALK = {"talk": {"type": "string", "description": "Talk code, e.g. BLD1428W"}}
TOOLS = [
    _fn("get_attendee", "The attendee's current conference time, known concepts and attended talks.", {}, []),
    _fn("search_talks", "Find talks by words in the title, abstract, speakers or topics.",
        {"query": {"type": "string"}, "day": {"type": "string", "enum": ["Wednesday", "Thursday", "any"]}}, ["query", "day"]),
    _fn("get_learning_path", "Ordered concepts this attendee still has to learn before a talk (empty = ready).", TALK, ["talk"]),
    _fn("plan_day", "Where to learn each step before the talk starts: earlier talks, or explainers. Flags clashes.", TALK, ["talk"]),
    _fn("find_where_to_learn", "Talks that teach a concept after the current time, optionally before a talk starts.",
        {"concept": {"type": "string", "description": "Concept id"}, "before_talk": {"type": "string", "description": "Talk code or empty"}},
        ["concept", "before_talk"]),
    _fn("explain_step", "The evidence behind one step: the abstract phrases and graph links that justify it.",
        {"talk": TALK["talk"], "concept": {"type": "string", "description": "Concept id"}}, ["talk", "concept"]),
    _fn("mark_attended", "Record that the attendee attended a talk; they learn what it teaches and the clock moves to its end.", TALK, ["talk"]),
    _fn("mark_known", "Record that the attendee already knows a concept.", {"concept": {"type": "string", "description": "Concept id"}}, ["concept"]),
    _fn("run_cypher", "Run a read-only Cypher query against the graph for questions other tools don't answer. Use LIMIT.",
        {"cypher": {"type": "string"}}, ["cypher"]),
]


def _trim(value, depth: int = 0):
    """Keep tool results small for the model: shorten long strings and lists."""
    if isinstance(value, str):
        return value if len(value) <= 300 else value[:300] + "…"
    if isinstance(value, list):
        return [_trim(v, depth + 1) for v in value[:MAX_ROWS]]
    if isinstance(value, dict):
        return {k: _trim(v, depth + 1) for k, v in value.items() if k != "queries"}
    return value


class Tools:
    """Tool implementations bound to one graph and one attendee. Each returns (result, cypher_used)."""

    def __init__(self, g: Graph, attendee: str):
        self.g, self.attendee = g, attendee

    def get_attendee(self):
        q = """
        MATCH (a:Attendee {code: $a})
        OPTIONAL MATCH (a)-[k:KNOWS]->(c:Concept)
        OPTIONAL MATCH (a)-[:ATTENDED]->(t:Talk)
        RETURN a.clock_min, collect(DISTINCT {concept: c.id, name: c.name, how: k.how}), collect(DISTINCT t.title)
        """
        rows = self.g.query(q, {"a": self.attendee}).result_set
        if not rows:
            return {"error": "unknown attendee"}, [q]
        clock, known, attended = rows[0]
        return {"clock": planner.format_minutes(clock), "known": [k for k in known if k["concept"]], "attended": attended}, [q]

    def search_talks(self, query: str, day: str = "any"):
        # FalkorDB narrows to talks mentioning any word; Python ranks them (titles count most, whole words only).
        q = """
        MATCH (t:Talk)
        WHERE ($day = 'any' OR t.day = $day)
          AND any(w IN $words WHERE toLower(t.title) CONTAINS w OR toLower(t.abstract) CONTAINS w
                  OR any(s IN t.speakers WHERE toLower(s) CONTAINS w))
        RETURN t.code, t.title, t.day, t.start, t.end, t.room, t.level, t.abstract, t.speakers
        """
        words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 2 and w not in STOPWORDS]
        words = words or [query.lower().strip()]
        rows = self.g.query(q, {"words": words, "day": day}).result_set

        def score(row) -> int:
            title, abstract, speakers = row[1].lower(), (row[7] or "").lower(), " ".join(row[8] or []).lower()
            hit = lambda text, w: re.search(rf"\b{re.escape(w)}\b", text) is not None
            return sum(3 * hit(title, w) + hit(abstract, w) + 2 * hit(speakers, w) for w in words)

        keys = ["code", "title", "day", "start", "end", "room", "level"]
        best = sorted(rows, key=score, reverse=True)[:6]
        return [dict(zip(keys, r[:7])) for r in best], [q]

    def get_learning_path(self, talk: str):
        path = planner.learning_path(self.g, talk, self.attendee)
        return path, path["queries"]

    def plan_day(self, talk: str):
        plan = planner.plan_day(self.g, talk, self.attendee)
        return plan, plan["queries"]

    def find_where_to_learn(self, concept: str, before_talk: str = ""):
        clock = planner.attendee_clock(self.g, self.attendee) or 0
        before = 10**9
        if before_talk:
            rows = self.g.query("MATCH (t:Talk {code: $t}) RETURN t.start_min", {"t": before_talk}).result_set
            before = rows[0][0] if rows else before
        rows = self.g.query(planner.TEACHERS, {"concept": concept, "after": clock, "before": before, "target": before_talk}).result_set
        keys = ["code", "title", "day", "start", "end", "start_min", "end_min", "room", "evidence"]
        return [dict(zip(keys, r)) for r in rows], [planner.TEACHERS]

    def explain_step(self, talk: str, concept: str):
        q = """
        MATCH (t:Talk {code: $talk})
        OPTIONAL MATCH (t)-[r:REQUIRES]->(c:Concept {id: $concept})
        OPTIONAL MATCH p = (:Concept)-[:DEPENDS_ON]->(:Concept {id: $concept})
        OPTIONAL MATCH (teacher:Talk)-[e:TEACHES]->(:Concept {id: $concept})
        RETURN t.title, r.evidence, r.status, r.checked_at, t.url,
               collect(DISTINCT [n IN nodes(p) | n.name]), collect(DISTINCT relationships(p)[0].evidence),
               collect(DISTINCT {talk: teacher.title, evidence: e.evidence, url: teacher.url})
        """
        rows = self.g.query(q, {"talk": talk, "concept": concept}).result_set
        if not rows:
            return {"error": "unknown talk"}, [q]
        title, evidence, status, checked_at, url, dep_paths, dep_evidence, teachers = rows[0]
        return {
            "talk": title, "requires_evidence": evidence, "status": status, "checked_at": checked_at, "source": url,
            "dependency_paths": [p for p in dep_paths if p], "dependency_evidence": [e for e in dep_evidence if e],
            "taught_by": [t for t in teachers if t["talk"]],
        }, [q]

    def mark_attended(self, talk: str):
        learned = planner.mark_attended(self.g, self.attendee, talk)
        return {"learned": learned, "clock": planner.format_minutes(planner.attendee_clock(self.g, self.attendee))}, []

    def mark_known(self, concept: str):
        planner.mark_known(self.g, self.attendee, concept)
        return {"ok": True, "known": concept}, []

    def run_cypher(self, cypher: str):
        result = self.g.ro_query(cypher, timeout=5000)
        rows = [[_plain(v) for v in row] for row in result.result_set[:MAX_ROWS]]
        return {"columns": [h[1] if isinstance(h, (list, tuple)) else h for h in result.header], "rows": rows}, [cypher]


def _plain(value):
    """Turn FalkorDB nodes, edges and paths into JSON-friendly values."""
    if hasattr(value, "properties") and hasattr(value, "labels"):
        return {"labels": value.labels, **{k: v for k, v in value.properties.items() if k != "abstract"}}
    if hasattr(value, "properties") and hasattr(value, "relation"):
        return {"type": value.relation, **value.properties}
    if hasattr(value, "nodes") and callable(value.nodes):
        return {"path": [_plain(n) for n in value.nodes()]}
    return value


def run_agent(g: Graph, attendee: str, message: str, history: list[dict] | None = None) -> dict:
    """One agent turn. History is earlier user/assistant text only; tool calls live in this turn's trace."""
    tools, trace = Tools(g, attendee), []
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *(history or [])[-10:], {"role": "user", "content": message}]
    client = OpenAI(timeout=60)
    for _ in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(model=settings.agent_model, messages=messages, tools=TOOLS)
        reply = response.choices[0].message
        if not reply.tool_calls:
            return {"reply": reply.content, "trace": trace}
        messages.append(reply.model_dump(exclude_none=True))
        for call in reply.tool_calls:
            args = json.loads(call.function.arguments or "{}")
            try:
                result, cypher = getattr(tools, call.function.name)(**args)
            except Exception as e:  # report tool errors to the model instead of crashing the turn
                result, cypher = {"error": f"{type(e).__name__}: {e}"}, []
            trace.append({"tool": call.function.name, "args": args, "cypher": [c.strip() for c in cypher], "result": _trim(result)})
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(_trim(result), default=str)})
    return {"reply": "I couldn't finish that within my tool budget. Try asking more narrowly.", "trace": trace}
