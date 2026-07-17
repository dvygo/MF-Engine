"""MF-Engine — collect every dataset into data/csv/ as CSV.

The pipeline phases write their native formats (JSON for the seed list and page
inventory, CSV for fund managers); the SEBI scraper writes both. This gathers
everything into one place, in CSV, for spreadsheet/BI consumption:

    data/csv/fund_managers.csv               Phase 3 — managers per AMC
    data/csv/fund_managers_enriched.csv      Phase 4 — + LinkedIn / email
    data/csv/amc_seed_list.csv               Phase 1 — AMFI roster + domains
    data/csv/sebi_*.csv                      SEBI directories (own scraper)
    data/csv/wealth_managers.csv             all SEBI types, rolled up

Usage:
    python src/export_csv.py
"""

import csv
import json
import logging
import shutil
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("mf-engine.export")

DATA_DIR = Path("data")
CSV_DIR = DATA_DIR / "csv"

# JSON datasets → CSV, with the column order we want in the export.
JSON_EXPORTS: dict[str, list[str]] = {
    "amc_seed_list": [
        "amc_id", "firm_name", "legal_name", "clean_name", "base_domain",
        "sitemap_url", "sitemap_type", "sitemap_verified",
    ],
}
# Already-CSV datasets → copied through as-is.
CSV_COPIES = ["fund_managers", "fund_managers_enriched"]


def export_json(stem: str, columns: list[str]) -> int:
    src = DATA_DIR / f"{stem}.json"
    if not src.exists():
        log.warning("%s missing — skipped", src)
        return 0
    rows = json.loads(src.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        log.warning("%s empty — skipped", src)
        return 0
    out = CSV_DIR / f"{stem}.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    log.info("Wrote %d rows to %s", len(rows), out)
    return len(rows)


def copy_csv(stem: str) -> int:
    src = DATA_DIR / f"{stem}.csv"
    if not src.exists():
        log.warning("%s missing — skipped", src)
        return 0
    out = CSV_DIR / f"{stem}.csv"
    shutil.copyfile(src, out)
    with out.open(encoding="utf-8") as f:
        n = max(sum(1 for _ in f) - 1, 0)
    log.info("Wrote %d rows to %s", n, out)
    return n


def main() -> int:
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    for stem, columns in JSON_EXPORTS.items():
        total += export_json(stem, columns)
    for stem in CSV_COPIES:
        total += copy_csv(stem)

    existing = sorted(p.name for p in CSV_DIR.glob("*.csv"))
    log.info("data/csv/ now holds %d file(s): %s", len(existing), ", ".join(existing))
    log.info("Note: sebi_*.csv and wealth_managers.csv come from sebi_intermediaries.py")
    return 0 if total else 1


if __name__ == "__main__":
    sys.exit(main())
