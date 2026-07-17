"""MF-Engine — location-tag and search fund managers / wealth-manager firms.

Ties the datasets together on geography:

    manager  --(firm name)-->  SEBI firm  --(pincode)-->  data/pincodes.json
                                                          district, taluk, state, lat/lon

A manager's scraped `location` is a best-effort guess off a web page. The firm's
SEBI address carries a real PIN, so joining through it gives an authoritative,
searchable location — and lets "bangalore" match a firm GeoNames files under
"Bengaluru" (see search_tags in src/geo_pincodes.py).

Build the tagged dataset, then query it:

    python src/locate.py --build                 # -> data/csv/managers_located.csv
    python src/locate.py bangalore               # any tag: city, district, state, PIN
    python src/locate.py 560093 --firms          # search firms instead of managers
    python src/locate.py --near 19.07,72.87 --km 25

Usage:
    python src/locate.py [query] [--build] [--firms] [--near LAT,LON --km N]
"""

import csv
import json
import logging
import math
import re
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("mf-engine.locate")

DATA_DIR = Path("data")
CSV_DIR = DATA_DIR / "csv"
PINCODES = DATA_DIR / "pincodes.json"
FIRM_SOURCES = [
    DATA_DIR / "sebi_mutual_funds.json",
    DATA_DIR / "sebi_portfolio_managers.json",
    DATA_DIR / "sebi_aif.json",
    DATA_DIR / "sebi_investment_advisers.json",
]
# Read the phases' own output, not the data/csv/ copies export_csv.py makes —
# otherwise a re-scrape silently locates stale rows until that copy is refreshed.
MANAGER_SOURCES = [
    DATA_DIR / "fund_managers_enriched.csv",
    DATA_DIR / "pms_managers.csv",
]
OUT_MANAGERS = CSV_DIR / "managers_located.csv"
OUT_FIRMS = CSV_DIR / "firms_located.csv"

MANAGER_COLUMNS = [
    "manager_name", "designation", "firm_name", "sebi_type", "reg_no",
    "pincode", "city", "district", "taluk", "state", "latitude", "longitude",
    "email", "firm_email", "linkedin_url", "search_tags",
]
FIRM_COLUMNS = [
    "name", "sebi_type", "reg_no", "contact_person", "email", "telephone",
    "domain", "pincode", "city", "district", "taluk", "state",
    "latitude", "longitude", "search_tags",
]


def norm(name: str) -> str:
    """Loose firm-name key: lowercase alphanumerics, legal suffixes dropped.

    AMFI says 'Aditya Birla Sun Life Mutual Fund', SEBI says 'ADITYA BIRLA SUN
    LIFE MF' — matching needs the noise gone.
    """
    n = name.lower()
    n = re.sub(
        r"\b(mutual fund|asset management|asset managers|amc|mf|company|co|"
        r"private|pvt|limited|ltd|llp|india|investment|managers|advisors|"
        r"advisers|capital|trust)\b",
        " ",
        n,
    )
    return re.sub(r"[^a-z0-9]", "", n)


def load_pincodes() -> dict[str, dict]:
    if not PINCODES.exists():
        log.error("Missing %s — run: python src/geo_pincodes.py", PINCODES)
        return {}
    return {r["pincode"]: r for r in json.loads(PINCODES.read_text(encoding="utf-8"))}


def load_firms() -> list[dict]:
    firms: list[dict] = []
    for path in FIRM_SOURCES:
        if path.exists():
            firms.extend(json.loads(path.read_text(encoding="utf-8")))
    return firms


def load_managers() -> list[dict]:
    rows: list[dict] = []
    for path in MANAGER_SOURCES:
        if path.exists():
            with path.open(encoding="utf-8") as f:
                rows.extend(csv.DictReader(f))
    return rows


def geo_for(pincode: str, pins: dict[str, dict]) -> dict:
    return pins.get(pincode, {})


def build() -> int:
    pins = load_pincodes()
    if not pins:
        return 1
    firms = load_firms()
    if not firms:
        log.error("No SEBI firm data — run: python src/sebi_intermediaries.py")
        return 1

    # --- firms -----------------------------------------------------------
    firm_rows: list[dict] = []
    by_key: dict[str, dict] = {}
    for f in firms:
        geo = geo_for(f.get("pincode", ""), pins)
        tags = set(geo.get("search_tags", []))
        for extra in (f.get("city", ""), f.get("state", ""), f.get("pincode", "")):
            if extra:
                tags.add(extra.lower())
        row = {
            "name": f["name"],
            "sebi_type": f.get("sebi_type", ""),
            "reg_no": f.get("reg_no", ""),
            "contact_person": f.get("contact_person", ""),
            "email": f.get("email", ""),
            "telephone": f.get("telephone", ""),
            "domain": f.get("domain", ""),
            "pincode": f.get("pincode", ""),
            "city": f.get("city", ""),
            "district": geo.get("district", ""),
            "taluk": geo.get("taluk", ""),
            "state": geo.get("state", "") or f.get("state", ""),
            "latitude": geo.get("latitude", ""),
            "longitude": geo.get("longitude", ""),
            "search_tags": "; ".join(sorted(t for t in tags if t)),
        }
        firm_rows.append(row)
        by_key.setdefault(norm(f["name"]), row)

    # --- managers, located through their firm ----------------------------
    mgr_rows: list[dict] = []
    matched = 0
    for m in load_managers():
        firm = by_key.get(norm(m.get("firm_name", "")), {})
        if firm:
            matched += 1
        # The firm's SEBI address is authoritative. Only fall back to the
        # manager's scraped location when no firm matched — otherwise a stale
        # page guess ("Bangalore") pollutes the tags of a Mumbai-registered firm.
        if firm:
            tags = set(filter(None, firm.get("search_tags", "").split("; ")))
        else:
            tags = {m["location"].lower()} if m.get("location") else set()
        mgr_rows.append(
            {
                "manager_name": m.get("manager_name", ""),
                "designation": m.get("designation", ""),
                "firm_name": m.get("firm_name", ""),
                "sebi_type": firm.get("sebi_type", ""),
                "reg_no": firm.get("reg_no", ""),
                "pincode": firm.get("pincode", ""),
                # firm's SEBI city is authoritative; fall back to the scraped guess
                "city": firm.get("city", "") or m.get("location", ""),
                "district": firm.get("district", ""),
                "taluk": firm.get("taluk", ""),
                "state": firm.get("state", ""),
                "latitude": firm.get("latitude", ""),
                "longitude": firm.get("longitude", ""),
                "email": m.get("email", ""),
                "firm_email": firm.get("email", ""),
                "linkedin_url": m.get("linkedin_url", ""),
                "search_tags": "; ".join(sorted(tags)),
            }
        )

    CSV_DIR.mkdir(parents=True, exist_ok=True)
    for path, cols, rows in (
        (OUT_FIRMS, FIRM_COLUMNS, firm_rows),
        (OUT_MANAGERS, MANAGER_COLUMNS, mgr_rows),
    ):
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)

    geo_firms = sum(1 for r in firm_rows if r["latitude"] != "")
    log.info("Wrote %d firms to %s (%d geo-tagged)", len(firm_rows), OUT_FIRMS, geo_firms)
    log.info(
        "Wrote %d managers to %s (%d matched to a SEBI firm)",
        len(mgr_rows),
        OUT_MANAGERS,
        matched,
    )
    return 0


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def search(query: str, firms: bool, near: str, km: float) -> int:
    path = OUT_FIRMS if firms else OUT_MANAGERS
    if not path.exists():
        log.error("Missing %s — run: python src/locate.py --build", path)
        return 1
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if near:
        try:
            lat0, lon0 = (float(x) for x in near.split(","))
        except ValueError:
            log.error("--near expects LAT,LON e.g. 19.07,72.87")
            return 1
        hits = []
        for r in rows:
            if r.get("latitude") and r.get("longitude"):
                d = haversine(lat0, lon0, float(r["latitude"]), float(r["longitude"]))
                if d <= km:
                    hits.append((d, r))
        hits.sort(key=lambda x: x[0])
        log.info("%d within %.0f km of %s", len(hits), km, near)
        for d, r in hits[:40]:
            label = r.get("manager_name") or r.get("name")
            log.info("  %5.1f km  %-28s %-34s %s", d, label[:28], r["firm_name"][:34]
                     if "firm_name" in r else r.get("sebi_type", ""), r["city"])
        return 0

    q = query.lower().strip()
    hits = [r for r in rows if q in r.get("search_tags", "").lower()]
    log.info("%d match '%s'", len(hits), query)
    for r in hits[:40]:
        if firms:
            log.info(
                "  %-40s %-12s %-14s %s",
                r["name"][:40], r["sebi_type"][:12], r["pincode"], r["city"]
            )
        else:
            log.info(
                "  %-24s %-20s %-34s %s",
                r["manager_name"][:24], r["designation"][:20],
                r["firm_name"][:34], r["city"]
            )
    if len(hits) > 40:
        log.info("  ... and %d more (full results in %s)", len(hits) - 40, path)
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if "--build" in argv:
        return build()
    near = ""
    km = 25.0
    if "--near" in argv:
        i = argv.index("--near")
        near = argv[i + 1] if i + 1 < len(argv) else ""
    if "--km" in argv:
        i = argv.index("--km")
        km = float(argv[i + 1]) if i + 1 < len(argv) else 25.0
    firms = "--firms" in argv
    positional = [
        a
        for i, a in enumerate(argv)
        if not a.startswith("--")
        and not (i > 0 and argv[i - 1] in ("--near", "--km"))
    ]
    query = positional[0] if positional else ""
    if not query and not near:
        log.error(__doc__)
        return 1
    return search(query, firms, near, km)


if __name__ == "__main__":
    sys.exit(main())
