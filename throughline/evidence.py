"""The word-for-word evidence check.

Every edge the model proposes carries an evidence phrase. The edge is kept only
if that phrase appears in its source after both are normalized the same way.
Friday's debate check showed why normalizing matters: a plain search missed
real quotes about a third of the time because of entities, curly quotes,
inline links and line wraps.
"""

import html
import re

_QUOTES = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "″": '"',
    "–": "-", "—": "-", "−": "-",
    " ": " ", "…": "...",
})


def normalize(text: str | None) -> str:
    """Strip tags, decode entities, straighten quotes and dashes, collapse whitespace, lowercase."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text).translate(_QUOTES)
    return re.sub(r"\s+", " ", text).strip().lower()


def phrase_in_source(phrase: str, source: str, min_words: int = 2) -> bool:
    """True if the evidence phrase appears word for word in the source text.

    Phrases under `min_words` words are rejected: a single word like "agents"
    would match almost any abstract and prove nothing.
    """
    needle = normalize(phrase).strip(" .,;:\"'")
    if len(needle.split()) < min_words:
        return False
    return needle in normalize(source)
