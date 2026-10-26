"""Extraction on any conference's talks, with a stub model."""

from throughline import extract


def _talk(code, abstract="Builds on OAuth 2.0 tokens in depth."):
    return {"code": code, "title": f"Talk {code}", "level": "", "type": "Session", "abstract": abstract}


def test_draft_concepts_keeps_basic_flag_and_dedupes():
    def ask(system, user, schema):
        assert "basic" in schema["schema"]["properties"]["concepts"]["items"]["required"]
        return {"concepts": [
            {"id": "oauth", "name": "OAuth 2.0", "aliases": [], "definition": "d1", "basic": True},
            {"id": "oauth", "name": "OAuth again", "aliases": [], "definition": "d2", "basic": False},
            {"id": "pods", "name": "Kubernetes pods", "aliases": [], "definition": "d3", "basic": False},
        ]}

    concepts = extract.draft_concepts([_talk("A1")], ask=ask)
    assert [c["id"] for c in concepts] == ["oauth", "pods"]
    assert concepts[0]["basic"] is True and concepts[0]["name"] == "OAuth 2.0"


def test_extract_edges_skips_empty_abstracts():
    calls = []

    def ask(system, user, schema):
        calls.append(user)
        return {"requires": [{"concept": "oauth", "evidence": "OAuth 2.0 tokens", "confidence": 0.9}], "teaches": []}

    progress = []
    edges, failed = extract.extract_edges(
        [_talk("A1"), _talk("A2", abstract="")],
        [{"id": "oauth", "name": "OAuth 2.0", "definition": "d", "basic": True}],
        ask=ask,
        progress=lambda done, total: progress.append((done, total)),
    )
    assert len(calls) == 1 and failed == 0
    assert [e["talk"] for e in edges] == ["A1"] and edges[0]["type"] == "REQUIRES"
    assert progress[-1] == (1, 1)


def test_extract_edges_counts_failures():
    def ask(system, user, schema):
        if "[A1]" in user:
            raise RuntimeError("boom")
        return {"requires": [], "teaches": [{"concept": "oauth", "evidence": "OAuth 2.0 tokens", "confidence": 0.8}]}

    edges, failed = extract.extract_edges(
        [_talk("A1"), _talk("A2")], [{"id": "oauth", "name": "OAuth", "definition": "d"}], ask=ask
    )
    assert failed == 1
    assert [(e["talk"], e["type"]) for e in edges] == [("A2", "TEACHES")]
