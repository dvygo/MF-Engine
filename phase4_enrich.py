"""MF-Engine — Phase 4: enrich fund managers with LinkedIn + email.

Reads data/fund_managers.csv (Phase 3) and adds, per manager:
  - linkedin_url : profile URL discovered via a Bing search (stored, never
                   scraped — LinkedIn hard-walls bots and hides emails anyway)
  - email        : a *verified* address only — kept from the AMC page if
                   Phase 3 found one, else Hunter.io (if HUNTER_API_KEY set),
                   else SMTP-verified (if VERIFY_SMTP=1)
  - email_guess  : best-effort corporate pattern (first.last@domain). Clearly
                   separate from `email` — a guess, not asserted fact.

Search: SerpAPI (Bing engine) when SERPAPI_KEY is set — reliable JSON, free
tier ~100/mo. Otherwise falls back to scraping Bing through Crawl4AI's stealth
Chromium, which is best-effort: the free endpoint throttles after ~20-30
queries (result pages thin out, LinkedIn hits vanish), so scrape mode won't
cover a full roster in one run. Either way only the discovered profile URL is
stored — no LinkedIn page is ever fetched.

Output: data/fund_managers_enriched.csv

Env:
  SERPAPI_KEY      use SerpAPI (Bing) for reliable LinkedIn discovery
  HUNTER_API_KEY   use Hunter.io email-finder for verified emails
  VERIFY_SMTP=1    attempt SMTP RCPT verification of guessed emails (slow,
                   often blocked by corporate mail servers; needs dnspython)
  MAX_MANAGERS=N   cap rows processed (testing)

Usage:
    python phase4_enrich.py
"""

import asyncio
import csv
import logging
import os
import random
import re
import sys
from pathlib import Path
from urllib.parse import quote_plus, urlparse

import httpx
from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("mf-engine.enrich")
logging.getLogger("httpx").setLevel(logging.WARNING)

INPUT_CSV = Path("data/fund_managers.csv")
OUTPUT_CSV = Path("data/fund_managers_enriched.csv")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
# Bing throttles bursts (results thin out, then vanish). Search serially with
# a jittered delay between queries to keep full result pages coming back.
SEARCH_DELAY_RANGE = (3.0, 5.5)
LINKEDIN_RE = re.compile(
    r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[A-Za-z0-9\-_%]+", re.IGNORECASE
)

SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")
HUNTER_API_KEY = os.environ.get("HUNTER_API_KEY", "")
VERIFY_SMTP = os.environ.get("VERIFY_SMTP") == "1"
MAX_MANAGERS = int(os.environ.get("MAX_MANAGERS", "0"))


def name_parts(full: str) -> tuple[str, str]:
    """First and last token of a name, initials/honorifics dropped."""
    tokens = [t.strip(".") for t in full.split() if t.strip(".")]
    tokens = [t for t in tokens if t.lower() not in {"mr", "ms", "mrs", "dr"}]
    words = [t for t in tokens if len(t) > 1] or tokens
    if not words:
        return "", ""
    return words[0].lower(), words[-1].lower()


def domain_of(source_url: str) -> str:
    return urlparse(source_url).netloc.lower().removeprefix("www.")


def email_candidates(first: str, last: str, domain: str) -> list[str]:
    """Common corporate email patterns, most-likely first."""
    if not (first and last and domain):
        return []
    f, l = first, last
    return [
        f"{f}.{l}@{domain}",
        f"{f}{l}@{domain}",
        f"{f[0]}{l}@{domain}",
        f"{f}_{l}@{domain}",
        f"{f}@{domain}",
        f"{l}.{f}@{domain}",
    ]


def firm_for_query(firm: str) -> str:
    """Trim 'Mutual Fund' — managers' profiles name the AMC/asset arm, not the
    fund brand ('360 ONE Asset', not '360 ONE Mutual Fund')."""
    return re.sub(r"\s*mutual\s+fund\s*$", "", firm, flags=re.IGNORECASE).strip()


async def _bing_once(crawler: AsyncWebCrawler, query: str) -> str:
    url = f"https://www.bing.com/search?q={quote_plus(query)}"
    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        delay_before_return_html=2.0,
        page_timeout=45_000,
        magic=True,
        override_navigator=True,
    )
    try:
        result = await crawler.arun(url=url, config=config)
        if result.success and result.html:
            hits = LINKEDIN_RE.findall(result.html)
            if hits:
                return hits[0].split("?")[0]
    except Exception:
        log.debug("bing search failed: %s", query)
    return ""


async def serpapi_linkedin(
    client: httpx.AsyncClient, query: str
) -> tuple[str, bool]:
    """(profile_url, api_used). Reliable when SERPAPI_KEY is set."""
    if not SERPAPI_KEY:
        return "", False
    try:
        resp = await client.get(
            "https://serpapi.com/search",
            params={"engine": "bing", "q": query, "api_key": SERPAPI_KEY},
        )
        blob = resp.text
        hits = LINKEDIN_RE.findall(blob)
        return (hits[0].split("?")[0] if hits else ""), True
    except Exception:
        log.debug("serpapi failed: %s", query)
        return "", True


async def find_linkedin(
    crawler: AsyncWebCrawler, client: httpx.AsyncClient, name: str, firm: str
) -> str:
    """Profile URL via SerpAPI (if keyed) else best-effort Bing scrape. Stored
    only, never scraped. One scrape retry after a pause — a thin (throttled)
    page yields nothing."""
    query = f"{name} {firm_for_query(firm)} linkedin"
    hit, api_used = await serpapi_linkedin(client, query)
    if api_used:
        return hit
    hit = await _bing_once(crawler, query)
    if not hit:
        await asyncio.sleep(random.uniform(6.0, 9.0))
        hit = await _bing_once(crawler, query)
    return hit


async def hunter_email(
    client: httpx.AsyncClient, first: str, last: str, domain: str
) -> tuple[str, str]:
    """(email, confidence) from Hunter.io, or ('', '') if unavailable."""
    if not (HUNTER_API_KEY and first and last and domain):
        return "", ""
    try:
        resp = await client.get(
            "https://api.hunter.io/v2/email-finder",
            params={
                "domain": domain,
                "first_name": first,
                "last_name": last,
                "api_key": HUNTER_API_KEY,
            },
        )
        data = resp.json().get("data", {})
        if data.get("email"):
            return data["email"], f"hunter:{data.get('score', '?')}"
    except Exception:
        log.debug("hunter lookup failed for %s.%s@%s", first, last, domain)
    return "", ""


def smtp_verify(candidates: list[str]) -> str:
    """Return the first candidate an MX server accepts (RCPT 250). Best-effort:
    many corporate servers block probes or accept everything (catch-all)."""
    if not candidates:
        return ""
    try:
        import smtplib

        import dns.resolver
    except ImportError:
        return ""
    domain = candidates[0].split("@", 1)[1]
    try:
        mx = sorted(
            dns.resolver.resolve(domain, "MX"),
            key=lambda r: r.preference,
        )[0].exchange.to_text()
    except Exception:
        return ""
    try:
        server = smtplib.SMTP(mx, 25, timeout=8)
        server.helo("mf-engine.local")
        server.mail("verify@mf-engine.local")
        # catch-all guard: if a random address is accepted, RCPT proves nothing
        rc, _ = server.rcpt(f"zzq-nonexistent-9182@{domain}")
        catch_all = rc in (250, 251)
        hit = ""
        if not catch_all:
            for cand in candidates:
                code, _ = server.rcpt(cand)
                if code in (250, 251):
                    hit = cand
                    break
        server.quit()
        return hit
    except Exception:
        return ""


async def main() -> int:
    if not INPUT_CSV.exists():
        log.error("Input missing — run phase3_extract.py first (%s)", INPUT_CSV)
        return 1
    rows = list(csv.DictReader(INPUT_CSV.open(encoding="utf-8")))
    if MAX_MANAGERS:
        rows = rows[:MAX_MANAGERS]
    log.info(
        "Enriching %d managers | hunter=%s smtp_verify=%s",
        len(rows),
        bool(HUNTER_API_KEY),
        VERIFY_SMTP,
    )

    browser_config = BrowserConfig(
        headless=True, user_agent=USER_AGENT, enable_stealth=True
    )

    async with AsyncWebCrawler(config=browser_config) as crawler:
        async with httpx.AsyncClient(
            timeout=15.0, headers={"User-Agent": USER_AGENT}
        ) as client:

            async def enrich(row: dict) -> None:
                name = row["manager_name"]
                firm = row["firm_name"]
                first, last = name_parts(name)
                domain = domain_of(row.get("source_url", ""))

                linkedin = await find_linkedin(crawler, client, name, firm)

                guesses = email_candidates(first, last, domain)
                row["email_guess"] = guesses[0] if guesses else ""

                verified = row.get("email", "")  # kept from the AMC page
                source = "amc_page" if verified else ""
                if not verified:
                    verified, source = await hunter_email(client, first, last, domain)
                if not verified and VERIFY_SMTP:
                    hit = await asyncio.to_thread(smtp_verify, guesses)
                    if hit:
                        verified, source = hit, "smtp"

                row["email"] = verified
                row["email_source"] = source
                row["linkedin_url"] = linkedin
                log.info(
                    "%-26s %-22s li=%-3s email=%s",
                    firm[:26],
                    name[:22],
                    "yes" if linkedin else "no",
                    verified or ("guess:" + row["email_guess"] if row["email_guess"] else "-"),
                )

            # Serial with jittered delay when scraping (Bing throttles bursts);
            # no delay needed when SerpAPI serves the search.
            for i, row in enumerate(rows):
                await enrich(row)
                if not SERPAPI_KEY and i + 1 < len(rows):
                    await asyncio.sleep(random.uniform(*SEARCH_DELAY_RANGE))

    fields = [
        "firm_name", "manager_name", "designation", "location",
        "email", "email_source", "email_guess", "linkedin_url", "source_url",
    ]
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    li = sum(1 for r in rows if r.get("linkedin_url"))
    em = sum(1 for r in rows if r.get("email"))
    log.info(
        "Wrote %s — %d/%d with LinkedIn, %d with a verified email",
        OUTPUT_CSV,
        li,
        len(rows),
        em,
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
