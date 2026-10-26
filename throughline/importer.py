"""Import any conference from its web page: fetch the page and read it.

This module is the page layer. `fetch_page` gets a URL over plain HTTP and falls back
to Bright Data's Browser API when the page is blocked or needs JavaScript;
`parse_page` turns the HTML into visible text and absolute links. Later steps have the
model read talks from this text and check every title and URL against it.
"""

import ipaddress
import socket
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlparse

import httpx

from . import brightdata

MIN_TEXT = 1500  # less visible text than this means the page needs a real browser
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
SKIPPED = {"script", "style", "noscript", "template"}
# Inline tags sit inside a word or line; every other tag (and <br>) is a boundary.
INLINE = {
    "a", "abbr", "b", "bdi", "bdo", "cite", "code", "data", "dfn", "em", "i", "kbd", "mark",
    "q", "s", "samp", "small", "span", "strong", "sub", "sup", "time", "u", "var", "wbr",
}
MAX_HOPS = 5


class UnsafeURL(ValueError):
    """The URL is not a public http(s) address, so it is never fetched."""


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

    def _boundary(self, tag):
        if tag not in INLINE and not self.skip:
            self.handle_data(" ")

    def handle_starttag(self, tag, attrs):
        if tag in SKIPPED:
            self.skip += 1
        elif tag == "a" and not self.skip:
            href = dict(attrs).get("href")
            if href:
                url = urldefrag(urljoin(self.base, href.strip()))[0]
                if urlparse(url).scheme in ("http", "https"):
                    self._open = [url, ""]
        else:
            self._boundary(tag)

    def handle_endtag(self, tag):
        if tag in SKIPPED:
            self.skip = max(0, self.skip - 1)
        elif tag == "a" and self._open:
            url, text = self._open
            self._open = None
            self.links.append((" ".join(text.split()), url))
        else:
            self._boundary(tag)

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
    return Page(url, html, " ".join("".join(reader.chunks).split()), links)


def _check_url(url: str, resolve) -> None:
    """Refuse anything but http(s) to a public address (blocks loopback, private, link-local...)."""
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise UnsafeURL(f"not a web URL: {url}")
    host = parts.hostname.rstrip(".").lower()
    try:
        addrs = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = resolve(host, None)
        except OSError as e:
            raise UnsafeURL(f"cannot resolve {host}") from e
        addrs = [ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos]
    if not addrs:
        raise UnsafeURL(f"cannot resolve {host}")
    for addr in addrs:
        for a in (addr, getattr(addr, "ipv4_mapped", None)):
            if a and (a.is_loopback or a.is_private or a.is_link_local or a.is_reserved
                      or a.is_multicast or a.is_unspecified):
                raise UnsafeURL(f"{host} is not a public address")


def _get(url: str, http, resolve):
    """GET with every hop (the URL and each redirect) checked; raises UnsafeURL on a bad one."""
    for _ in range(MAX_HOPS + 1):
        _check_url(url, resolve)
        resp = http(url, timeout=20, headers={"User-Agent": USER_AGENT}, follow_redirects=False)
        location = resp.headers.get("location") if 300 <= resp.status_code < 400 else None
        if not location:
            return url, resp
        url = urljoin(url, location)
    raise UnsafeURL("too many redirects")


def fetch_page(url: str, http=httpx.get, render=brightdata.render_page, resolve=socket.getaddrinfo) -> Page:
    """Plain GET first; the Browser API when that fails, is blocked, or returns a thin page.

    An unsafe URL raises UnsafeURL and is never rendered either.
    """
    if urlparse(url).scheme not in ("http", "https"):
        raise UnsafeURL(f"not a web URL: {url}")
    try:
        final, resp = _get(url, http, resolve)
        if resp.status_code < 400:
            page = parse_page(final, resp.text)
            if len(page.text) >= MIN_TEXT:
                return page
    except UnsafeURL:
        raise
    except Exception:
        pass
    return parse_page(url, render(url))
