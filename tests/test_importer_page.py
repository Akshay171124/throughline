"""Page layer of the importer: parsing visible text and links, and the fetch fallback."""

from pathlib import Path

from throughline.importer import MIN_TEXT, fetch_page, parse_page

SITES = Path(__file__).parent / "fixtures" / "sites"
QCON = "https://qconsf.com/schedule/nov2026"


class Resp:
    def __init__(self, status, text):
        self.status_code = status
        self.text = text


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
    page = fetch_page(QCON, http=lambda *a, **k: Resp(200, "<p>hi</p>"), render=lambda u: _qcon())
    assert "Live Resharding Without Regret" in page.text


def test_full_plain_page_never_renders():
    body = "<p>" + "word " * 1000 + "</p>"
    assert len(body) > MIN_TEXT

    def no_render(url):
        raise AssertionError("render called")

    page = fetch_page(QCON, http=lambda *a, **k: Resp(200, body), render=no_render)
    assert page.text.startswith("word")


def test_error_status_and_exception_fall_back():
    def boom(*a, **k):
        raise OSError("down")

    assert fetch_page(QCON, http=lambda *a, **k: Resp(403, "x"), render=lambda u: _qcon()).text
    assert fetch_page(QCON, http=boom, render=lambda u: _qcon()).text
