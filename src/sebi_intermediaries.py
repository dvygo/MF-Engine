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
import csv
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
CSV_DIR = DATA_DIR / "csv"

# Column order for the CSV exports.
CSV_COLUMNS = [
    "sebi_id", "name", "reg_no", "category", "contact_person", "email",
    "telephone", "fax", "website", "domain", "pincode", "city", "state",
    "address", "correspondence_address", "validity", "sebi_type",
]

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


# SEBI publishes far more per firm than name/address — contact details and a
# website are right there in the directory. Map its labels to record keys.
FIELD_MAP = {
    "name": "name",
    "registration no.": "reg_no",
    "e-mail": "email",
    "telephone": "telephone",
    "fax no.": "fax",
    "website": "website",
    "contact person": "contact_person",
    "address": "address",
    "correspondence address": "correspondence_address",
    "validity": "validity",
}
RECORD_FIELDS = [
    "name", "reg_no", "contact_person", "email", "telephone", "fax",
    "website", "address", "correspondence_address", "validity",
]


def parse_records(html: str) -> list[dict]:
    """Group SEBI card-view label/value blocks into one record per firm.

    A new record starts at each 'Name' label; every subsequent label until the
    next 'Name' belongs to it. Fields are optional — SEBI leaves e-mail,
    website, phone etc. blank for some firms.
    """
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find(id="ajax_cat") or soup
    records: list[dict] = []
    current: dict | None = None
    for card in container.select("div.card-view"):
        parts = [p for p in card.get_text("||", strip=True).split("||") if p]
        if len(parts) < 2:
            continue
        label = parts[0].strip().lower()
        value = " ".join(parts[1:]).strip()
        key = FIELD_MAP.get(label)
        if key == "name":
            current = {f: "" for f in RECORD_FIELDS}
            current["name"] = value
            records.append(current)
        elif current is not None and key:
            current[key] = value
    return [r for r in records if r["reg_no"]]


def total_records(html: str) -> int:
    """'1 to 25 of 526 records' -> 526, else 0."""
    m = re.search(r"of\s+([\d,]+)\s+records", html, re.IGNORECASE)
    return int(m.group(1).replace(",", "")) if m else 0


def extract_pincode(address: str) -> str:
    """The 6-digit PIN from a SEBI address — the join key into data/pincodes.json.

    Indian PINs never start with 0, which rules out phone fragments and years.
    Takes the last match, since the PIN sits at the end of the address.
    """
    hits = re.findall(r"\b[1-9]\d{5}\b", address)
    return hits[-1] if hits else ""


def city_state(address: str) -> tuple[str, str]:
    """Best-effort (city, state) from a SEBI address tail: '..., CITY, STATE, PIN'."""
    tokens = [t.strip() for t in address.split(",") if t.strip()]
    tokens = [t for t in tokens if not re.fullmatch(r"\d{6}", t)]  # drop PIN
    if len(tokens) >= 2:
        return tokens[-2].title(), tokens[-1].title()
    return "", ""


def website_domain(website: str) -> str:
    """Bare domain from SEBI's free-text website field ('www.x.com', 'http://x.com')."""
    site = website.strip().lower()
    if not site or "@" in site:  # some rows put an email here
        return ""
    site = re.sub(r"^https?://", "", site)
    site = site.split("/")[0].split()[0] if site else ""
    return site.removeprefix("www.")


def aif_category(reg_no: str) -> str:
    """AIF registration numbers encode the category: IN/AIF1|2|3/... -> I/II/III."""
    m = re.search(r"/AIF([123])/", reg_no, re.IGNORECASE)
    return {"1": "Category I", "2": "Category II", "3": "Category III"}.get(
        m.group(1) if m else "", ""
    )


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
            # Take city, state and PIN from ONE address. The correspondence
            # address is the operational one where SEBI lists it; otherwise the
            # registered office. Mixing them yields records like
            # pincode=400063 (Mumbai) with city='New Delhi'.
            located = r["correspondence_address"] or r["address"]
            if not extract_pincode(located):  # unusable — fall back
                located = r["address"] or r["correspondence_address"]
            r["located_address"] = located
            r["city"], r["state"] = city_state(located)
            r["pincode"] = extract_pincode(located)
            r["domain"] = website_domain(r["website"])
            r["category"] = aif_category(r["reg_no"]) if slug == "aif" else ""
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


def write_csv(path: Path, records: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


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
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    grand_total = 0
    combined: list[dict] = []

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
            stem = f"sebi_{slug.replace('-', '_')}"
            out = DATA_DIR / f"{stem}.json"
            out.write_text(
                json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            write_csv(CSV_DIR / f"{stem}.csv", records)
            combined.extend(records)
            grand_total += len(records)
            with_site = sum(1 for r in records if r["domain"])
            with_mail = sum(1 for r in records if r["email"])
            log.info(
                "Wrote %d %s — %d with website, %d with e-mail (%s, %s)",
                len(records), slug, with_site, with_mail, out, CSV_DIR / f"{stem}.csv",
            )

    if combined:
        # One roll-up of every wealth manager scraped this run.
        write_csv(CSV_DIR / "wealth_managers.csv", combined)
        log.info("Wrote %d rows to %s", len(combined), CSV_DIR / "wealth_managers.csv")

    log.info("Done — %d records across %d type(s)", grand_total, len(slugs))
    return 0 if grand_total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
