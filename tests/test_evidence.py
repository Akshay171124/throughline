from throughline.evidence import normalize, phrase_in_source

ABSTRACT = (
    "<p>You know how to use GitHub Copilot. Now learn how to own it.</p> "
    "This expert-level workshop breaks down every customization layer Copilot offers "
    "across app, web, and CLI. No beginner basics, just practical control."
)


def test_exact_phrase_passes():
    assert phrase_in_source("every customization layer Copilot offers", ABSTRACT)


def test_case_whitespace_and_trailing_punctuation_are_ignored():
    assert phrase_in_source("  You know how to use   GITHUB Copilot. ", ABSTRACT)


def test_curly_quotes_and_entities_match_straight_ones():
    source = "It&#8217;s the “full stack” of Copilot"
    assert phrase_in_source("it's the \"full stack\"", source)


def test_paraphrase_fails():
    assert not phrase_in_source("every layer of Copilot customization", ABSTRACT)


def test_text_across_a_tag_boundary_still_matches():
    assert phrase_in_source("own it. This expert-level workshop", ABSTRACT)


def test_single_word_evidence_is_rejected():
    assert not phrase_in_source("Copilot", ABSTRACT)


def test_normalize():
    assert normalize("<b>A</b>&amp; B — C") == "a & b - c"
