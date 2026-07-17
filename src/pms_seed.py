"""MF-Engine — build a crawler seed list for SEBI Portfolio Managers (PMS).

Turns data/sebi_portfolio_managers.json (from src/sebi_intermediaries.py) into
the same seed shape Phase 2 consumes, so the existing discovery → extraction
pipeline runs over PMS firms instead of AMFI mutual funds.

SEBI publishes each PMS firm's website, so base domains come from the regulator
— no guessing. Firms without a listed website are skipped (nothing to crawl);
they'd need a search pass to resolve a domain first.

Output: data/pms_seed_list.json

Then run the rest of the pipeline against it:
    SEED_PATH=data/pms_seed_list.json INVENTORY_PATH=data/pms_page_inventory.json \\
        python src/phase2_discover.py
    INVENTORY_PATH=data/pms_page_inventory.json MANAGERS_CSV=data/pms_managers.csv \\
        python src/phase3_extract.py

Usage:
    python src/pms_seed.py
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

# Reuse the AMFI pipeline's name cleaning and sitemap discovery verbatim.
sys.path.insert(0, str(Path(__file__).parent))
from main import clean_name, enrich_with_sitemaps  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("mf-engine.pms-seed")

SOURCE_PATH = Path("data/sebi_portfolio_managers.json")
OUTPUT_PATH = Path("data/pms_seed_list.json")


async def main() -> int:
    if not SOURCE_PATH.exists():
        log.error(
            "Missing %s — run: python src/sebi_intermediaries.py portfolio-managers",
            SOURCE_PATH,
        )
        return 1
    firms = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))

    records: list[dict] = []
    for firm in firms:
        domain = (firm.get("domain") or "").strip()
        if not domain:
            continue  # no website listed with SEBI — nothing to crawl
        records.append(
            {
                "amc_id": firm["sebi_id"],
                "firm_name": firm["name"],
                "legal_name": firm["name"],
                "clean_name": clean_name(firm["name"]),
                "base_domain": domain,
                # carried through from SEBI so downstream keeps the regulator's data
                "sebi_reg_no": firm.get("reg_no", ""),
                "sebi_email": firm.get("email", ""),
                "sebi_contact_person": firm.get("contact_person", ""),
                "city": firm.get("city", ""),
                "state": firm.get("state", ""),
            }
        )

    skipped = len(firms) - len(records)
    log.info(
        "%d PMS firms — %d with a SEBI-listed website, %d skipped (no website)",
        len(firms),
        len(records),
        skipped,
    )
    if not records:
        log.error("No PMS firm has a usable website — nothing to seed")
        return 1

    log.info("Probing %d domains for sitemaps...", len(records))
    await enrich_with_sitemaps(records)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    verified = sum(1 for r in records if r.get("sitemap_verified"))
    log.info(
        "Wrote %d PMS seed records to %s (%d with a verified sitemap)",
        len(records),
        OUTPUT_PATH,
        verified,
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
