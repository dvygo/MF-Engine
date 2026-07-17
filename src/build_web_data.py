"""MF-Engine — build the JSON shards the web app searches.

Writes one file per dataset into web/public/data/, plus a manifest. The site
fetches the manifest, then every shard in parallel, and indexes the lot in the
browser — the dataset (~3.9k rows) is far too small to justify a database.

Why shards rather than one blob: the datasets refresh on different cadences
(AIF moves weekly, the AMC roster rarely). Each shard carries a content hash in
the manifest and is fetched as `<name>.json?v=<hash>`, so re-scraping one
dataset busts only that file — every other shard stays in the browser cache.
Filenames stay stable; the hash does the versioning.

    web/public/data/manifest.json
    web/public/data/managers.json
    web/public/data/firms_mutual_funds.json
    web/public/data/firms_portfolio_managers.json
    web/public/data/firms_aif.json
    web/public/data/firms_investment_advisers.json

Usage:
    python src/build_web_data.py
"""

import csv
import hashlib
import json
import logging
import sys
from datetime import date
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("mf-engine.web")

CSV_DIR = Path("data/csv")
FIRMS_CSV = CSV_DIR / "firms_located.csv"
MANAGERS_CSV = CSV_DIR / "managers_located.csv"
OUT_DIR = Path("web/public/data")

# SEBI type -> shard filename. Split by refresh cadence, not by size.
FIRM_SHARDS = {
    "mutual-funds": "firms_mutual_funds.json",
    "portfolio-managers": "firms_portfolio_managers.json",
    "aif": "firms_aif.json",
    "investment-advisers": "firms_investment_advisers.json",
}
MANAGERS_SHARD = "managers.json"
PLACES_SHARD = "places.json"


def num(value: str) -> float | None:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def compact(row: dict) -> dict:
    """Drop empties — they're roughly a third of the payload otherwise."""
    return {k: v for k, v in row.items() if v not in ("", None)}


def load_firms() -> dict[str, list[dict]]:
    shards: dict[str, list[dict]] = {name: [] for name in FIRM_SHARDS.values()}
    with FIRMS_CSV.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            shard = FIRM_SHARDS.get(r["sebi_type"])
            if not shard:
                continue
            shards[shard].append(
                compact(
                    {
                        "k": "firm",
                        "n": r["name"],
                        "t": r["sebi_type"],
                        "r": r["reg_no"],
                        "cp": r["contact_person"],
                        "e": r["email"],
                        "ph": r["telephone"],
                        "w": r["domain"],
                        "p": r["pincode"],
                        "c": r["city"],
                        "d": r["district"],
                        "s": r["state"],
                        "lat": num(r["latitude"]),
                        "lon": num(r["longitude"]),
                        "tags": r["search_tags"],
                    }
                )
            )
    return shards


def load_managers() -> list[dict]:
    rows = []
    with MANAGERS_CSV.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(
                compact(
                    {
                        "k": "manager",
                        "n": r["manager_name"],
                        "role": r["designation"],
                        "firm": r["firm_name"],
                        "t": r["sebi_type"],
                        "e": r["email"] or r["firm_email"],
                        "li": r["linkedin_url"],
                        "p": r["pincode"],
                        "c": r["city"],
                        "d": r["district"],
                        "s": r["state"],
                        "lat": num(r["latitude"]),
                        "lon": num(r["longitude"]),
                        "tags": r["search_tags"],
                    }
                )
            )
    return rows


def build_places(firm_shards: dict[str, list[dict]], managers: list[dict]) -> list[dict]:
    """Distinct places, ranked by how many records sit there.

    A separate, tiny corpus for "did you mean?" suggestions. MiniSearch's own
    autoSuggest runs over every indexed field, so it offers firm-name noise
    ("delightfinancial delight") rather than places. Fuzzy-matching a clean
    place list instead gives 'deli' -> 'Delhi'.
    """
    counts: dict[tuple[str, str], int] = {}
    for row in [r for rows in firm_shards.values() for r in rows] + managers:
        for kind, key in (("city", "c"), ("district", "d"), ("state", "s")):
            name = (row.get(key) or "").strip()
            if name:
                counts[(name, kind)] = counts.get((name, kind), 0) + 1

    places = [
        {"name": name, "kind": kind, "n": n}
        for (name, kind), n in counts.items()
        if n >= 2  # one-off spellings are noise, not suggestions
    ]
    places.sort(key=lambda p: -p["n"])
    return places


def write_shard(name: str, rows: list[dict]) -> dict:
    path = OUT_DIR / name
    body = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    path.write_text(body, encoding="utf-8")
    return {
        "file": name,
        "rows": len(rows),
        # short content hash — the cache-buster in ?v=
        "hash": hashlib.sha256(body.encode("utf-8")).hexdigest()[:12],
        "bytes": len(body.encode("utf-8")),
        "updated": date.today().isoformat(),
    }


def main() -> int:
    if not FIRMS_CSV.exists() or not MANAGERS_CSV.exists():
        log.error("Missing located CSVs — run: python src/locate.py --build")
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []

    firm_shards = load_firms()
    managers = load_managers()
    for name, rows in firm_shards.items():
        entries.append(write_shard(name, rows))
    entries.append(write_shard(MANAGERS_SHARD, managers))
    entries.append(write_shard(PLACES_SHARD, build_places(firm_shards, managers)))

    manifest_path = OUT_DIR / "manifest.json"
    previous = {}
    if manifest_path.exists():
        try:
            previous = {
                e["file"]: e["hash"]
                for e in json.loads(manifest_path.read_text(encoding="utf-8"))["shards"]
            }
        except Exception:
            previous = {}

    manifest = {
        "generated": date.today().isoformat(),
        "total_rows": sum(e["rows"] for e in entries),
        "shards": entries,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    for e in entries:
        changed = previous.get(e["file"]) not in (e["hash"], None)
        fresh = e["file"] not in previous
        mark = "new" if fresh else ("changed" if changed else "cached")
        log.info(
            "  %-34s %6d rows  %6.0f KB  %s  [%s]",
            e["file"], e["rows"], e["bytes"] / 1024, e["hash"], mark
        )
    log.info(
        "Wrote %d shards (%d rows) + manifest.json to %s",
        len(entries),
        manifest["total_rows"],
        OUT_DIR,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
