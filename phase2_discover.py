"""MF-Engine — Phase 2: team & scheme page discovery.

Reads data/amc_seed_list.json, fetches each AMC's sitemap (plain HTTP first,
headless Chromium for WAF-walled sites), and classifies the URLs the site
itself publishes into team/management pages and fund/scheme pages.

Hard rule: no URL is ever constructed from a template. Only sitemap <loc>
entries and on-page anchors are eligible; team URLs are resolved through
redirects to their final destination.

Output: data/amc_page_inventory.json

Usage:
    python phase2_discover.py
"""

import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("mf-engine.discover")
logging.getLogger("httpx").setLevel(logging.WARNING)

SEED_PATH = Path("data/amc_seed_list.json")
OUTPUT_PATH = Path("data/amc_page_inventory.json")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

HTTP_TIMEOUT = 12.0
HTTP_CONCURRENCY = 10
BROWSER_CONCURRENCY = 2
MAX_CHILD_SITEMAPS = 15  # sitemap indexes can list dozens; page maps come first
MAX_URLS_PER_AMC = 2000

# Classify *discovered* URLs only — these patterns never build paths.
TEAM_URL_RE = re.compile(
    r"fund-?managers?|our-?team|management-?team|investment-?team|leadership"
    r"|key-?personnel|our-?people|board-?of|/team(?:/|$|\.)",
    re.IGNORECASE,
)
SCHEME_URL_RE = re.compile(
    r"mutual-?funds?/|/schemes?(?:/|$)|/funds?(?:/|$)|-fund(?:/|$|-)",
    re.IGNORECASE,
)
LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)


def url_variants(url: str) -> list[str]:
    """The URL as-is, plus a www. variant — some CDNs (e.g. Akamai on
    hdfcfund.com) hard-deny the apex host while serving www fine."""
    variants = [url]
    netloc = urlparse(url).netloc
    if not netloc.startswith("www."):
        variants.append(url.replace(f"//{netloc}", f"//www.{netloc}", 1))
    return variants


def same_site(url: str, base_domain: str) -> bool:
    """Keep URLs on the AMC's registered domain (subdomains allowed)."""
    netloc = urlparse(url).netloc.lower().removeprefix("www.")
    root = base_domain.removeprefix("www.")
    # compare on the last two labels so mf.example.com matches example.com
    tail = ".".join(root.split(".")[-2:])
    return netloc == root or netloc.endswith("." + tail)


async def fetch_text(client: httpx.AsyncClient, url: str) -> tuple[str, str] | None:
    """GET through redirects; returns (final_url, body) or None."""
    try:
        resp = await client.get(url)
        if resp.status_code == 200 and resp.text:
            return str(resp.url), resp.text
    except httpx.HTTPError:
        pass
    return None


async def fetch_via_browser(crawler: AsyncWebCrawler, url: str) -> str | None:
    """Chromium fallback for WAF-walled sites; returns raw page HTML."""
    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        delay_before_return_html=2.0,
        page_timeout=45_000,
    )
    try:
        result = await crawler.arun(url=url, config=config)
        if result.success:
            return result.html
    except Exception:
        log.debug("browser fetch failed for %s", url)
    return None


def extract_sitemap_urls(body: str) -> tuple[list[str], bool]:
    """Pull <loc> entries; second value marks a sitemap index (children, not pages)."""
    locs = LOC_RE.findall(body)
    is_index = "<sitemapindex" in body.lower()
    return locs, is_index


def extract_anchor_urls(html: str, page_url: str) -> list[str]:
    """Absolutized hrefs from an HTML page (HTML sitemaps, homepage fallback)."""
    soup = BeautifulSoup(html, "html.parser")
    urls = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        urls.append(urljoin(page_url, href))
    return urls


async def collect_urls(
    client: httpx.AsyncClient,
    crawler: AsyncWebCrawler,
    browser_sem: asyncio.Semaphore,
    record: dict,
) -> tuple[list[str], str]:
    """All page URLs an AMC's site publishes, and how we got them."""
    sitemap_url = record["sitemap_url"]
    domain = record["base_domain"]

    async def get(url: str) -> tuple[str, str] | None:
        for candidate in url_variants(url):
            got = await fetch_text(client, candidate)
            if got:
                return got
        for candidate in url_variants(url):
            async with browser_sem:
                html = await fetch_via_browser(crawler, candidate)
            if html:
                return candidate, html
        return None

    got = await get(sitemap_url)
    if got:
        final_url, body = got
        if record["sitemap_type"] == "xml" or "<loc" in body.lower():
            locs, is_index = extract_sitemap_urls(body)
            if is_index:
                pages: list[str] = []
                for child in locs[:MAX_CHILD_SITEMAPS]:
                    child_got = await get(child)
                    if child_got:
                        child_locs, _ = extract_sitemap_urls(child_got[1])
                        pages.extend(child_locs)
                    if len(pages) >= MAX_URLS_PER_AMC:
                        break
                if pages:
                    return pages[:MAX_URLS_PER_AMC], "sitemap_index"
            if locs:
                return locs[:MAX_URLS_PER_AMC], "sitemap_xml"
        # HTML sitemap page: its anchors are the inventory
        anchors = extract_anchor_urls(body, final_url)
        if anchors:
            return anchors[:MAX_URLS_PER_AMC], "sitemap_html"

    # Last resort: the homepage's own nav/anchor links (still discovered URLs)
    home = await get(f"https://{domain}")
    if home:
        anchors = extract_anchor_urls(home[1], home[0])
        if anchors:
            return anchors[:MAX_URLS_PER_AMC], "homepage_anchors"
    return [], "unreachable"


def classify(urls: list[str], base_domain: str) -> tuple[list[str], list[str]]:
    team: list[str] = []
    scheme: list[str] = []
    seen: set[str] = set()
    for url in urls:
        url = url.split("#")[0].strip()
        if not url or url in seen or not same_site(url, base_domain):
            continue
        seen.add(url)
        path = urlparse(url).path
        if TEAM_URL_RE.search(path):
            team.append(url)
        elif SCHEME_URL_RE.search(path):
            scheme.append(url)
    return team, scheme


async def resolve_finals(client: httpx.AsyncClient, urls: list[str]) -> list[str]:
    """Follow each team URL to its final destination (dedup after redirects)."""
    finals: list[str] = []
    for url in urls:
        got = await fetch_text(client, url)
        final = got[0] if got else url
        if final not in finals:
            finals.append(final)
    return finals


async def main() -> int:
    if not SEED_PATH.exists():
        log.error("Seed list missing — run main.py first (%s)", SEED_PATH)
        return 1
    seeds = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    log.info("Discovering pages for %d AMCs", len(seeds))

    http_sem = asyncio.Semaphore(HTTP_CONCURRENCY)
    browser_sem = asyncio.Semaphore(BROWSER_CONCURRENCY)
    browser_config = BrowserConfig(headless=True, user_agent=USER_AGENT)
    inventory: list[dict] = []

    async with AsyncWebCrawler(config=browser_config) as crawler:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        ) as client:

            async def process(record: dict) -> None:
                async with http_sem:
                    try:
                        urls, source = await collect_urls(
                            client, crawler, browser_sem, record
                        )
                        team, scheme = classify(urls, record["base_domain"])
                        team = await resolve_finals(client, team[:25])
                    except Exception:
                        log.exception("Discovery failed for %s", record["base_domain"])
                        urls, source, team, scheme = [], "error", [], []
                    inventory.append(
                        {
                            "amc_id": record["amc_id"],
                            "firm_name": record["firm_name"],
                            "base_domain": record["base_domain"],
                            "source": source,
                            "discovered_total": len(urls),
                            "team_urls": team,
                            "scheme_urls": scheme,
                        }
                    )
                    log.info(
                        "%-45s %-16s pages=%-5d team=%-3d scheme=%d",
                        record["firm_name"],
                        source,
                        len(urls),
                        len(team),
                        len(scheme),
                    )

            await asyncio.gather(*(process(r) for r in seeds))

    inventory.sort(key=lambda r: r["amc_id"])
    OUTPUT_PATH.write_text(
        json.dumps(inventory, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    with_team = sum(1 for r in inventory if r["team_urls"])
    with_scheme = sum(1 for r in inventory if r["scheme_urls"])
    log.info(
        "Wrote %s — %d/%d AMCs with team pages, %d with scheme pages",
        OUTPUT_PATH,
        with_team,
        len(inventory),
        with_scheme,
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
