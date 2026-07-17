<div align="center">

# MF-Engine — Indian Mutual Fund Fund-Manager Web Scraper

**An open-source Python web-scraping pipeline that builds a structured dataset of fund managers at every AMFI-registered mutual fund (AMC) in India.**

From the AMFI members directory to a clean CSV of who manages the money — fund-manager names, designations, locations, emails, and LinkedIn profile URLs — for every SEBI-registered Asset Management Company. Built with [Crawl4AI](https://github.com/unclecode/crawl4ai), Playwright, and Python 3.11.

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Crawl4AI](https://img.shields.io/badge/crawler-Crawl4AI-6E56CF.svg)](https://github.com/unclecode/crawl4ai)
[![Docker](https://img.shields.io/badge/deploy-Docker%20Compose-2496ED.svg)](https://docs.docker.com/compose/)
[![Status](https://img.shields.io/badge/status-active-success.svg)](#roadmap)

*Keywords: Indian mutual fund fund managers list · AMFI AMC scraper · fund manager database India · mutual fund data extraction · Python web scraping pipeline · Crawl4AI example project*

</div>

---

## What it does

**MF-Engine is a web scraper and data pipeline for the Indian mutual fund industry.** It collects, from public sources only, a structured list of the fund managers who run India's mutual fund schemes — the kind of dataset normally sold behind expensive B2B data subscriptions.

Indian Asset Management Companies (AMCs) publish who runs their funds — but scattered across ~55 corporate websites, each with a different layout, most behind bot protection. MF-Engine walks the chain automatically:

1. **Discovers** every active AMC from AMFI, the industry's source of truth, with its official corporate domain.
2. **Maps** each site to the pages that actually matter — team directories and fund/scheme pages — straight from the site's own sitemap. No URLs are ever guessed.
3. **Extracts** fund-manager records (name, designation, location, email) into a CSV.
4. **Enriches** each manager with a name-matched LinkedIn profile URL.

The result is [`data/fund_managers.csv`](data) — a dataset you can't buy off the shelf, built entirely from public sources.

Indian Asset Management Companies (AMCs) publish who runs their funds — but scattered across ~55 corporate websites, each with a different layout, most behind bot protection. MF-Engine walks the chain automatically:

1. **Discovers** every active AMC from AMFI, the industry's source of truth, with its official corporate domain.
2. **Maps** each site to the pages that actually matter — team directories and fund/scheme pages — straight from the site's own sitemap. No URLs are ever guessed.
3. **Extracts** fund-manager records (name, designation, location, email) into a CSV.
4. **Enriches** each manager with a name-matched LinkedIn profile URL.

The result is [`data/fund_managers.csv`](data) — a dataset you can't buy off the shelf, built entirely from public sources.

```mermaid
flowchart LR
    A["AMFI members<br/>directory"] --> P1["Phase 1<br/>seed list"]
    P1 --> P2["Phase 2<br/>sitemap page inventory"]
    P2 --> P3["Phase 3<br/>manager extraction"]
    P3 --> P4["Phase 4<br/>LinkedIn + email"]
    P4 --> OUT[("fund_managers<br/>_enriched.csv")]
```

## Highlights

- **Source of truth, not guesswork.** Seeds from AMFI's hydration payload — stable IDs, registered legal names, and each AMC's *official* website. Domains are read, never slugged together.
- **Never fabricates a URL.** Every page crawled is one the site itself published (sitemap `<loc>`, on-page anchors), followed through redirects to its real destination. Pattern-matching only *classifies* discovered URLs; it never *constructs* them.
- **Gets past the walls.** Stealth headless Chromium, `www.`-variant retries, soft-200 challenge detection, and per-site canonical-host resolution unlock WAF-protected AMCs (HDFC, ICICI, UTI, Franklin…).
- **Degrades safely.** Live scrape unusable? Fall back to an embedded roster. Search returns junk? A name-match guard rejects it — a wrong LinkedIn URL never lands in the data.
- **Batteries-included stack.** A single `docker compose` brings up MinIO, a local Qwen LLM (vLLM), Open WebUI, Qdrant, and SearXNG.

## Pipeline

| Phase | Script | Output | What it does | Status |
|:-----:|--------|--------|--------------|:------:|
| **1** | [`src/main.py`](src/main.py) | `amc_seed_list.json` | Scrape AMFI → **55 AMCs** with official domains & verified sitemaps | ✅ |
| **2** | [`src/phase2_discover.py`](src/phase2_discover.py) | `amc_page_inventory.json` | Classify sitemap URLs → team + scheme pages (**40 AMCs, 7,372 scheme URLs**) | ✅ |
| **3** | [`src/phase3_extract.py`](src/phase3_extract.py) | `fund_managers.csv` | Extract **137 managers** — name, designation, email, location | ✅ |
| **4** | [`src/phase4_enrich.py`](src/phase4_enrich.py) | `fund_managers_enriched.csv` | Name-matched LinkedIn URL + best-effort email | ✅ |
| 5 | — | MinIO buckets | Persist raw HTML + JSON, date-partitioned | 📋 planned |
| 6 | — | Qdrant | Semantic search over manager profiles | 📋 planned |

## Quickstart

```bash
# 1. Install
pip install -r setup/requirements.txt
playwright install chromium          # one-time browser download

# 2. Run the pipeline (from the repo root)
python src/main.py                   # Phase 1 → data/amc_seed_list.json
python src/phase2_discover.py        # Phase 2 → data/amc_page_inventory.json
python src/phase3_extract.py         # Phase 3 → data/fund_managers.csv
python src/phase4_enrich.py          # Phase 4 → data/fund_managers_enriched.csv
```

Phase 4's LinkedIn search needs a backend — set `BRAVE_API_KEY` (reliable) or point `SEARXNG_URL` at a local SearXNG (no key, best-effort). See [Configuration](#configuration).

**Bonus — SEBI registered intermediaries** (standalone): scrape the *regulator's* official directories — registration numbers, addresses, and dates that the industry bodies don't publish. Covers the broader wealth-management universe, not just mutual funds:

```bash
python src/sebi_intermediaries.py                    # AMCs + PMS + AIF + RIAs
python src/sebi_intermediaries.py mutual-funds aif   # or pick types
```

| Type | Records | Output |
|---|---|---|
| `mutual-funds` | 59 AMCs | `data/sebi_mutual_funds.json` |
| `portfolio-managers` | ~526 PMS firms | `data/sebi_portfolio_managers.json` |
| `aif` | ~1,989 funds | `data/sebi_aif.json` |
| `investment-advisers` | ~1,044 RIAs | `data/sebi_investment_advisers.json` |

### With Docker

```bash
docker build -t mf-engine .
docker run -v ./data:/app/data mf-engine          # runs Phase 1

# Full supporting stack (MinIO, vLLM/Qwen, Open WebUI, Qdrant, SearXNG, Tor):
cd docker && cp .env.example .env
docker compose up -d
```

## Output

`fund_managers_enriched.csv` — one row per (AMC, manager):

| Column | Example |
|--------|---------|
| `firm_name` | `Aditya Birla Sun Life Mutual Fund` |
| `manager_name` | `Harish Krishnan` |
| `designation` | `Chief Investment Officer` |
| `location` | `Mumbai` |
| `email` | verified only (AMC page / Hunter / SMTP), else blank |
| `email_guess` | `harish.krishnan@…` — a pattern guess, never asserted as fact |
| `linkedin_url` | `https://www.linkedin.com/in/harish-krishnan-cfa-38402950/` |

Full field semantics for every stage: [context/data-schema.md](context/data-schema.md).

## Configuration

Phase 4 is driven by environment variables (all optional):

| Variable | Purpose |
|----------|---------|
| `BRAVE_API_KEY` | Brave Search API for LinkedIn discovery — reliable, recommended |
| `SEARXNG_URL` | Self-hosted SearXNG fallback (default `http://localhost:8080`) |
| `HUNTER_API_KEY` | Hunter.io email-finder for *verified* emails |
| `VERIFY_SMTP=1` | Attempt SMTP RCPT verification of guessed emails (needs `dnspython`) |
| `SEARCH_GAP_SECONDS` | Pause between live SearXNG queries (default `4`) |

Hand-verified profiles live in [`linkedin_overrides.json`](linkedin_overrides.json) (`"name|firm"` → URL) and are applied as authoritative, skipping search.

## Architecture & docs

- [context/](context/) — project overview, phase-by-phase design, data schema (read before working on pipeline logic)
- [docs/](docs/) — Mermaid flowcharts and sequence diagrams, high- and low-level
- [CLAUDE.md](CLAUDE.md) — stack, commands, and conventions

## Tech stack

`Python 3.11` · `asyncio` · [Crawl4AI](https://github.com/unclecode/crawl4ai) (Playwright/Chromium) · `BeautifulSoup` · `httpx` · Docker Compose · MinIO · vLLM + Qwen2.5 · Qdrant · SearXNG

## Roadmap

- [x] Phases 1–4: seed → discovery → extraction → enrichment
- [ ] Phase 5: MinIO persistence (dated, immutable raw-HTML + JSON archive)
- [ ] Phase 6: Qdrant semantic search + RAG over manager profiles
- [ ] LLM-assisted extraction (Qwen) to replace the Phase 3 heuristic and map managers → funds from scheme pages

## Who it's for

- **Fintech & wealth-tech builders** who need a fund-manager reference dataset for research tools, dashboards, or investor-facing products.
- **Data journalists & analysts** tracking who manages India's mutual fund AUM, manager moves, and CIO changes.
- **Recruiters & BD teams** mapping the asset-management talent landscape across Indian AMCs.
- **Web-scraping engineers** looking for a real-world [Crawl4AI](https://github.com/unclecode/crawl4ai) + Playwright example that handles JavaScript rendering, sitemaps, WAF/bot protection, and canonical-host resolution.

## Frequently asked questions

**What is MF-Engine?**
MF-Engine is an open-source Python pipeline that scrapes public data to build a structured dataset of fund managers at India's SEBI-registered mutual fund companies (AMCs), starting from the AMFI members directory.

**How does it find every Indian AMC?**
It reads AMFI's members directory (`amfiindia.com/aboutamfi?tab=members`), which is the authoritative list of registered mutual fund houses. The page ships a hydration JSON payload with each AMC's stable ID, legal name, and official website — so the roster and domains are read from source, not guessed.

**Does it scrape LinkedIn?**
No. It never fetches LinkedIn profile pages. Phase 4 uses a web search to *discover* a manager's public profile URL, name-matches it, and stores only the URL. LinkedIn's own content is never accessed.

**Is the data accurate / where does it come from?**
Every record comes from a public source — the AMFI directory, each AMC's own website (via its sitemap), and public web search. Guessed values (e.g. an inferred email pattern) are kept in a separate `email_guess` column and never presented as verified fact.

**What technologies does it use?**
Python 3.11, `asyncio`, Crawl4AI on Playwright/Chromium for JavaScript-heavy and bot-protected sites, BeautifulSoup, and httpx. An optional Docker Compose stack adds MinIO, a local Qwen LLM via vLLM, Qdrant, and SearXNG.

**Can I use this for another country or industry?**
The architecture (authoritative seed list → sitemap page inventory → extraction → enrichment) is generic. Swap the Phase 1 source and the classification patterns and it applies to any directory-of-companies problem.

**Is it legal to use?**
It collects publicly available information for research. You are responsible for complying with each site's Terms of Service and applicable data-protection law — see the [disclaimer](#disclaimer).

## Glossary

- **AMC (Asset Management Company)** — a firm that manages mutual fund schemes (e.g. SBI Mutual Fund, HDFC Mutual Fund). ~55 are registered in India.
- **AMFI (Association of Mutual Funds in India)** — the industry body whose members directory is the authoritative list of active AMCs.
- **Fund manager** — the investment professional who runs a fund's portfolio. An AMC employee — **not** the same as an MFD.
- **MFD (Mutual Fund Distributor)** — an agent/broker who *sells* funds to investors (has a public ARN). Distinct from fund managers; not what this project extracts.
- **NAV / scheme** — a "scheme" is an individual mutual fund; NAV is its per-unit net asset value. Scheme pages are where AMCs list the managers running each fund.

## Contributing

Contributions are welcome — new AMC mappings, better parsing, a search backend, docs. Start with [CONTRIBUTING.md](CONTRIBUTING.md); it covers setup, the four project principles (chief among them: **never fabricate a URL**), the PR checklist, and how AI-assisted changes are handled. Please also read the [Code of Conduct](CODE_OF_CONDUCT.md).

- 🐛 [Report a bug](.github/ISSUE_TEMPLATE/bug_report.md) · 💡 [Request a feature](.github/ISSUE_TEMPLATE/feature_request.md) · 🔒 [Security policy](SECURITY.md)

## Disclaimer

MF-Engine collects **publicly available** information for research purposes. It reads only what sites publish (sitemaps, public pages, public search results); it does **not** scrape LinkedIn profile pages, bypass authentication, or fabricate contact data — guessed emails are clearly separated from verified ones. Respect each site's Terms of Service and applicable data-protection law when using the output.

## License

[Apache License 2.0](LICENSE) © 2026 the MF-Engine authors.

---

<div align="center">

**MF-Engine** — Indian mutual fund fund-manager web scraper & dataset pipeline.

<sub>Topics: `web-scraping` · `python` · `crawl4ai` · `playwright` · `mutual-funds` · `india` · `amfi` · `fund-managers` · `data-pipeline` · `dataset` · `fintech` · `etl` · `web-crawler` · `data-engineering`</sub>

<sub>Related searches: how to scrape Indian mutual fund data · list of AMCs in India · fund manager database · AMFI fund manager list · Crawl4AI Playwright tutorial · scrape company team pages from sitemap · Python asyncio web scraper example</sub>

</div>
