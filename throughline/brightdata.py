"""Bright Data: live web data for the schedule and for outside explainers.

- `fetch_catalog()` loads the Universe catalog page in Bright Data's Browser API and
  records the JSON feed the page itself loads (the page renders with JavaScript).
- `find_explainers()` uses the SERP API to find a short explainer for a concept
  no talk teaches in time, and stores it as (Resource)-[:EXPLAINS]->(Concept).

  uv run python -m throughline.brightdata catalog
  uv run python -m throughline.brightdata explain <concept_id>
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from urllib.parse import quote_plus, urlparse

import httpx
from falkordb import Graph

from .catalog import extract_items, normalize_items, write_snapshot
from .config import ROOT, settings

CATALOG_URL = "https://reg.githubuniverse.com/flow/github/universe26/attendee-portal/page/sessioncatalog"
FEED_MARKER = "/api/sessions"
REQUEST_API = "https://api.brightdata.com/request"

# Documentation and established educational sources only (the explainer filter).
EXPLAINER_DOMAINS = (
    "docs.github.com", "github.blog", "learn.microsoft.com", "code.visualstudio.com",
    "modelcontextprotocol.io", "developer.mozilla.org", "docs.docker.com", "kubernetes.io",
    "owasp.org", "slsa.dev", "openssf.org", "cloud.google.com", "aws.amazon.com", "docs.aws.amazon.com",
    "platform.openai.com", "developers.openai.com", "docs.anthropic.com", "wikipedia.org", "youtube.com",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _env(name: str) -> str:
    value = os.getenv(name, "")
    if not value:
        raise RuntimeError(f"{name} is empty in .env")
    return value


# --- schedule ---------------------------------------------------------------

async def _record_feed(max_pages: int = 12) -> list[dict]:
    from playwright.async_api import async_playwright

    payloads: list[dict] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(_env("BRIGHTDATA_BROWSER_WS"))
        try:
            page = await browser.new_page()

            async def on_response(response):
                if FEED_MARKER in response.url and response.request.method == "POST":
                    try:
                        payloads.append(await response.json())
                    except Exception:
                        pass

            page.on("response", on_response)
            await page.goto(CATALOG_URL, wait_until="networkidle", timeout=120_000)
            for _ in range(max_pages):  # the catalog loads 50 sessions at a time behind "Show more"
                before = len(payloads)
                more = page.get_by_text("Show more", exact=True)
                if not await more.count():
                    break
                await more.last.click()
                for _ in range(60):  # each batch takes 6-11 s through the proxy; give up after 30 s
                    await page.wait_for_timeout(500)
                    if len(payloads) > before:
                        break
                else:
                    break
        finally:
            await browser.close()
    items, seen = [], set()
    for payload in payloads:
        for item in extract_items(payload):
            if item.get("sessionID") not in seen:
                seen.add(item.get("sessionID"))
                items.append(item)
    return items


def fetch_catalog(min_ratio: float = 0.8) -> dict:
    """Scrape the catalog; keep the last good snapshot if the scrape looks broken."""
    items = asyncio.run(_record_feed())
    talks = normalize_items(items)
    previous = sum(1 for _ in settings.talks_snapshot.open()) if settings.talks_snapshot.exists() else 0
    missing = [t["code"] for t in talks if not (t["title"] and t["abstract"] and t["start"])]
    if len(talks) < previous * min_ratio or missing:
        return {"ok": False, "kept_snapshot": True, "scraped": len(talks), "previous": previous, "missing_fields": missing[:10]}
    raw_path = ROOT / "data" / "raw" / f"universe26_feed_{datetime.now():%Y-%m-%d}.json"
    raw_path.write_text(json.dumps({"source": "brightdata-browser-api", "fetched_at": _now(), "items": items}, ensure_ascii=False))
    write_snapshot(talks, settings.talks_snapshot)
    return {"ok": True, "scraped": len(talks), "previous": previous, "raw": str(raw_path)}


async def _render(url: str, timeout_ms: int) -> str:
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(_env("BRIGHTDATA_BROWSER_WS"))
        try:
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            return await page.content()
        finally:
            await browser.close()


def render_page(url: str, timeout_ms: int = 90_000) -> str:
    """Load any page in Bright Data's Browser API and return its rendered HTML."""
    return asyncio.run(_render(url, timeout_ms))


# --- outside explainers -----------------------------------------------------

def serp_search(query: str, num: int = 10) -> list[dict]:
    """Google results through Bright Data's SERP API, parsed to title/url/snippet."""
    url = f"https://www.google.com/search?q={quote_plus(query)}&num={num}&brd_json=1"
    response = httpx.post(
        REQUEST_API,
        headers={"Authorization": f"Bearer {_env('BRIGHTDATA_API_TOKEN')}"},
        json={"zone": _env("BRIGHTDATA_SERP_ZONE"), "url": url, "format": "raw"},
        timeout=60,
    )
    response.raise_for_status()
    if error := response.headers.get("x-brd-error"):  # some failures arrive as 200 + a plain-text message
        raise RuntimeError(f"Bright Data SERP: {error}")
    data = response.json() if response.headers.get("content-type", "").startswith("application/json") else json.loads(response.text)
    return [
        {"title": r.get("title", ""), "url": r.get("link") or r.get("url", ""), "snippet": r.get("description") or r.get("snippet", "")}
        for r in data.get("organic", [])
    ]


def _allowed(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(host == d or host.endswith("." + d) for d in EXPLAINER_DOMAINS)


def find_explainers(g: Graph, concept_id: str, limit: int = 1) -> list[dict]:
    """Search for a short explainer and store the first acceptable result on the concept."""
    rows = g.query("MATCH (c:Concept {id: $id}) RETURN c.name, c.definition", {"id": concept_id}).result_set
    if not rows:
        raise ValueError(f"No concept {concept_id}")
    name, definition = rows[0]
    results = [r for r in serp_search(f"{name} explained introduction") if r["url"] and _allowed(r["url"])][:limit]
    fetched_at = _now()
    for r in results:
        g.query(
            """
            MATCH (c:Concept {id: $id})
            MERGE (res:Resource {url: $url})
            SET res.title = $title, res.snippet = $snippet, res.fetched_at = $fetched_at, res.source = 'brightdata-serp'
            MERGE (res)-[e:EXPLAINS]->(c)
            SET e.evidence = $snippet, e.checked_at = $fetched_at
            """,
            {"id": concept_id, "url": r["url"], "title": r["title"], "snippet": r["snippet"], "fetched_at": fetched_at},
        )
    return results


if __name__ == "__main__":
    from .graph import connect

    if sys.argv[1:2] == ["catalog"]:
        print(json.dumps(fetch_catalog(), indent=2))
    elif sys.argv[1:2] == ["explain"] and len(sys.argv) > 2:
        print(json.dumps(find_explainers(connect(), sys.argv[2]), indent=2))
    else:
        print(__doc__)
