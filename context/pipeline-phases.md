# Pipeline Phases

## Phase 1 — AMC seed list (implemented: `src/main.py`)

Scrape the AMFI members directory, normalize firm names, resolve corporate domains, write `data/amc_seed_list.json`.

- Live scrape via Crawl4AI (`AsyncWebCrawler`, headless Chromium, cache bypass, defensive render wait).
- **Primary parse**: the members page hydrates from an embedded escaped-JSON payload with one object per AMC — `mf_id`, `mf_name`, `amc_name`, and the **official `amc_website`**. Regex extraction over the unescaped HTML yields ~55 records with authoritative domains; no guessing.
- Name cleaning strips legal suffixes ("Mutual Fund", "Asset Management Company", "Ltd", …).
- Domain resolution for records without a website (and for fallback paths): `KNOWN_DOMAINS` curated map → substring match (longest key first) → `www.{slug}mf.com` guess.
- Resilience chain: payload extraction → DOM text scan → embedded static roster (49 names). The run's source is logged; the script always produces a seed file.
- **Sitemap discovery**: every domain is probed concurrently (httpx, semaphore 10) — `robots.txt` `Sitemap:` directive, then `/sitemap.xml`, `/sitemap_index.xml`, `/sitemap`, `/site-map` — and records carry `sitemap_url` / `sitemap_type` / `sitemap_verified` (~39/55 verify over plain HTTP; WAF-walled sites like HDFC need Phase 2's browser).

## Phase 2 — Team & scheme page discovery (implemented: `src/phase2_discover.py`)

**Hard rule: never construct or template URLs.** Only URLs that actually appear in the sitemap (or on-page anchors) get crawled, each followed through redirects to its final destination before scraping. Pattern-matching is for *classifying* discovered URLs only.

For each seed record, parse `sitemap_url` (XML: `<loc>` entries; HTML: anchor inventory) and classify the discovered URLs into two sets:

1. **Team/management pages** — discovered URLs whose path mentions team/management/fund-manager/leadership. Roster + bios.
2. **Scheme pages** — discovered URLs whose path marks a fund/scheme (HDFC's sitemap, for instance, lists every scheme page). Each scheme page names its fund managers with designations — the direct manager→fund mapping, richer than a roster.

Fetch strategy per URL: httpx first, headless Chromium fallback (Chrome's XML viewer still exposes `<loc>` tags), and a `www.` host-variant retry — some CDNs answer the apex host with a soft-200 challenge stub (200 OK, no real content) while serving the true sitemap on www (Akamai on hdfcfund.com/icicipruamc.com). A bare 200 is therefore not trusted: `get()` short-circuits only on a body actually containing `<loc>`, else keeps the richest body. The browser runs with stealth (`enable_stealth`, `magic`, `simulate_user`, `override_navigator`) to clear automation fingerprints. Sitemap indexes recurse into child sitemaps (capped 15). No usable sitemap → homepage anchors.

**Canonical host, not seed domain.** Discovered URLs are filtered against the host the sitemap actually *resolved to*, not AMFI's listed domain. This keeps AMCs whose AMFI domain redirects elsewhere (pgimindiamf.com → pgimindia.com) and correctly rejects a misconfigured sitemap serving another company's URLs (abakkusmf.com's sitemap lists capitalmindmf.com pages). Host match is a full-suffix compare so multi-part suffixes (assetmanagement.hsbc.co.in) aren't collapsed to co.in. Team URLs are then resolved through redirects to final destinations.

Output: `data/amc_page_inventory.json` (records carry `canonical_host`). Current yield: 29/55 AMCs with team pages, 40/55 with scheme pages (186 team + 7372 scheme URLs). Remaining zero-yield are small/newly-launched houses (Invesco's `/FundPage` slugless paths, Angel One, Choice, Unifi, ASK, Monarch, AlphaGrep) needing per-site classifier patterns, plus Lakshya (DNS does not resolve — site not up yet) and Abakkus (upstream sitemap misconfig).

## Phase 3 — Fund manager extraction (implemented: `src/phase3_extract.py`)

Current scope: crawl each AMC's team/management pages (from Phase 2 `team_urls`, blog/article paths filtered out) and extract **fund-manager name, designation, email, location** into `data/fund_managers.csv`. Heuristic only — no LLM, runs on CPU:

- **Names**: pair a person-name regex (honorific + full capitalised words, single initials allowed) with a designation label (Fund Manager / CIO / Portfolio Manager / Head of Equity…) on the same or preceding line; a stopword set rejects heading/role phrases.
- **Emails**: regex, generic locals (info@/service@…) deprioritised behind any personal address.
- **Location**: Indian-city match, preferring a city near an office/address cue.
- Dedupe on (firm, manager). Current yield: ~137 managers across 18 AMCs.

Crawls with Crawl4AI stealth. Best-effort by design — layouts vary per AMC and few sites publish per-manager emails. **Upgrade path**: swap the heuristic for an LLM pass (vLLM/Qwen on :8000, `instructor` + Pydantic) for cleaner names and manager→fund mapping from scheme pages.

## Phase 4 — Enrichment: LinkedIn + email (implemented: `src/phase4_enrich.py`)

Reads `data/fund_managers.csv` and adds, per manager, a LinkedIn profile URL and a best-effort email → `data/fund_managers_enriched.csv`.

- **LinkedIn**: a search (`{name} {firm} fund manager linkedin`, firm's "Mutual Fund" suffix trimmed). Backend is the **Brave Search API** when `BRAVE_API_KEY` is set — keyed, reliable, free tier ~2000/mo covers the full roster with no throttling — otherwise **SearXNG** (`SEARXNG_URL`) as a no-key fallback. The discovered profile URL is **name-matched** to the manager (last name must appear in the slug/title; single-token slugs must also carry the first name) so a wrong-person hit is rejected rather than stored — no LinkedIn page is ever fetched.
- **Verified overrides**: `linkedin_overrides.json` (keyed `"name|firm"`) holds hand-verified profile URLs, applied as authoritative and skipping search — reproducible, never re-searched.
- **Throttling reality**: SearXNG scrapes Bing/Google/DDG under the hood, so a burst gets those engines IP-throttled and they start returning junk (the name-match guard rejects it, so coverage drops but no bad data lands). The run is therefore serial with a `SEARCH_GAP_SECONDS` (default 4) pause between live queries; run against a cool instance for full coverage.
- **Email**: fund managers are AMC employees, not MFDs — no public directory lists their emails, and AMC sites rarely publish them. `email` holds a *verified* address only (from the AMC page in Phase 3, else Hunter.io if `HUNTER_API_KEY` set, else SMTP-verified if `VERIFY_SMTP=1`). `email_guess` holds the most-likely corporate pattern (`first.last@domain`) — kept in a separate column so a guess is never presented as fact.

Fund manager ≠ MFD: the AMFI `/api/distributor-agent` endpoint lists distributors (with contacts) and is not a source for fund managers.

## Side scraper — SEBI registered intermediaries (`src/sebi_intermediaries.py`)

Standalone, not part of the 1→4 chain. Scrapes SEBI's official registered-intermediary directories (the *regulator's* lists) → `data/sebi_<type>.json`. Each record: name, SEBI registration number, registered address (city/state parsed out), registration/validity date — fields the industry bodies don't publish.

This widens the project beyond mutual funds to the **broader Indian wealth-management universe**:

| Type (slug) | intmId | Records (July 2026) |
|---|---|---|
| `mutual-funds` | 23 | 59 AMCs |
| `portfolio-managers` | 33 | ~526 PMS firms |
| `aif` | 16 | ~1,989 Alternative Investment Funds |
| `investment-advisers` | 13 | ~1,044 RIAs |
| `research-analysts` | 14 | — |
| `merchant-bankers` | 9 | — |

Every directory paginates via the AJAX call its own `searchFormFpi()` makes to `getintmfpiinfo.jsp`, POSTing `intmId` + `doDirect=<page-1>` (0-based) and returning an HTML fragment of ~25 records. No token or browser needed — the script calls that endpoint directly, page by page, with retries and a 1s gap (SEBI drops rapid connections). It reads the "of N records" total to know when to stop.

```bash
python src/sebi_intermediaries.py                    # wealth-manager set (default)
python src/sebi_intermediaries.py mutual-funds aif   # specific types
python src/sebi_intermediaries.py --all              # every known type
```

Counts can land 1–2 short of SEBI's stated total where a record ships a blank registration number (those are skipped rather than stored half-empty).

## Phase 6 — Persistence (planned)

Land raw HTML snapshots and extracted JSON in a MinIO data lake (service defined in `docker/docker-compose.yml`, S3 API on :9000), for downstream querying and change tracking. Immutable, date-partitioned — every pull kept, nothing overwritten:

```
bucket mf-raw-html/   {crawl_date}/{base_domain}/{page}.html   (each page = one object)
bucket mf-extracted/  {crawl_date}/{base_domain}.json          (Phase 3 output)
```

## Phase 7 — Semantic search (planned)

Qdrant (:6333) holds the *latest* state: one point per manager (keyed by manager+firm, upserted each pull) with the extracted profile as payload. Role split:

- **Embedding model** (separate small model, e.g. sentence-transformers/BGE on CPU — not the chat Qwen) vectorizes profiles and queries.
- **Qdrant** does the actual search: cosine top-k over vectors. No LLM in the lookup.
- **Qwen via vLLM** optionally does RAG on top: takes Qdrant hits, writes a readable answer (Open WebUI on :3000 as the interface).

MinIO = dated immutable archive; Qdrant = current snapshot, searchable.
