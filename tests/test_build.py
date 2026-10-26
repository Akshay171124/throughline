"""The build job: schedule page to conference graph, with partial, not-found and safe retries.

Everything runs offline: pages come from tests/fixtures/sites, the model is a stub that routes by
its system prompt, and every graph is a local, test-prefixed one that is deleted afterwards.
"""

import re
import threading
from pathlib import Path

import pytest
from falkordb import FalkorDB

from throughline import build, planner, registry
from throughline.config import settings
from throughline.graph import connect
from throughline.importer import Page, parse_page

SITES = Path(__file__).parent / "fixtures" / "sites"
HOME = "https://qconsf.com/"
SCHEDULE = "https://qconsf.com/schedule/nov2026"
DETAIL = "https://qconsf.com/presentation/nov2026/"
AIE = "https://www.ai.engineer/code"
PREFIX = "test_"
QCON = {"name": "QCon San Francisco 2026", "url": HOME, "location": "San Francisco, CA",
        "dates": "Nov 16–20, 2026", "start_date": "2026-11-16", "end_date": "2026-11-20"}

# Talks on the fixture's Monday, each with its listing teaser exactly as the page has it.
TALKS = [
    ("Live Resharding Without Regret: Lessons from Building Valkey's Atomic Slot Migration", "10:35AM PST",
     "live-resharding-without-regret-lessons-building-valkeys-atomic-slot-migration",
     "Sharding is easy. Resharding under heavy load is notoriously difficult."),
    ("APIs That Can't Afford to Be Wrong: Lessons from Moving Money", "10:35AM PST",
     "apis-cant-afford-be-wrong-lessons-moving-money",
     "Most API design advice assumes a forgiving environment: retries are cheap, data has a single source of truth, "
     "and a slow response is only an inconvenience."),
    ("The Freeze Paradox: Why Stopping Deployments Doesn't Stop Failures", "10:35AM PST",
     "freeze-paradox-why-stopping-deployments-doesnt-stop-failures",
     "When systems fail at Netflix and in an environment this complex, they sometimes will, the instinctive "
     "response is to freeze deployments."),
    ("Model-Harness Co-Training: Data-Driven Optimization Toward Pareto-Optimal Agents", "10:35AM PST",
     "model-harness-co-training-data-driven-optimization-toward-pareto-optimal",
     "Teams with agents in production are chasing the optimal agent."),
    ("Architecting Nubank's Global Financial Infrastructure", "11:45AM PST",
     "architecting-nubanks-global-financial-infrastructure",
     "Instant payment frameworks are transforming global finance, but few institutions have faced the "
     "infrastructure scale required by Brazil's Pix network."),
    ("How Airbnb Guardrailed Its AI Customer Support Agent", "11:45AM PST",
     "how-airbnb-guardrailed-its-ai-customer-support-agent",
     "When Airbnb launched its AI customer support assistant, the feature made the news"),
    ("Everything I Knew About Developer Experience Is Wrong for Agents", "11:45AM PST",
     "everything-i-knew-about-developer-experience-wrong-agents",
     "Most of what we know about developer experience we learned from humans."),
]
OAUTH = {"id": "oauth2", "name": "OAuth 2.0", "aliases": [], "definition": "Delegated authorization.", "basic": True}
AGENTS = {"id": "ai_agents", "name": "AI agents", "aliases": [], "definition": "Models that act.", "basic": False}


def raw(title, time_text, slug, abstract):
    start = {"10:35AM PST": "10:35", "11:45AM PST": "11:45"}[time_text]
    return {"title": title, "date": "2026-11-16", "time_text": time_text, "start": start, "end": None,
            "duration_text": None, "room": None, "track": None, "type": "talk", "level": None, "speakers": [],
            "abstract": abstract, "detail_url": DETAIL + slug, "sponsored": False}


def pages():
    home = Page(HOME, "", "Welcome to QCon San Francisco", [("Schedule", SCHEDULE)])
    schedule = parse_page(SCHEDULE, (SITES / "qcon_schedule.html").read_text())
    # The one saved talk page stands in for every talk page: it states "(50 minutes)".
    talk = parse_page(DETAIL + "apis", (SITES / "qcon_talk.html").read_text())
    aie = parse_page(AIE, (SITES / "aie_code_2026.html").read_text())
    return {HOME: home, SCHEDULE: schedule, AIE: aie}, talk


def make_ask(listing, concepts):
    """Canned model answers, chosen by the first words of the system prompt."""
    def ask(system, user, schema):
        if system.startswith("You help find"):
            return {"is_schedule": f"url={SCHEDULE}>" in user or f"url={AIE}>" in user, "link": SCHEDULE}
        if system.startswith("You read a conference schedule"):
            return {"talks": listing}
        if system.startswith("You read one conference talk"):
            return {"abstract": None, "time_text": None, "duration_text": "(50 minutes)"}
        if system.startswith("You build the shared vocabulary"):
            return {"concepts": concepts}
        if system.startswith("You map one conference talk"):
            title = re.search(r"^\[\w+\] (.+)$", user, re.M).group(1)
            return {"requires": [{"concept": concepts[0]["id"], "evidence": title, "confidence": 0.9}],
                    "teaches": [{"concept": concepts[-1]["id"], "evidence": title, "confidence": 0.9}]}
        raise AssertionError(f"unexpected prompt: {system[:40]}")
    return ask


def make_deps(listing, concepts=(OAUTH, AGENTS), fetch=None, explained=None):
    by_url, talk = pages()
    explained = explained if explained is not None else []
    return build.Deps(
        fetch=fetch or (lambda url: by_url.get(url) or talk),
        ask=make_ask(listing, list(concepts)),
        connect=lambda name: connect(PREFIX + name, local=True),
        explain=explained.append,
    )


def graph(name):
    return connect(PREFIX + name, local=True)


def built_graphs():
    return [n for n in _db().list_graphs() if n.startswith(PREFIX + "throughline_c_")]


def _db():
    return FalkorDB(host=settings.falkordb_host, port=settings.falkordb_port)


@pytest.fixture
def reg():
    try:
        g = connect("throughline_test_build_registry", local=True)
        g.query("RETURN 1")
    except Exception as e:
        pytest.skip(f"FalkorDB not reachable: {e}")
    yield g
    for name in built_graphs():
        _db().select_graph(name).delete()
    g.delete()


def qcon(reg):
    return registry.upsert_found(reg, QCON)["id"]


def test_qcon_fixture_builds_partial_or_ready(reg):
    cid = qcon(reg)
    explained = []
    entry = build.run(reg, cid, None, make_deps([raw(*t) for t in TALKS], explained=explained))
    assert cid == "qcon-san-francisco-2026"
    assert entry["status"] in ("ready", "partial"), entry["reason"]
    assert entry["counts"]["kept"] >= 5 and entry["talks"] == entry["counts"]["kept"]
    assert entry["graph"] == f"throughline_c_{cid}_v1"
    assert entry["clock_start"] == "2026-11-16T08:30"
    g = graph(entry["graph"])
    assert g.query("MATCH (t:Talk)-[:PART_OF]->(:Conference {id: $id}) RETURN count(t)",
                   {"id": cid}).result_set[0][0] == entry["counts"]["kept"]
    assert g.query("MATCH (c:Conference) RETURN c.clock_start, c.name").result_set == [
        ["2026-11-16T08:30", "QCon San Francisco 2026"]]
    assert g.query("MATCH (:Talk)-[e:TEACHES]->(:Concept) RETURN count(e)").result_set[0][0] > 0
    assert graph(entry["graph"] + "_public").query("MATCH (t:Talk) RETURN count(t)").result_set[0][0] > 0
    assert [x.name for x in explained] == [PREFIX + entry["graph"]]
    assert "throughline" in _db().list_graphs()  # Universe is never touched


def test_aie_fixture_is_not_found(reg):
    cid = registry.upsert_found(reg, {"name": "AI Engineer Code Summit 2026", "url": AIE,
                                      "start_date": "2026-11-10", "end_date": "2026-11-12"})["id"]
    entry = build.run(reg, cid, None, make_deps([]))
    assert entry["status"] == "not_found"
    assert "doesn't list any talks yet" in entry["reason"]
    assert entry["graph"] == ""
    assert built_graphs() == []


def test_login_wall_and_unsafe_links_are_not_found(reg):
    cid = qcon(reg)
    entry = build.run(reg, cid, None, make_deps([raw(*t) for t in TALKS[:2]]))
    assert (entry["status"], entry["reason"]) == ("not_found", "The schedule page needs a login.")
    entry = build.run(reg, cid, "http://127.0.0.1/schedule", make_deps([], fetch=build.importer.fetch_page))
    assert (entry["status"], entry["reason"]) == ("not_found", "That link can't be fetched safely.")
    assert entry["schedule_url"] == "http://127.0.0.1/schedule"

    def dead(url):
        raise ConnectionError("down")

    entry = build.run(reg, cid, None, make_deps([], fetch=dead))
    assert (entry["status"], entry["reason"]) == ("not_found", f"We couldn't load {HOME}.")


def test_unexpected_error_fails_the_build(reg):
    cid = qcon(reg)
    deps = make_deps([raw(*t) for t in TALKS])
    deps.ask = lambda *a: (_ for _ in ()).throw(KeyError("boom"))
    entry = build.run(reg, cid, None, deps)
    assert (entry["status"], entry["reason"]) == ("failed", "The build stopped: KeyError.")
    assert built_graphs() == []


def test_second_start_joins_running_build(reg):
    cid = qcon(reg)
    release = threading.Event()
    by_url, talk = pages()

    def slow(url):
        release.wait(10)
        return by_url.get(url) or talk

    deps = make_deps([raw(*t) for t in TALKS], fetch=slow)
    first = build.start(reg, cid, deps=deps)
    second = build.start(reg, cid, deps=deps)
    assert first["status"] == second["status"] == "building"
    assert len(build._running) == 1
    thread = build._running[cid]
    release.set()
    thread.join(30)
    assert cid not in build._running
    assert registry.get(reg, cid)["status"] in ("ready", "partial")


def test_interrupted_builds_become_failed(reg):
    cid = qcon(reg)
    registry.set_status(reg, cid, status="building", step=build.STEPS["listing"])
    assert registry.mark_interrupted(reg) == 1
    assert registry.get(reg, cid)["status"] == "failed"
    build.start(reg, cid, deps=make_deps([raw(*t) for t in TALKS]))
    build._running[cid].join(30)
    assert registry.get(reg, cid)["status"] in ("ready", "partial")


def test_worse_retry_keeps_the_old_map(reg):
    cid = qcon(reg)
    first = build.run(reg, cid, None, make_deps([raw(*t) for t in TALKS[:6]]))
    assert first["counts"]["kept"] == 6
    again = build.run(reg, cid, None, make_deps([raw(*t) for t in TALKS[:5]]))
    assert again["graph"] == first["graph"] and again["status"] == first["status"]
    assert again["reason"] == "The retry found fewer talks, so the earlier map was kept."
    assert set(built_graphs()) == {PREFIX + first["graph"], PREFIX + first["graph"] + "_public"}


def test_better_retry_carries_attendee_marks(reg):
    cid = qcon(reg)
    first = build.run(reg, cid, None, make_deps([raw(*t) for t in TALKS[:6]]))
    old = graph(first["graph"])
    talk_code = old.query("MATCH (t:Talk {title: $t}) RETURN t.code", {"t": TALKS[1][0]}).result_set[0][0]
    code = planner.new_attendee(old)
    planner.mark_known(old, code, "oauth2")
    planner.mark_attended(old, code, talk_code)
    planner.add_target(old, code, talk_code)
    old.query("MATCH (a:Attendee {code: $c}) SET a.role = 'SRE'", {"c": code})

    renamed = {**OAUTH, "id": "oauth_2_0"}
    again = build.run(reg, cid, None, make_deps([raw(*t) for t in TALKS], concepts=(renamed, AGENTS)))
    assert again["graph"] == f"throughline_c_{cid}_v2" and again["counts"]["kept"] == 7
    new = graph(again["graph"])
    known = {r[0] for r in new.query("MATCH (:Attendee {code: $c})-[:KNOWS]->(k:Concept) RETURN k.id",
                                     {"c": code}).result_set}
    assert "oauth_2_0" in known
    assert new.query("MATCH (a:Attendee {code: $c})-[:ATTENDED]->(t:Talk) RETURN t.code, a.role",
                     {"c": code}).result_set == [[talk_code, "SRE"]]
    assert new.query("MATCH (:Attendee {code: $c})-[:TARGETS]->(t:Talk) RETURN t.code",
                     {"c": code}).result_set == [[talk_code]]
    assert graph(again["graph"] + "_public").query("MATCH (a:Attendee) RETURN count(a)").result_set[0][0] == 0
    assert set(built_graphs()) == {PREFIX + again["graph"], PREFIX + again["graph"] + "_public"}


def test_clock_and_dates_from_talks():
    talks = [{"date": "2026-11-17", "start": "08:00"}, {"date": "2026-11-16", "start": "09:00"},
             {"date": "2026-11-20", "start": "10:00"}]
    assert build.clock_start(talks) == "2026-11-16T08:30"
    assert build.clock_start([{"date": "2026-11-16", "start": "08:15"}]) == "2026-11-16T07:45"
    assert build.dates_text("2026-11-16", "2026-11-20") == "Nov 16–20, 2026"
    assert build.dates_text("2026-10-30", "2026-11-02") == "Oct 30–Nov 2, 2026"
    assert build.dates_text("2026-11-16", "2026-11-16") == "Nov 16, 2026"


def test_dropped_talks_make_a_partial_map_and_explainer_errors_are_ignored(reg):
    cid = qcon(reg)
    invented = raw("A Talk That Isn't There", "10:35AM PST", "x", "")
    deps = make_deps([raw(*t) for t in TALKS] + [invented])
    deps.explain = lambda g: 1 / 0
    entry = build.run(reg, cid, None, deps)
    assert entry["status"] == "partial"
    assert entry["counts"] == {"kept": 7, "title_not_on_page": 1}


def test_failed_retry_leaves_the_earlier_map_open(reg):
    cid = qcon(reg)
    first = build.run(reg, cid, None, make_deps([raw(*t) for t in TALKS]))

    def dead(url):
        raise ConnectionError("down")

    again = build.run(reg, cid, None, make_deps([], fetch=dead))
    assert (again["status"], again["graph"]) == (first["status"], first["graph"])
    assert again["reason"] == f"We couldn't load {HOME}. The earlier map was kept."


def unlinked_ask(listing):
    ask = make_ask(listing, [OAUTH, AGENTS])

    def failing(system, user, schema):
        if system.startswith("You map one conference talk"):
            raise RuntimeError("model down")
        return ask(system, user, schema)
    return failing


def test_unlinked_retry_keeps_the_old_map(reg):
    cid = qcon(reg)
    first = build.run(reg, cid, None, make_deps([raw(*t) for t in TALKS[:6]]))
    deps = make_deps([raw(*t) for t in TALKS])
    deps.ask = unlinked_ask([raw(*t) for t in TALKS])
    again = build.run(reg, cid, None, deps)
    assert (again["status"], again["graph"]) == (first["status"], first["graph"])
    assert again["reason"] == "The retry couldn't link talks to concepts, so the earlier map was kept."
    assert set(built_graphs()) == {PREFIX + first["graph"], PREFIX + first["graph"] + "_public"}


def test_unlinked_first_build_is_partial(reg):
    cid = qcon(reg)
    deps = make_deps([raw(*t) for t in TALKS])
    deps.ask = unlinked_ask([raw(*t) for t in TALKS])
    entry = build.run(reg, cid, None, deps)
    assert entry["status"] == "partial" and entry["graph"]
    assert entry["counts"]["no_links"] == 7


def test_blog_in_is_not_a_login_wall(reg):
    cid = qcon(reg)
    blog = Page(SCHEDULE, "", "Schedule. Read our blog in full. Live Resharding Without Regret 10:35AM PST", [])
    entry = build.run(reg, cid, SCHEDULE, make_deps([raw(*TALKS[0])], fetch=lambda url: blog))
    assert entry["status"] == "not_found"
    assert entry["reason"] == f"{SCHEDULE} doesn't list any talks yet."


def test_restart_gives_back_maps_and_fails_first_builds(reg):
    retried = qcon(reg)
    registry.set_status(reg, retried, status="building", graph=f"throughline_c_{retried}_v1", counts={"kept": 6})
    first = registry.upsert_found(reg, {"name": "AI Engineer Code Summit 2026", "url": AIE,
                                        "start_date": "2026-11-10", "end_date": "2026-11-12"})["id"]
    registry.set_status(reg, first, status="building")
    assert build.recover_interrupted(reg) == 2
    entry = registry.get(reg, retried)
    assert (entry["status"], entry["reason"]) == ("ready", "A retry was interrupted; the earlier map was kept.")
    entry = registry.get(reg, first)
    assert (entry["status"], entry["reason"]) == ("failed", "The build was interrupted")


def test_a_model_that_never_answers_ends_the_build_in_plain_words(reg):
    cid = qcon(reg)
    deps = make_deps([raw(*t) for t in TALKS])
    listing = deps.ask

    def ask(system, user, schema):
        if system == build.extract.CONCEPTS_PROMPT:
            raise build.importer.DeadlineExceeded("no answer within 600 s")
        return listing(system, user, schema)

    deps.ask = ask
    entry = build.run(reg, cid, None, deps)
    assert (entry["status"], entry["reason"]) == ("failed", "The build stopped: the model took too long to answer.")


def test_concept_drafting_has_a_hard_deadline_and_one_retry(monkeypatch):
    # A float timeout is per read: the QCon retry sat 46 minutes on one drafting call. The wall clock rules now.
    calls, never = [], threading.Event()

    def hang(client, system, user, schema):
        calls.append(len(user))
        never.wait(5)
        return {"concepts": []}

    monkeypatch.setattr(build, "CONCEPTS_DEADLINE", 0.05)
    monkeypatch.setattr(build.extract, "_ask", hang)
    with pytest.raises(build.importer.DeadlineExceeded):
        build.ask_openai(build.extract.CONCEPTS_PROMPT, "x" * 10, {})
    never.set()
    assert calls == [10, 10]


def test_other_model_calls_have_a_hard_deadline(monkeypatch):
    never = threading.Event()
    monkeypatch.setattr(build, "ASK_DEADLINE", 0.05)
    monkeypatch.setattr(build.importer, "ask_openai", lambda system, user, schema: never.wait(5))
    with pytest.raises(build.importer.DeadlineExceeded):
        build.ask_openai("listing", "x", {})
    never.set()
