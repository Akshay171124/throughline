"""Page layer of the importer: parsing visible text and links, and the fetch fallback."""

from pathlib import Path

import pytest

from throughline.importer import MIN_TEXT, UnsafeURL, fetch_page, parse_page

SITES = Path(__file__).parent / "fixtures" / "sites"
QCON = "https://qconsf.com/schedule/nov2026"


class Resp:
    def __init__(self, status, text, location=None):
        self.status_code = status
        self.text = text
        self.headers = {"location": location} if location else {}


HOSTS = {"qconsf.com": "93.184.216.36", "localhost": "127.0.0.1", "good.org": "93.184.216.34", "other.org": "93.184.216.35"}


def resolve(host, port):
    return [(2, 1, 6, "", (HOSTS[host], 0))]


def _qcon() -> str:
    return (SITES / "qcon_schedule.html").read_text()


def test_parse_qcon_schedule_text_and_links():
    page = parse_page(QCON, _qcon())
    assert "Live Resharding Without Regret" in page.text
    assert "10:35AM PST" in page.text
    assert "<script" not in page.text
    urls = [u for _, u in page.links]
    assert "https://qconsf.com/presentation/nov2026/live-resharding-without-regret-lessons-building-valkeys-atomic-slot-migration" in urls


def test_links_are_absolute_and_fragment_free():
    page = parse_page("https://x.org/a/", '<a href="/p/1#top">One</a><a href="#day2">D</a><a href="b">B</a>')
    assert page.links == [("One", "https://x.org/p/1"), ("D", "https://x.org/a/"), ("B", "https://x.org/a/b")]


def test_skips_script_style_and_decodes_entities():
    page = parse_page("https://x.org/", "<style>p{}</style><script>var a=1</script><p>Tom &amp;   Jerry</p><noscript>no</noscript>")
    assert page.text == "Tom & Jerry"


def test_thin_page_falls_back_to_browser():
    page = fetch_page(QCON, http=lambda *a, **k: Resp(200, "<p>hi</p>"), render=lambda u: _qcon(), resolve=resolve)
    assert "Live Resharding Without Regret" in page.text


def test_full_plain_page_never_renders():
    body = "<p>" + "word " * 1000 + "</p>"
    assert len(body) > MIN_TEXT

    def no_render(url):
        raise AssertionError("render called")

    page = fetch_page(QCON, http=lambda *a, **k: Resp(200, body), render=no_render, resolve=resolve)
    assert page.text.startswith("word")


def test_error_status_and_exception_fall_back():
    def boom(*a, **k):
        raise OSError("down")

    assert fetch_page(QCON, http=lambda *a, **k: Resp(403, "x"), render=lambda u: _qcon(), resolve=resolve).text
    assert fetch_page(QCON, http=boom, render=lambda u: _qcon(), resolve=resolve).text


def test_inline_tags_do_not_split_words():
    page = parse_page("https://x.org/", "<p>10:<b>35</b>AM PST</p><p><em>Un</em>believable</p>")
    assert "10:35AM PST" in page.text and "Unbelievable" in page.text
    assert "PST Unbelievable" in page.text


def test_links_keep_only_http_and_https():
    html = '<a href="data:text/html,x">D</a><a href="mailto:a@b.c">M</a><a href="sms:1">S</a><a href="ftp://h/f">F</a><a href="/ok">OK</a>'
    assert parse_page("https://x.org/", html).links == [("OK", "https://x.org/ok")]


def never(*a, **k):
    raise AssertionError("must not be called")


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://localhost/", "http://169.254.169.254/latest/meta-data",
    "http://10.0.0.5/", "file:///etc/passwd", "http://[::1]/",
])
def test_unsafe_urls_are_refused(url):
    with pytest.raises(UnsafeURL):
        fetch_page(url, http=never, render=never, resolve=resolve)


def test_redirect_to_private_address_is_refused():
    def http(url, **k):
        return Resp(302, "", "http://127.0.0.1/admin")

    with pytest.raises(UnsafeURL):
        fetch_page("http://good.org/", http=http, render=never, resolve=resolve)


def test_public_redirect_is_followed():
    body = "<p>" + "word " * 1000 + "</p>"
    seen = []

    def http(url, **k):
        seen.append(url)
        assert k["follow_redirects"] is False
        return Resp(301, "", "/next") if url == "http://good.org/" else Resp(200, body)

    page = fetch_page("http://good.org/", http=http, render=never, resolve=resolve)
    assert seen == ["http://good.org/", "http://good.org/next"] and page.url == "http://good.org/next"


def test_within_gives_up_on_a_call_that_never_returns():
    import threading
    import time

    from throughline.importer import DeadlineExceeded, within

    never = threading.Event()
    started = time.monotonic()
    with pytest.raises(DeadlineExceeded):
        within(0.05, never.wait)
    assert time.monotonic() - started < 1
    never.set()
    assert within(1, lambda a, b: a + b, 2, 3) == 5
    with pytest.raises(KeyError):
        within(1, {}.__getitem__, "missing")
