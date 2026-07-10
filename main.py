"""MF-Engine — Phase 1: AMFI AMC seed list builder.

Scrapes the AMFI members directory
(https://www.amfiindia.com/aboutamfi?tab=members) for all active Asset
Management Companies in India, resolves each AMC's corporate domain (known
mapping first, slug fallback second), and writes a crawler seed list to
data/amc_seed_list.json.

If the live scrape fails (network drop, bot block, DOM change) the script
falls back to an embedded static list of active AMCs so a seed file is always
produced.

Usage:
    python main.py
"""

import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("mf-engine.seed")
logging.getLogger("httpx").setLevel(logging.WARNING)  # per-request GET lines are noise

# NOTE: /members returns 404 — the directory lives on the About AMFI page's
# members tab, rendered client-side. Member names link to /member/{id} pages.
AMFI_MEMBERS_URL = "https://www.amfiindia.com/aboutamfi?tab=members"
OUTPUT_PATH = Path("data/amc_seed_list.json")
SITEMAP_TIMEOUT = 8.0
SITEMAP_CONCURRENCY = 10

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Legal / generic suffixes stripped from firm names, longest patterns first so
# e.g. "Asset Management Company" wins over "Asset Management".
LEGAL_SUFFIXES = [
    r"asset management company limited",
    r"asset management company ltd",
    r"asset management company",
    r"asset management co\.? ltd\.?",
    r"asset management co",
    r"asset management limited",
    r"asset management ltd",
    r"asset management",
    r"investment managers?",
    r"mutual fund",
    r"private limited",
    r"pvt\.? ltd\.?",
    r"limited",
    r"ltd\.?",
    r"amc",
]

# Curated domain map for active Indian AMCs. Keys are lowercase clean names
# (post suffix-stripping). Unmapped names fall through to slug guessing.
KNOWN_DOMAINS = {
    "360 one": "mf.360.one",
    "abakkus": "abakkusmf.com",
    "aditya birla sun life": "mutualfund.adityabirlacapital.com",
    "angel one": "angelonemf.com",
    "axis": "axismf.com",
    "bajaj finserv": "bajajamc.com",
    "bandhan": "bandhanmutual.com",
    "bank of india": "boimf.in",
    "baroda bnp paribas": "barodabnpparibasmf.in",
    "canara robeco": "canararobeco.com",
    "capitalmind": "capitalmindmf.com",
    "dsp": "dspim.com",
    "edelweiss": "edelweissmf.com",
    "franklin templeton": "franklintempletonindia.com",
    "groww": "growwmf.in",
    "hdfc": "hdfcfund.com",
    "helios": "heliosmf.in",
    "hsbc": "assetmanagement.hsbc.co.in",
    "icici prudential": "icicipruamc.com",
    "invesco": "invescomutualfund.com",
    "iti": "itimf.com",
    # jioblackrock.com is the investment-adviser arm; the AMC is jioblackrockamc.com
    "jio blackrock": "jioblackrockamc.com",
    "jm financial": "jmfinancialmf.com",
    "kotak mahindra": "kotakmf.com",
    "lic": "licmf.com",
    "mahindra manulife": "mahindramanulife.com",
    "mirae asset": "miraeassetmf.co.in",
    "motilal oswal": "motilaloswalmf.com",
    "navi": "navi.com",
    "nippon india": "mf.nipponindiaim.com",
    "nj": "njmutualfund.com",
    "old bridge": "oldbridgemf.com",
    "pgim india": "pgimindiamf.com",
    "ppfas": "amc.ppfas.com",
    "quant": "quantmutual.com",
    "quantum": "quantumamc.com",
    "samco": "samcomf.com",
    "sbi": "sbimf.com",
    "shriram": "shriramamc.in",
    "sundaram": "sundarammutual.com",
    "tata": "tatamutualfund.com",
    "taurus": "taurusmutualfund.com",
    "the wealth company": "wealthcompany.in",
    "trust": "trustmf.com",
    "unifi": "unifimf.com",
    "union": "unionmf.com",
    "uti": "utimf.com",
    "whiteoak capital": "mf.whiteoakamc.com",
    "zerodha": "zerodhafundhouse.com",
}

# Fallback roster of the 49 active AMFI member AMCs (verified July 2026).
# Used only when the live scrape yields nothing, so the pipeline always gets
# a seed file.
STATIC_AMC_NAMES = [
    "360 ONE Mutual Fund",
    "Abakkus Mutual Fund",
    "Aditya Birla Sun Life Mutual Fund",
    "Angel One Mutual Fund",
    "Axis Mutual Fund",
    "Bajaj Finserv Mutual Fund",
    "Bandhan Mutual Fund",
    "Bank of India Mutual Fund",
    "Baroda BNP Paribas Mutual Fund",
    "Canara Robeco Mutual Fund",
    "Capitalmind Mutual Fund",
    "DSP Mutual Fund",
    "Edelweiss Mutual Fund",
    "Franklin Templeton Mutual Fund",
    "Groww Mutual Fund",
    "HDFC Mutual Fund",
    "Helios Mutual Fund",
    "HSBC Mutual Fund",
    "ICICI Prudential Mutual Fund",
    "Invesco Mutual Fund",
    "ITI Mutual Fund",
    "Jio BlackRock Mutual Fund",
    "JM Financial Mutual Fund",
    "Kotak Mahindra Mutual Fund",
    "LIC Mutual Fund",
    "Mahindra Manulife Mutual Fund",
    "Mirae Asset Mutual Fund",
    "Motilal Oswal Mutual Fund",
    "Navi Mutual Fund",
    "Nippon India Mutual Fund",
    "NJ Mutual Fund",
    "Old Bridge Mutual Fund",
    "PGIM India Mutual Fund",
    "PPFAS Mutual Fund",
    "quant Mutual Fund",
    "Quantum Mutual Fund",
    "Samco Mutual Fund",
    "SBI Mutual Fund",
    "Shriram Mutual Fund",
    "Sundaram Mutual Fund",
    "Tata Mutual Fund",
    "Taurus Mutual Fund",
    "The Wealth Company Mutual Fund",
    "Trust Mutual Fund",
    "Unifi Mutual Fund",
    "Union Mutual Fund",
    "UTI Mutual Fund",
    "WhiteOak Capital Mutual Fund",
    "Zerodha Mutual Fund",
]

# Names on the members page that are not AMCs themselves.
NON_AMC_PATTERNS = re.compile(
    r"association of mutual funds|amfi|registrar|trustee", re.IGNORECASE
)

# The members page hydrates from an embedded (escaped) JSON payload with one
# object per AMC: {"mf_id":"64","mf_name":"PPFAS Mutual Fund",
# "amc_name":"PPFAS Asset Management Pvt. Ltd.","amc_website":"https://amc.ppfas.com",...}
# Field order is stable, so a sequential regex over the unescaped HTML is the
# most reliable extraction — official websites included, no guessing needed.
PAYLOAD_RECORD_RE = re.compile(
    r'"mf_id":"(?P<mf_id>\d+)","mf_name":"(?P<mf_name>[^"]+)",'
    r'"amc_name":"(?P<amc_name>[^"]+)","amc_website":"(?P<website>[^"]*)"'
)


def clean_name(firm_name: str) -> str:
    """Strip legal suffixes and normalize whitespace: core firm name only."""
    name = re.sub(r"\s+", " ", firm_name).strip()
    lowered = name.lower()
    changed = True
    while changed:
        changed = False
        for suffix in LEGAL_SUFFIXES:
            match = re.search(rf"\b{suffix}\s*$", lowered)
            if match:
                name = name[: match.start()].rstrip(" ,.-")
                lowered = name.lower()
                changed = True
    return name.strip()


def slugify(name: str) -> str:
    """Lowercase alphanumeric slug for fallback domain guessing."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def resolve_domain(cleaned: str) -> str:
    """Map a clean AMC name to its corporate domain, guessing when unknown."""
    key = cleaned.lower()
    if key in KNOWN_DOMAINS:
        return KNOWN_DOMAINS[key]
    # Partial match: known key contained in the scraped name (or vice versa)
    # absorbs punctuation/ordering drift in the directory listing. Longest
    # keys first so "quantum" wins over "quant" for Quantum MF.
    for known, domain in sorted(
        KNOWN_DOMAINS.items(), key=lambda kv: len(kv[0]), reverse=True
    ):
        if known in key or key in known:
            return domain
    guess = f"www.{slugify(cleaned)}mf.com"
    log.warning("No known domain for '%s' — guessing %s", cleaned, guess)
    return guess


def website_to_domain(website: str) -> str:
    """'https://www.dspim.com/x' -> 'dspim.com' (keep non-www subdomains)."""
    netloc = urlparse(website).netloc.lower()
    return netloc.removeprefix("www.")


def parse_member_payload(html: str) -> list[dict]:
    """Extract AMC records from the page's embedded hydration payload."""
    text = html.replace('\\"', '"')
    seen: dict[str, dict] = {}
    for m in PAYLOAD_RECORD_RE.finditer(text):
        seen.setdefault(
            m["mf_id"],
            {
                "mf_id": int(m["mf_id"]),
                "mf_name": m["mf_name"].strip(),
                "amc_name": m["amc_name"].strip(),
                "website": m["website"].strip(),
            },
        )
    return sorted(seen.values(), key=lambda r: r["mf_id"])


def build_records_from_payload(members: list[dict]) -> list[dict]:
    """Seed records from official AMFI payload data — stable ids, real websites."""
    records = []
    for member in members:
        cleaned = clean_name(member["mf_name"])
        domain = ""
        if member["website"].startswith("http"):
            domain = website_to_domain(member["website"])
        if not domain:  # missing or malformed website; fall back to the map
            domain = resolve_domain(cleaned)
        records.append(
            {
                "amc_id": member["mf_id"],
                "firm_name": member["mf_name"],
                "legal_name": member["amc_name"],
                "clean_name": cleaned,
                "base_domain": domain,
            }
        )
    return records


def build_records(firm_names: list[str]) -> list[dict]:
    """Seed records from bare names (fallback paths) — sequential ids."""
    records = []
    for idx, firm in enumerate(firm_names, start=1):
        cleaned = clean_name(firm)
        domain = resolve_domain(cleaned)
        records.append(
            {
                "amc_id": idx,
                "firm_name": firm,
                "legal_name": "",
                "clean_name": cleaned,
                "base_domain": domain,
            }
        )
    return records


# Probed in order after robots.txt. XML preferred; /sitemap and /site-map are
# HTML sitemap pages some AMCs use instead (e.g. hdfcfund.com/sitemap,
# kotakmf.com/site-map) — still a full page inventory for Phase 2.
CANDIDATE_SITEMAP_PATHS = ["/sitemap.xml", "/sitemap_index.xml", "/sitemap", "/site-map"]


async def discover_sitemap(
    client: httpx.AsyncClient, domain: str
) -> tuple[str, str, bool]:
    """Find a site's sitemap: robots.txt directive first, path probes second.

    Returns (sitemap_url, sitemap_type, verified) where type is "xml" or
    "html". Unreachable sites keep the conventional /sitemap.xml guess with
    verified=False so Phase 2 knows to re-probe with a real browser.
    """
    try:
        resp = await client.get(f"https://{domain}/robots.txt")
        if resp.status_code == 200:
            declared = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", resp.text)
            if declared:
                return declared[0], "xml", True
    except httpx.HTTPError:
        pass

    for path in CANDIDATE_SITEMAP_PATHS:
        try:
            resp = await client.get(f"https://{domain}{path}")
        except httpx.HTTPError:
            continue
        # follow_redirects is on: a path that bounces to the homepage is a miss
        if resp.status_code != 200 or "sitemap" not in str(resp.url).replace("-", ""):
            continue
        looks_xml = "xml" in resp.headers.get("content-type", "") or (
            resp.text.lstrip().startswith("<?xml")
        )
        if looks_xml:
            return str(resp.url), "xml", True
        if path in ("/sitemap", "/site-map"):
            return str(resp.url), "html", True
    return f"https://{domain}/sitemap.xml", "xml", False


async def enrich_with_sitemaps(records: list[dict]) -> None:
    """Attach sitemap_url/sitemap_verified to every record, concurrently."""
    semaphore = asyncio.Semaphore(SITEMAP_CONCURRENCY)
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=SITEMAP_TIMEOUT,
        headers={"User-Agent": USER_AGENT},
    ) as client:

        async def probe(record: dict) -> None:
            async with semaphore:
                try:
                    url, kind, verified = await discover_sitemap(
                        client, record["base_domain"]
                    )
                except Exception:
                    url, kind, verified = (
                        f"https://{record['base_domain']}/sitemap.xml",
                        "xml",
                        False,
                    )
                record["sitemap_url"] = url
                record["sitemap_type"] = kind
                record["sitemap_verified"] = verified

        await asyncio.gather(*(probe(r) for r in records))

    found = sum(1 for r in records if r["sitemap_verified"])
    log.info("Sitemaps verified for %d/%d domains", found, len(records))


def parse_member_names(html: str) -> list[str]:
    """Pull AMC names out of the rendered members page.

    Secondary path — used only if the embedded payload extraction comes up
    short. Scans every plausible container for AMC-shaped strings.
    """
    soup = BeautifulSoup(html, "html.parser")

    candidates: list[str] = []
    for tag in soup.find_all(["td", "li", "a", "h3", "h4", "p", "div", "span"]):
        # Leaf-ish nodes only; deep containers repeat all their children's text.
        if tag.find(["td", "li", "div", "p", "table", "ul"]):
            continue
        text = re.sub(r"\s+", " ", tag.get_text(" ", strip=True))
        if not (5 < len(text) < 90):
            continue
        if NON_AMC_PATTERNS.search(text):
            continue
        if re.search(r"mutual fund|asset management", text, re.IGNORECASE):
            candidates.append(text)
    return _dedupe(candidates)


def _dedupe(candidates: list[str]) -> list[str]:
    """Order-preserving dedupe on the cleaned, lowercased name."""
    seen: set[str] = set()
    names: list[str] = []
    for name in candidates:
        key = clean_name(name).lower()
        if key and key not in seen:
            seen.add(key)
            names.append(name)
    return names


async def fetch_members_html() -> str | None:
    """Render the AMFI members page with a real browser and return its HTML."""
    browser_config = BrowserConfig(
        headless=True,
        user_agent=USER_AGENT,
        viewport_width=1366,
        viewport_height=900,
    )
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        wait_for="css:body",
        delay_before_return_html=4.0,  # let the members tab finish re-rendering
        page_timeout=60_000,
    )
    try:
        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url=AMFI_MEMBERS_URL, config=run_config)
        if not result.success:
            log.error("Crawl failed: %s", result.error_message)
            return None
        return result.html
    except Exception:
        log.exception("Crawler raised while fetching %s", AMFI_MEMBERS_URL)
        return None


async def main() -> int:
    log.info("Fetching AMFI members directory: %s", AMFI_MEMBERS_URL)
    html = await fetch_members_html()

    records: list[dict] = []
    source = "live_payload"
    if html:
        try:
            members = parse_member_payload(html)
            if len(members) >= 20:  # sane roster is ~50
                log.info("Payload extraction yielded %d AMC records", len(members))
                records = build_records_from_payload(members)
        except Exception:
            log.exception("Payload extraction failed")

    if not records and html:
        try:
            names = parse_member_names(html)
            if len(names) >= 20:
                log.info("DOM text scan yielded %d AMC names", len(names))
                records = build_records(names)
                source = "live_dom_scan"
        except Exception:
            log.exception("Parsing members page failed")

    if not records:
        log.warning(
            "Live scrape unusable — using embedded static roster (%d AMCs)",
            len(STATIC_AMC_NAMES),
        )
        records = build_records(STATIC_AMC_NAMES)
        source = "static_fallback"

    log.info("Probing %d domains for sitemaps...", len(records))
    await enrich_with_sitemaps(records)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log.info("Wrote %d records to %s (source: %s)", len(records), OUTPUT_PATH, source)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
