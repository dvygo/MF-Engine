"""MF-Engine — build a searchable Indian pincode reference.

Downloads the GeoNames India postal-code export (free, CC-BY 4.0, no key) and
turns it into a location lookup keyed by pincode, tagged for search.

    https://download.geonames.org/export/zip/IN.zip   (~155k rows)

GeoNames columns (see its readme.txt):
    country, postal_code, place_name, admin1(state), code1,
    admin2(district), code2, admin3(taluk), code3, lat, lon, accuracy

One pincode covers several places, so rows are grouped: each pincode gets its
list of place names, its district/taluk/state, and a mean lat/lon. Every known
name plus its aliases are flattened into `search_tags` — a lowercase blob you
can substring-match, so "bangalore" finds a firm GeoNames files under
"Bengaluru", and vice versa.

Output:
    data/pincodes.json      pincode -> location record
    data/csv/pincodes.csv   same, flat

Usage:
    python src/geo_pincodes.py
"""

import csv
import io
import json
import logging
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("mf-engine.geo")
logging.getLogger("httpx").setLevel(logging.WARNING)

GEONAMES_URL = "https://download.geonames.org/export/zip/IN.zip"
DATA_DIR = Path("data")
CSV_DIR = DATA_DIR / "csv"
OUTPUT_JSON = DATA_DIR / "pincodes.json"
OUTPUT_CSV = CSV_DIR / "pincodes.csv"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Indian cities that renamed — datasets, websites and users all use both forms.
# Matching either spelling must find the same place, so both go in search_tags.
CITY_ALIASES: dict[str, list[str]] = {
    "bengaluru": ["bangalore"],
    "mumbai": ["bombay"],
    "kolkata": ["calcutta"],
    "chennai": ["madras"],
    "gurugram": ["gurgaon"],
    "puducherry": ["pondicherry"],
    "vadodara": ["baroda"],
    "kochi": ["cochin"],
    "thiruvananthapuram": ["trivandrum"],
    "prayagraj": ["allahabad"],
    "varanasi": ["banaras", "benares"],
    "mysuru": ["mysore"],
    "mangaluru": ["mangalore"],
    "hubballi": ["hubli"],
    "belagavi": ["belgaum"],
    "kalaburagi": ["gulbarga"],
    "shivamogga": ["shimoga"],
    "tiruchirappalli": ["trichy"],
    "thoothukudi": ["tuticorin"],
    "kanpur": ["cawnpore"],
    "ujjain": ["ujain"],
    "panaji": ["panjim"],
    "shimla": ["simla"],
    "odisha": ["orissa"],
    "uttarakhand": ["uttaranchal"],
}
# Reverse direction too, so the old name resolves to the new one's tags.
ALIAS_LOOKUP: dict[str, list[str]] = {}
for canonical, olds in CITY_ALIASES.items():
    ALIAS_LOOKUP.setdefault(canonical, []).extend(olds)
    for old in olds:
        ALIAS_LOOKUP.setdefault(old, []).append(canonical)

CSV_COLUMNS = [
    "pincode", "district", "taluk", "state", "places",
    "latitude", "longitude", "search_tags",
]


def expand_aliases(names: set[str]) -> set[str]:
    """Add every known alias of every name (both rename directions)."""
    out = set(names)
    for name in list(names):
        out.update(ALIAS_LOOKUP.get(name.strip().lower(), []))
    return out


def download_geonames() -> list[list[str]]:
    log.info("Downloading GeoNames India postal codes: %s", GEONAMES_URL)
    resp = httpx.get(
        GEONAMES_URL, headers={"User-Agent": USER_AGENT}, timeout=90, follow_redirects=True
    )
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        text = z.read("IN.txt").decode("utf-8")
    rows = [line.split("\t") for line in text.strip().split("\n") if line.strip()]
    log.info("Fetched %d GeoNames rows", len(rows))
    return rows


def build_records(rows: list[list[str]]) -> list[dict]:
    """Group GeoNames rows by pincode into one searchable record each."""
    grouped: dict[str, list[list[str]]] = defaultdict(list)
    for r in rows:
        if len(r) >= 11 and r[1].strip():
            grouped[r[1].strip()].append(r)

    records: list[dict] = []
    for pincode, group in grouped.items():
        places = sorted({r[2].strip() for r in group if r[2].strip()})
        districts = sorted({r[5].strip() for r in group if len(r) > 5 and r[5].strip()})
        taluks = sorted({r[7].strip() for r in group if len(r) > 7 and r[7].strip()})
        states = sorted({r[3].strip() for r in group if r[3].strip()})

        lats = [float(r[9]) for r in group if r[9].strip()]
        lons = [float(r[10]) for r in group if r[10].strip()]

        tags = expand_aliases({*places, *districts, *taluks, *states, pincode})
        records.append(
            {
                "pincode": pincode,
                "district": districts[0] if districts else "",
                "taluk": taluks[0] if taluks else "",
                "state": states[0] if states else "",
                "places": places,
                "latitude": round(sum(lats) / len(lats), 5) if lats else None,
                "longitude": round(sum(lons) / len(lons), 5) if lons else None,
                # lowercase, de-duplicated blob for plain substring search
                "search_tags": sorted({t.lower() for t in tags if t}),
            }
        )
    records.sort(key=lambda r: r["pincode"])
    return records


def main() -> int:
    try:
        rows = download_geonames()
    except Exception:
        log.exception("GeoNames download failed")
        return 1

    records = build_records(rows)
    if not records:
        log.error("No pincode records built — GeoNames format may have changed")
        return 1

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for r in records:
            flat = dict(r)
            flat["places"] = "; ".join(r["places"])
            flat["search_tags"] = "; ".join(r["search_tags"])
            writer.writerow(flat)

    with_geo = sum(1 for r in records if r["latitude"] is not None)
    log.info(
        "Wrote %d pincodes to %s and %s (%d with coordinates)",
        len(records),
        OUTPUT_JSON,
        OUTPUT_CSV,
        with_geo,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
