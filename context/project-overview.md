# Project Overview

## Mission

Build a structured dataset of fund managers across all active Indian Asset Management Companies (AMCs) — who manages which funds, at which firm, with what background — by crawling each AMC's official corporate website.

## Source of truth

- **AMFI** (Association of Mutual Funds in India, https://www.amfiindia.com) maintains the authoritative member directory of active AMCs at https://www.amfiindia.com/aboutamfi?tab=members (the old `/members` path is a 404). The directory payload carries ~55 member entries (July 2026) — 49 operating fund houses plus not-yet-launched members (e.g. ASK, Lakshya) — and changes a few times a year as new houses launch (e.g. Jio BlackRock, Abakkus, Capitalmind, The Wealth Company) or merge.
- Each member name on the directory links to a detail page at `https://www.amfiindia.com/member/{id}` (e.g. Invesco = 42, Old Bridge = 78, Jio BlackRock = 82) — useful in Phase 2 for corporate contact/website validation.
- Each AMC publishes its fund-manager/team information on its own corporate site, in wildly different formats — hence a per-domain crawl seeded from the AMFI roster.

## Why a seed list first

The seed list (`data/amc_seed_list.json`) is the pipeline's root input — every downstream phase keys off it. The members page embeds a hydration JSON payload carrying each AMC's **official website** (`amc_website`), stable `mf_id`, and registered legal name, so on the normal path domains are authoritative, not guessed. The curated dictionary (`KNOWN_DOMAINS` in `main.py`) and slug guess (`www.{slug}mf.com`) only cover members without a listed website (unlaunched fund houses) and degraded fallback paths.

## Constraints

- amfiindia.com renders content with JavaScript and sits behind bot protection — scraping requires a real headless browser (Crawl4AI/Playwright), human-like user agent, and defensive waits.
- Guessed domains and team URLs are unverified; Phase 2 validates them against live sites.
