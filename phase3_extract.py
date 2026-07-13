"""MF-Engine — Phase 3: extract fund managers to CSV.

Reads data/amc_page_inventory.json, crawls each AMC's team/management pages
(discovered in Phase 2), and pulls fund-manager rows — name, designation,
email, location — into data/fund_managers.csv.

Heuristic extraction only: no LLM, no GPU. Manager names are found next to
designation labels ("Fund Manager", "CIO", …); emails via regex; location via
an Indian-city match near office/address context. Layouts vary per AMC, so
this is best-effort — a later LLM pass (Qwen on vLLM) can refine it.

Usage:
    python phase3_extract.py
"""

import asyncio
import csv
import json
import logging
import re
import sys
from pathlib import Path

from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("mf-engine.extract")

INVENTORY_PATH = Path("data/amc_page_inventory.json")
OUTPUT_CSV = Path("data/fund_managers.csv")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
PAGE_CONCURRENCY = 4
MAX_TEAM_PAGES_PER_AMC = 8

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Team-classified URLs that are really blog/article/PR pages — their titles and
# bylines produce fake "names". Skip them; keep genuine people pages.
ARTICLE_PATH_RE = re.compile(
    r"knowledge|blog|article|perspective|thought-?leadership|leadership-?corner"
    r"|insight|news|media|podcast|video|story|stories|/mf-|research/|learn",
    re.IGNORECASE,
)

# A person's name: optional honorific, then 2–4 tokens where each token is a
# full capitalised word (>=2 letters) or a single initial ("B", "B."), with at
# least two full words overall (enforced in looks_like_name). Full words avoid
# the truncation that a lone optional letter caused ("Deshpande" -> "De").
NAME_TOKEN = r"(?:[A-Z][a-z]{1,}|[A-Z]\.?)"
NAME_RE = re.compile(
    r"(?:(?:Mr|Ms|Mrs|Dr)\.?\s+)?"
    rf"({NAME_TOKEN}(?:\s+{NAME_TOKEN}){{1,3}})"
)

# Words that are never part of a person's name — headings, roles, business
# lines. If a candidate contains any of these it is rejected outright.
NON_NAME_WORDS = {
    "fund", "funds", "manager", "managers", "management", "chief", "investment",
    "officer", "portfolio", "managing", "director", "directors", "board",
    "trustee", "trustees", "team", "head", "equity", "equities", "debt",
    "fixed", "income", "research", "analyst", "credit", "private", "real",
    "assets", "asset", "renewable", "energy", "economist", "potential", "risk",
    "the", "our", "key", "personnel", "co", "senior", "associate", "assistant",
    "mutual", "capital", "wealth", "markets", "market", "leadership", "read",
    "more", "of", "and", "solutions", "advisory", "services", "limited",
    "business", "alternate", "form", "error", "knowledge", "hub", "contact",
    "about", "home", "login", "register", "download", "factsheet", "scheme",
    "schemes", "details", "disclosure", "disclosures", "policy", "policies",
    "statutory", "faq", "media", "video", "videos", "blog", "blogs", "podcast",
    "news", "notice", "careers", "sitemap", "overview", "profile", "corporate",
}

# Roles that mark a fund manager (not admin/support staff).
DESIGNATION_RE = re.compile(
    r"\b(?:Senior\s+|Associate\s+|Assistant\s+|Co-?)?"
    r"(?:Fund\s+Manager|Portfolio\s+Manager"
    r"|Chief\s+Investment\s+Officer|CIO"
    r"|Head\s+(?:of\s+)?(?:Equity|Fixed\s+Income|Debt|Research)"
    r"|Equity\s+Analyst\s+and\s+Fund\s+Manager)\b",
    re.IGNORECASE,
)

# Indian cities where AMCs are typically headquartered.
CITY_RE = re.compile(
    r"\b(Mumbai|Navi\s+Mumbai|New\s+Delhi|Delhi|Gurugram|Gurgaon|Bengaluru"
    r"|Bangalore|Chennai|Kolkata|Hyderabad|Pune|Ahmedabad|Noida)\b",
    re.IGNORECASE,
)
# Prefer city mentions near an address/office cue.
OFFICE_CUE_RE = re.compile(
    r"registered\s+office|corporate\s+office|head\s+office|address", re.IGNORECASE
)

# Emails that are clearly org-level, not a person.
GENERIC_EMAIL_RE = re.compile(
    r"^(?:info|contact|care|service|support|invest|help|customer|feedback"
    r"|complianc|grievance|webmaster|admin|enquiry|query)",
    re.IGNORECASE,
)


def clean_ws(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text).strip()


def find_location(text: str) -> str:
    """Best-effort HQ city: prefer a city near an office/address cue."""
    for m in OFFICE_CUE_RE.finditer(text):
        window = text[m.start() : m.start() + 300]
        city = CITY_RE.search(window)
        if city:
            return clean_ws(city.group(1)).title()
    city = CITY_RE.search(text)
    return clean_ws(city.group(1)).title() if city else ""


def looks_like_name(candidate: str) -> bool:
    """A real person name: 2–4 tokens, no role/heading words, >=2 full words."""
    if not (4 < len(candidate) < 45):
        return False
    tokens = candidate.split()
    if not (2 <= len(tokens) <= 4):
        return False
    if any(t.lower().strip(".") in NON_NAME_WORDS for t in tokens):
        return False
    full_words = [t for t in tokens if len(t.strip(".")) >= 2 and "." not in t]
    return len(full_words) >= 2


def extract_managers(text: str) -> list[tuple[str, str]]:
    """Pull (name, designation) pairs by pairing designation lines with the
    nearest name on the same or the preceding line."""
    lines = [clean_ws(l) for l in text.splitlines()]
    lines = [l for l in lines if l]
    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    for i, line in enumerate(lines):
        dmatch = DESIGNATION_RE.search(line)
        if not dmatch:
            continue
        designation = clean_ws(dmatch.group(0))

        # Search the designation line first, then the line above (common layout:
        # name on its own line, title beneath).
        name = ""
        for probe in (line, lines[i - 1] if i > 0 else ""):
            for nm in NAME_RE.finditer(probe):
                cand = clean_ws(nm.group(1))
                if looks_like_name(cand):
                    name = cand
                    break
            if name:
                break
        if not name:
            continue

        key = name.lower()
        if key not in seen:
            seen.add(key)
            found.append((name, designation))
    return found


def page_emails(text: str) -> tuple[str, list[str]]:
    """Return (best_personal_email, all_emails). Personal = non-generic local part."""
    emails: list[str] = []
    for e in EMAIL_RE.findall(text):
        e = e.lower().rstrip(".")
        if e not in emails and not e.endswith((".png", ".jpg", ".svg", ".gif")):
            emails.append(e)
    personal = next(
        (e for e in emails if not GENERIC_EMAIL_RE.match(e.split("@", 1)[0])), ""
    )
    return personal, emails


async def crawl_text(crawler: AsyncWebCrawler, url: str) -> str | None:
    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        delay_before_return_html=1.5,
        page_timeout=45_000,
        magic=True,
        override_navigator=True,
    )
    try:
        result = await crawler.arun(url=url, config=config)
        if result.success:
            # markdown keeps line structure that name/title pairing relies on
            return result.markdown or result.cleaned_html or result.html
    except Exception:
        log.debug("crawl failed: %s", url)
    return None


async def main() -> int:
    if not INVENTORY_PATH.exists():
        log.error("Inventory missing — run phase2_discover.py first (%s)", INVENTORY_PATH)
        return 1
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))

    targets = []
    for rec in inventory:
        urls = [u for u in rec.get("team_urls", []) if not ARTICLE_PATH_RE.search(u)]
        if urls:
            targets.append((rec, urls[:MAX_TEAM_PAGES_PER_AMC]))
    total_pages = sum(len(urls) for _, urls in targets)
    log.info(
        "Extracting from %d AMCs with team pages (%d pages)", len(targets), total_pages
    )

    rows: list[dict] = []
    sem = asyncio.Semaphore(PAGE_CONCURRENCY)
    browser_config = BrowserConfig(
        headless=True, user_agent=USER_AGENT, enable_stealth=True
    )

    async with AsyncWebCrawler(config=browser_config) as crawler:

        async def handle(rec: dict, url: str) -> None:
            async with sem:
                text = await crawl_text(crawler, url)
            if not text:
                return
            managers = extract_managers(text)
            personal, all_emails = page_emails(text)
            location = find_location(text)
            # Prefer a personal (non-generic) email; only fall back to an
            # on-domain generic (service@/info@) when no personal one exists.
            on_domain = next(
                (e for e in all_emails if rec["base_domain"].split(".")[0] in e), ""
            )
            page_email = personal or on_domain
            for name, designation in managers:
                rows.append(
                    {
                        "firm_name": rec["firm_name"],
                        "manager_name": name,
                        "designation": designation,
                        "email": page_email,
                        "location": location,
                        "source_url": url,
                    }
                )
            if managers:
                log.info(
                    "%-38s %2d managers  %-11s %s",
                    rec["firm_name"][:38],
                    len(managers),
                    location or "-",
                    url[:60],
                )

        await asyncio.gather(
            *(handle(rec, url) for rec, urls in targets for url in urls)
        )

    # Dedupe on (firm, manager); keep the row that has an email if any.
    best: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row["firm_name"], row["manager_name"].lower())
        if key not in best or (row["email"] and not best[key]["email"]):
            best[key] = row
    final = sorted(best.values(), key=lambda r: (r["firm_name"], r["manager_name"]))

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "firm_name", "manager_name", "designation",
                "email", "location", "source_url",
            ],
        )
        writer.writeheader()
        writer.writerows(final)

    firms = len({r["firm_name"] for r in final})
    with_email = sum(1 for r in final if r["email"])
    log.info(
        "Wrote %d managers across %d AMCs to %s (%d with an email)",
        len(final),
        firms,
        OUTPUT_CSV,
        with_email,
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
