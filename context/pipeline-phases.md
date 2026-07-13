# Pipeline Phases

## Phase 1 — AMC seed list (implemented: `main.py`)

Scrape the AMFI members directory, normalize firm names, resolve corporate domains, write `data/amc_seed_list.json`.

- Live scrape via Crawl4AI (`AsyncWebCrawler`, headless Chromium, cache bypass, defensive render wait).
- **Primary parse**: the members page hydrates from an embedded escaped-JSON payload with one object per AMC — `mf_id`, `mf_name`, `amc_name`, and the **official `amc_website`**. Regex extraction over the unescaped HTML yields ~55 records with authoritative domains; no guessing.
- Name cleaning strips legal suffixes ("Mutual Fund", "Asset Management Company", "Ltd", …).
- Domain resolution for records without a website (and for fallback paths): `KNOWN_DOMAINS` curated map → substring match (longest key first) → `www.{slug}mf.com` guess.
- Resilience chain: payload extraction → DOM text scan → embedded static roster (49 names). The run's source is logged; the script always produces a seed file.
- **Sitemap discovery**: every domain is probed concurrently (httpx, semaphore 10) — `robots.txt` `Sitemap:` directive, then `/sitemap.xml`, `/sitemap_index.xml`, `/sitemap`, `/site-map` — and records carry `sitemap_url` / `sitemap_type` / `sitemap_verified` (~39/55 verify over plain HTTP; WAF-walled sites like HDFC need Phase 2's browser).

## Phase 2 — Team & scheme page discovery (implemented: `phase2_discover.py`)

**Hard rule: never construct or template URLs.** Only URLs that actually appear in the sitemap (or on-page anchors) get crawled, each followed through redirects to its final destination before scraping. Pattern-matching is for *classifying* discovered URLs only.

For each seed record, parse `sitemap_url` (XML: `<loc>` entries; HTML: anchor inventory) and classify the discovered URLs into two sets:

1. **Team/management pages** — discovered URLs whose path mentions team/management/fund-manager/leadership. Roster + bios.
2. **Scheme pages** — discovered URLs whose path marks a fund/scheme (HDFC's sitemap, for instance, lists every scheme page). Each scheme page names its fund managers with designations — the direct manager→fund mapping, richer than a roster.

Fetch strategy per URL: httpx first, headless Chromium fallback (WAF-walled sites; Chrome's XML viewer still exposes `<loc>` tags), and a `www.` host variant retry — some CDNs hard-deny the apex host while serving www (Akamai on hdfcfund.com). Sitemap indexes recurse into child sitemaps (capped 15). No usable sitemap → homepage anchors (still discovered URLs). Team URLs are resolved through redirects to final destinations.

Output: `data/amc_page_inventory.json`. Current yield: 25/55 AMCs with team pages, 35/55 with scheme pages (152 team + 4660 scheme URLs). Known gaps: ICICI/UTI/Franklin Templeton/ITI resist both httpx and vanilla Chromium (challenge pages) — need stealth/wait tuning; a few zero-yield AMCs need per-site classifier patterns.

## Phase 3 — Fund manager extraction (planned)

Crawl each verified team page and scheme page, extract structured manager profiles: name, designation, funds managed, experience, qualifications. Scheme pages yield the manager→fund edges (one page per fund, managers listed with titles); team pages yield fuller bios. Merge on manager name per AMC. LLM-assisted extraction (vLLM serving Qwen, OpenAI-compatible endpoint on :8000 — see `docker/docker-compose.yml`) since page structures vary per AMC.

## Phase 4 — Persistence (planned)

Land raw HTML snapshots and extracted JSON in a MinIO data lake (service defined in `docker/docker-compose.yml`, S3 API on :9000), for downstream querying and change tracking. Immutable, date-partitioned — every pull kept, nothing overwritten:

```
bucket mf-raw-html/   {crawl_date}/{base_domain}/{page}.html   (each page = one object)
bucket mf-extracted/  {crawl_date}/{base_domain}.json          (Phase 3 output)
```

## Phase 5 — Semantic search (planned)

Qdrant (:6333) holds the *latest* state: one point per manager (keyed by manager+firm, upserted each pull) with the extracted profile as payload. Role split:

- **Embedding model** (separate small model, e.g. sentence-transformers/BGE on CPU — not the chat Qwen) vectorizes profiles and queries.
- **Qdrant** does the actual search: cosine top-k over vectors. No LLM in the lookup.
- **Qwen via vLLM** optionally does RAG on top: takes Qdrant hits, writes a readable answer (Open WebUI on :3000 as the interface).

MinIO = dated immutable archive; Qdrant = current snapshot, searchable.
