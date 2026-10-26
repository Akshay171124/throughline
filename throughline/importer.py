"""Import any conference from its web page: fetch the page and read it.

This module is the page layer. `fetch_page` gets a URL over plain HTTP and falls back
to Bright Data's Browser API when the page is blocked or needs JavaScript;
`parse_page` turns the HTML into visible text and absolute links. Later steps have the
model read talks from this text and check every title and URL against it.
"""

from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin

import httpx

from . import brightdata

MIN_TEXT = 1500  # less visible text than this means the page needs a real browser
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
SKIPPED = {"script", "style", "noscript", "template"}


@dataclass
class Page:
    url: str
    html: str
    text: str
    links: list[tuple[str, str]] = field(default_factory=list)


class _Reader(HTMLParser):
    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.skip = 0
        self.chunks: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._open: list[str] | None = None  # href and anchor text of the link being read

    def handle_starttag(self, tag, attrs):
        if tag in SKIPPED:
            self.skip += 1
        elif tag == "a" and not self.skip:
            href = dict(attrs).get("href")
            if href and not href.strip().lower().startswith(("javascript:", "mailto:", "tel:")):
                self._open = [urldefrag(urljoin(self.base, href.strip()))[0], ""]

    def handle_endtag(self, tag):
        if tag in SKIPPED:
            self.skip = max(0, self.skip - 1)
        elif tag == "a" and self._open:
            url, text = self._open
            self._open = None
            self.links.append((" ".join(text.split()), url))

    def handle_data(self, data):
        if self.skip:
            return
        self.chunks.append(data)
        if self._open:
            self._open[1] += data


def parse_page(url: str, html: str) -> Page:
    """Visible text (whitespace collapsed) and de-duplicated absolute links, in page order."""
    reader = _Reader(url)
    reader.feed(html)
    reader.close()
    seen, links = set(), []
    for link in reader.links:
        if link not in seen:
            seen.add(link)
            links.append(link)
    return Page(url, html, " ".join(" ".join(reader.chunks).split()), links)


def fetch_page(url: str, http=httpx.get, render=brightdata.render_page) -> Page:
    """Plain GET first; the Browser API when that fails, is blocked, or returns a thin page."""
    try:
        resp = http(url, timeout=20, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
        if resp.status_code < 400:
            page = parse_page(url, resp.text)
            if len(page.text) >= MIN_TEXT:
                return page
    except Exception:
        pass
    return parse_page(url, render(url))
