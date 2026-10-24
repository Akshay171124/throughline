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
    "a", "an", "at", "in", "of", "to", "is", "it", "my", "me", "we", "do", "by", "or", "as", "be", "i",
    "are", "was", "who", "where", "when", "which", "want", "need", "see", "go", "going", "find", "show",
    "tell", "can", "there", "its", "our", "their", "they", "them", "all", "any", "not", "but", "into",
    "workshops", "sessions", "thing", "something", "called", "named", "some", "us",
}

SCHEMA_NOTE = """Graph schema for run_cypher (FalkorDB, Cypher). It holds conference knowledge only, no attendee data:
(:Talk {code, title, type, level, level_num, day, date, start, end, start_min, end_min, room, speakers, topics, abstract, url})
(:TimeSlot {key, date, start, end}), (:Conference {id, name}), (:Concept {id, name, aliases, definition}), (:Resource {url, title, minutes})
(Talk)-[:IN_SLOT]->(TimeSlot), (Talk)-[:PART_OF]->(Conference)
(Talk)-[:REQUIRES {evidence, confidence, status}]->(Concept), (Talk)-[:TEACHES {evidence, confidence, status}]->(Concept)
(Concept)-[:DEPENDS_ON {support, via, evidence}]->(Concept), (Resource)-[:EXPLAINS]->(Concept)
Times: start_min/end_min are minutes. Day 1 is Wednesday 2026-10-28, day 2 Thursday 2026-10-29.
In patterns that look for a different talk, add WHERE a <> b.
The attendee's own memory is only available through get_attendee."""

# Attendee memory never goes through free-form Cypher (it also runs on a copy without attendees).
PRIVATE_TERMS = re.compile(r"\b(attendee|knows|attended|targets|clock_min)\b", re.IGNORECASE)

SYSTEM_PROMPT = f"""You are Throughline, a readiness agent for GitHub Universe 2026 (October 28-29, San Francisco).
You help one attendee get ready for talks they care about: what to learn first, in what order, and where to learn it before the talk starts.

Rules:
- Answer only from tool results. Never use your own knowledge about talks, speakers, times, rooms or concepts. If the tools don't give an answer, say you don't know.
- Start by calling get_attendee to learn the current conference time, what this attendee already knows, their profile (role, experience, interests) and their saved talks.
- Tailor answers to the profile: for someone new, explain concepts in plain words; for an experienced attendee, be brief. Use their interests and saved talks when they ask what to do next.
- When they say they want to go to a talk or ask you to save it, call save_talk.
- To find a talk the attendee names loosely ("the MCP security talk"), call search_talks.
- To get someone ready for a talk or plan their way there, call plan_day: it returns the ordered steps and where to learn each one. Use get_learning_path only when they just ask what they need to know.
- When they say they attended or just came out of a talk, call mark_attended. When they say they already know a concept, call mark_known.
- An empty learning path means they're ready: say "You're ready" and why.
- Mention talks by title, day and time, written like "Thursday 9:00 AM". Keep replies short: a few sentences or a short list.
- If search_talks returns several plausible talks and none clearly matches, ask which one they mean.
- Use run_cypher only for questions the other tools don't cover. It is read-only.
- Other attendees' codes and memory are private and not in your tools. If asked for them, say so plainly. Never call talk codes attendee codes.

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
    _fn("save_talk", "Save a talk to the attendee's list of talks they're aiming for.", TALK, ["talk"]),
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

    def __init__(self, g: Graph, attendee: str, public: Graph | None = None):
        # `public` is the attendee-free copy used by run_cypher (see graph.publish_public_view).
        self.g, self.attendee, self.public = g, attendee, public
        self.last_view = None  # the latest full path or plan, for the page to draw

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
        attended_talks = [
            {"code": c, "title": t} for c, t in self.g.query(
                "MATCH (:Attendee {code: $a})-[:ATTENDED]->(t:Talk) RETURN t.code, t.title ORDER BY t.start_min",
                {"a": self.attendee},
            ).result_set
        ]
        return {
            "clock": planner.format_minutes(clock),
            "known": [k for k in known if k["concept"]],
            "attended": attended,
            "attended_talks": attended_talks,
            "profile": planner.get_profile(self.g, self.attendee),
            "targets": planner.targets(self.g, self.attendee),
        }, [q]

    def save_talk(self, talk: str):
        return {"saved": talk, "targets": planner.add_target(self.g, self.attendee, talk)}, []

    def search_talks(self, query: str, day: str = "any"):
        """FalkorDB narrows to talks mentioning any query word stem (or with that exact code);
        Python ranks them with a few plain rules:
          exact talk code  +100
          word in title +3, in speakers/companies +3, in abstract +1 (per query word)
          two query words side by side in the title (either order)  +4
          title starts with a query word  +2
          "workshop"/"keynote"/"panel" in the query and the talk is that type  +2
        Words match on a light stem (security ~ securing ~ secure, agents ~ agent), or when
        one stem starts with the other (5+ letters: custom ~ customization)."""
        q = """
        MATCH (t:Talk)
        WHERE ($day = 'any' OR t.day = $day)
          AND any(w IN $words WHERE toLower(t.code) = w OR toLower(t.title) CONTAINS w
                  OR toLower(t.abstract) CONTAINS w OR any(s IN t.speakers WHERE toLower(s) CONTAINS w))
        RETURN t.code, t.title, t.day, t.start, t.end, t.room, t.level, t.abstract, t.speakers, t.type
        """
        suffixes = ("ations", "ation", "ities", "ity", "ings", "ing", "ies", "ied", "ers", "er",
                    "ed", "es", "ate", "ic", "al", "ly", "e", "y", "s")

        def tokens(text: str) -> list[str]:
            text = re.sub(r"['’]s\b", "", (text or "").lower()).replace("'", "").replace("’", "")
            return re.findall(r"[a-z0-9]+", text)

        def stem(w: str) -> str:
            if any(ch.isdigit() for ch in w):  # codes, "2am", "x86": keep as written
                return w
            for _ in range(2):  # two passes: securely -> secure -> secur
                for suf in suffixes:
                    if w.endswith(suf) and len(w) - len(suf) >= 3:
                        w = w[: -len(suf)]
                        break
            return w

        def same(a: str, b: str) -> bool:
            if a == b:
                return True
            short, long_ = sorted((a, b), key=len)
            return len(short) >= 5 and long_.startswith(short)

        raw = tokens(query)
        terms = [stem(w) for w in raw if w not in STOPWORDS]
        terms = list(dict.fromkeys(terms))  # dedupe, keep order
        words = terms or [query.lower().strip()]
        wanted_type = next((t for t in ("workshop", "keynote", "panel") if any(w.startswith(t) for w in raw)), None)
        rows = self.g.query(q, {"words": words, "day": day}).result_set

        def score(row) -> float:
            code, title, abstract, speakers, kind = row[0], row[1], row[7], row[8] or [], row[9] or ""
            title_seq = [stem(w) for w in tokens(title) if w not in STOPWORDS]
            abstract_set = {stem(w) for w in tokens(abstract)}
            speaker_set = {stem(w) for w in tokens(" ".join(speakers))}
            hit = lambda pool, t: any(same(t, w) for w in pool)
            s = 100.0 * any(t == code.lower() for t in terms)
            s += sum(3 * hit(title_seq, t) + 3 * hit(speaker_set, t) + hit(abstract_set, t) for t in terms)
            pairs = {frozenset(p) for p in zip(terms, terms[1:])}
            s += 4 * sum(any(same(a, x) and same(b, y) or same(a, y) and same(b, x) for x, y in zip(title_seq, title_seq[1:]))
                         for a, b in (tuple(p) for p in pairs if len(p) == 2))
            s += 2 * bool(title_seq and any(same(title_seq[0], t) for t in terms))
            s += 2 * bool(wanted_type and wanted_type in kind.lower())
            return s

        keys = ["code", "title", "day", "start", "end", "room", "level"]
        best = sorted(rows, key=score, reverse=True)[:6]
        return [dict(zip(keys, r[:7])) for r in best], [q]

    def get_learning_path(self, talk: str):
        path = planner.learning_path(self.g, talk, self.attendee)
        self.last_view = {"kind": "path", **path}
        return path, path["queries"]

    def plan_day(self, talk: str):
        plan = planner.plan_day(self.g, talk, self.attendee)
        self.last_view = {"kind": "plan", **plan}
        return plan, plan["queries"]

    def find_where_to_learn(self, concept: str, before_talk: str = ""):
        clock = planner.attendee_clock(self.g, self.attendee) or 0
        before = 10**9
        if before_talk:
            rows = self.g.query("MATCH (t:Talk {code: $t}) RETURN t.start_min", {"t": before_talk}).result_set
            before = rows[0][0] if rows else before
        rows = self.g.query(planner.TEACHERS, {"concept": concept, "after": clock, "before": before, "target": before_talk}).result_set
        return [dict(zip(planner.TEACHER_KEYS, r)) for r in rows], [planner.TEACHERS]

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
        if PRIVATE_TERMS.search(cypher):
            return {"error": "Attendee data isn't available to free-form queries. Use get_attendee."}, [cypher]
        if self.public is None:
            return {"error": "The public view isn't built yet. Run: uv run python -m throughline.graph"}, [cypher]
        result = self.public.ro_query(cypher, timeout=5000)
        rows = [[_plain(v) for v in row] for row in result.result_set[:MAX_ROWS]]
        return {"columns": [h[1] if isinstance(h, (list, tuple)) else h for h in result.header], "rows": rows}, [cypher]


def _plain(value):
    """Turn FalkorDB nodes, edges and paths into JSON-friendly values, never exposing attendees."""
    if hasattr(value, "properties") and hasattr(value, "labels"):
        if "Attendee" in (value.labels or []):
            return None
        return {"labels": value.labels, **{k: v for k, v in value.properties.items() if k != "abstract"}}
    if hasattr(value, "properties") and hasattr(value, "relation"):
        if PRIVATE_TERMS.search(value.relation or ""):
            return None
        return {"type": value.relation, **value.properties}
    if hasattr(value, "nodes") and callable(value.nodes):
        return {"path": [n for n in (_plain(n) for n in value.nodes()) if n is not None]}
    return value


def run_agent(g: Graph, attendee: str, message: str, history: list[dict] | None = None,
              public: Graph | None = None) -> dict:
    """One agent turn. History is earlier user/assistant text only; tool calls live in this turn's trace."""
    tools, trace = Tools(g, attendee, public), []
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *(history or [])[-10:], {"role": "user", "content": message}]
    client = OpenAI(timeout=60)
    for _ in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(model=settings.agent_model, messages=messages, tools=TOOLS)
        reply = response.choices[0].message
        if not reply.tool_calls:
            return {"reply": reply.content, "trace": trace, "view": tools.last_view}
        messages.append(reply.model_dump(exclude_none=True))
        for call in reply.tool_calls:
            args = json.loads(call.function.arguments or "{}")
            try:
                result, cypher = getattr(tools, call.function.name)(**args)
            except Exception as e:  # report tool errors to the model instead of crashing the turn
                result, cypher = {"error": f"{type(e).__name__}: {e}"}, []
            trace.append({"tool": call.function.name, "args": args, "cypher": [c.strip() for c in cypher], "result": _trim(result)})
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(_trim(result), default=str)})
    return {"reply": "I couldn't finish that within my tool budget. Try asking more narrowly.", "trace": trace,
            "view": tools.last_view}
