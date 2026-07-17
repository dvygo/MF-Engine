"""MF-Engine — SEBI registered intermediaries scraper (standalone).

Scrapes SEBI's official registered-intermediary directories — the *regulator's*
lists, complementary to the AMFI members roster the main pipeline seeds from.
Covers the broader Indian wealth-management universe, not just mutual funds:

    mutual-funds          ~59 AMCs       (intmId 23)
    portfolio-managers   ~526 PMS firms  (intmId 33)
    aif                 ~1989 funds      (intmId 16)
    investment-advisers ~1044 RIAs       (intmId 13)
    research-analysts                    (intmId 14)
    merchant-bankers                     (intmId 9)

Each record carries name, SEBI registration number, registered address
(city/state parsed out), and registration/validity date — fields the industry
bodies don't publish.

Every directory paginates via the AJAX call its own `searchFormFpi()` makes to
`getintmfpiinfo.jsp`, POSTing `intmId` + `doDirect=<page-1>` (0-based) and
returning an HTML fragment of ~25 records. No token or browser needed.

Output: data/sebi_<type>.json (one file per type)

Usage:
    python src/sebi_intermediaries.py                       # wealth-manager set
    python src/sebi_intermediaries.py mutual-funds aif      # specific types
    python src/sebi_intermediaries.py --all                 # every known type
"""

import asyncio
import json
import logging
import re
import sys
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("mf-engine.sebi")
logging.getLogger("httpx").setLevel(logging.WARNING)

AJAX_URL = "https://www.sebi.gov.in/sebiweb/ajax/other/getintmfpiinfo.jsp"
REFERER_TMPL = (
    "https://www.sebi.gov.in/sebiweb/other/OtherAction.do"
    "?doRecognisedFpi=yes&intmId={intm_id}"
)
DATA_DIR = Path("data")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# SEBI intermediary types, by the intmId their directory URL uses.
TYPES: dict[str, int] = {
    "mutual-funds": 23,
    "portfolio-managers": 33,
    "aif": 16,
    "investment-advisers": 13,
    "research-analysts": 14,
    "merchant-bankers": 9,
}
# The wealth-management universe — the default set.
DEFAULT_TYPES = ["mutual-funds", "portfolio-managers", "aif", "investment-advisers"]

MAX_PAGES = 200  # safety bound; AIF is the largest at ~80 pages of 25
RETRIES = 4  # SEBI drops connections under rapid requests
PAGE_DELAY = 1.0  # be gentle between pages


def page_form(intm_id: int, page_index: int) -> dict:
    """POST body searchFormFpi() sends; doDirect is the 0-based page index."""
    return {
        "nextValue": "1",
        "next": "n",
        "intmId": str(intm_id),
        "contPer": "",
        "name": "",
        "regNo": "",
        "email": "",
        "location": "",
        "exchange": "",
        "affiliate": "",
        "alp": "",
        "doDirect": str(page_index),
        "intmIds": "",
    }


def parse_records(html: str) -> list[dict]:
    """Group SEBI card-view label/value blocks into one record per firm."""
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find(id="ajax_cat") or soup
    records: list[dict] = []
    current: dict | None = None
    for card in container.select("div.card-view"):
        parts = [p for p in card.get_text("||", strip=True).split("||") if p]
        if len(parts) < 2:
            continue
        label = parts[0].lower()
        value = " ".join(parts[1:]).strip()
        if label.startswith("name"):
            current = {"name": value, "reg_no": "", "address": "", "validity": ""}
            records.append(current)
        elif current is not None:
            if "regist" in label:
                current["reg_no"] = value
            elif "address" in label:
                current["address"] = value
            elif "valid" in label:
                current["validity"] = value
    return [r for r in records if r["reg_no"]]


def total_records(html: str) -> int:
    """'1 to 25 of 526 records' -> 526, else 0."""
    m = re.search(r"of\s+([\d,]+)\s+records", html, re.IGNORECASE)
    return int(m.group(1).replace(",", "")) if m else 0


def city_state(address: str) -> tuple[str, str]:
    """Best-effort (city, state) from a SEBI address tail: '..., CITY, STATE, PIN'."""
    tokens = [t.strip() for t in address.split(",") if t.strip()]
    tokens = [t for t in tokens if not re.fullmatch(r"\d{6}", t)]  # drop PIN
    if len(tokens) >= 2:
        return tokens[-2].title(), tokens[-1].title()
    return "", ""


async def fetch_page(client: httpx.AsyncClient, intm_id: int, page_index: int) -> str:
    """POST the AJAX endpoint for one page, retrying flaky disconnects."""
    for attempt in range(RETRIES):
        try:
            resp = await client.post(
                AJAX_URL,
                data=page_form(intm_id, page_index),
                headers={"Referer": REFERER_TMPL.format(intm_id=intm_id)},
            )
            if resp.status_code == 200 and resp.text:
                return resp.text
        except httpx.HTTPError:
            pass
        await asyncio.sleep(1.5 * (attempt + 1))
    log.warning("intmId=%d page %d failed after %d retries", intm_id, page_index, RETRIES)
    return ""


async def scrape_type(client: httpx.AsyncClient, slug: str) -> list[dict]:
    """All records for one intermediary type, paged until exhausted."""
    intm_id = TYPES[slug]
    seen: set[str] = set()
    records: list[dict] = []
    expected = 0

    for page_index in range(MAX_PAGES):
        html = await fetch_page(client, intm_id, page_index)
        if not html:
            break
        if page_index == 0:
            expected = total_records(html)
            log.info("%s (intmId=%d): %d records listed", slug, intm_id, expected)
        new = [r for r in parse_records(html) if r["reg_no"] not in seen]
        for r in new:
            seen.add(r["reg_no"])
            r["city"], r["state"] = city_state(r["address"])
            r["sebi_type"] = slug
            records.append(r)
        if not new:  # pager wrapped or ran out
            break
        if page_index % 10 == 0:
            log.info("  %s: %d/%s collected", slug, len(records), expected or "?")
        if expected and len(records) >= expected:
            break
        await asyncio.sleep(PAGE_DELAY)

    records.sort(key=lambda r: r["name"].lower())
    for i, r in enumerate(records, start=1):
        r["sebi_id"] = i
    return records


async def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if "--all" in sys.argv:
        slugs = list(TYPES)
    elif args:
        slugs = args
    else:
        slugs = DEFAULT_TYPES

    unknown = [s for s in slugs if s not in TYPES]
    if unknown:
        log.error("Unknown type(s): %s — known: %s", ", ".join(unknown), ", ".join(TYPES))
        return 1

    log.info("Scraping SEBI intermediaries: %s", ", ".join(slugs))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    grand_total = 0

    async with httpx.AsyncClient(
        timeout=25.0,
        headers={
            "User-Agent": USER_AGENT,
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    ) as client:
        for slug in slugs:
            records = await scrape_type(client, slug)
            if not records:
                log.error(
                    "%s: no records parsed — endpoint/structure may have changed", slug
                )
                continue
            out = DATA_DIR / f"sebi_{slug.replace('-', '_')}.json"
            out.write_text(
                json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            grand_total += len(records)
            log.info("Wrote %d %s to %s", len(records), slug, out)

    log.info("Done — %d records across %d type(s)", grand_total, len(slugs))
    return 0 if grand_total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
