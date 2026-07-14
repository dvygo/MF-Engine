# Data Schema

## `data/amc_seed_list.json` (Phase 1 output)

JSON array, one object per AMC:

| Field | Type | Meaning |
|---|---|---|
| `amc_id` | integer | On the live path: AMFI's own stable `mf_id` (e.g. PPFAS = 64). On the static fallback: sequential 1-based, not stable across runs. |
| `firm_name` | string | Fund-house name as listed by AMFI (`mf_name`), e.g. `"PPFAS Mutual Fund"`. |
| `legal_name` | string | Registered AMC entity (`amc_name`), e.g. `"PPFAS Asset Management Pvt. Ltd."`. Empty string on fallback paths. |
| `clean_name` | string | Core name after stripping legal suffixes, e.g. `"PPFAS"`. Join key for domain mapping. |
| `base_domain` | string | Corporate domain. Live path: taken from AMFI's official `amc_website` field (authoritative). Fallback: curated `KNOWN_DOMAINS` map, else `www.{slug}mf.com` guess. No scheme, no `www.`. |
| `sitemap_url` | string | Site's sitemap, discovered at seed time: `robots.txt` `Sitemap:` directive first, then probes of `/sitemap.xml`, `/sitemap_index.xml`, `/sitemap`, `/site-map`. When nothing verifies, holds the conventional `/sitemap.xml` guess. |
| `sitemap_type` | string | `"xml"` (machine sitemap) or `"html"` (human sitemap page, e.g. taurusmutualfund.com/sitemap) — Phase 2 parses each differently. |
| `sitemap_verified` | boolean | `true` = URL answered 200 with plausible content over plain HTTP. `false` = probe failed (often WAF/bot-block, e.g. hdfcfund.com 403s non-browser clients) — Phase 2 must re-probe with headless Chromium. |

Example object (live path):

```json
{
  "amc_id": 64,
  "firm_name": "PPFAS Mutual Fund",
  "legal_name": "PPFAS Asset Management Pvt. Ltd.",
  "clean_name": "PPFAS",
  "base_domain": "amc.ppfas.com",
  "sitemap_url": "https://amc.ppfas.com/sitemap.xml",
  "sitemap_type": "xml",
  "sitemap_verified": true
}
```

## `data/amc_page_inventory.json` (Phase 2 output)

JSON array, one object per AMC:

| Field | Type | Meaning |
|---|---|---|
| `amc_id` / `firm_name` / `base_domain` | — | Carried from the seed list. |
| `canonical_host` | string | Host the sitemap actually resolved to (post-redirect); URLs are filtered against this, not `base_domain`. Differs when the AMFI domain redirects (pgimindiamf.com → pgimindia.com). |
| `source` | string | How URLs were obtained: `sitemap_xml`, `sitemap_index`, `sitemap_html`, `homepage_anchors`, `unreachable`, `error`. |
| `discovered_total` | integer | Raw URL count found (pre-classification, capped 2000). |
| `team_urls` | string[] | Discovered URLs whose path matches team/management/leadership patterns, resolved to final destinations. |
| `scheme_urls` | string[] | Discovered URLs whose path marks a fund/scheme page (manager→fund mapping lives here). |

## `data/fund_managers.csv` (Phase 3 output)

One row per (AMC, manager). Columns:

| Column | Meaning |
|---|---|
| `firm_name` | AMC name (from the seed list). |
| `manager_name` | Extracted person name. |
| `designation` | Role label found next to the name (Fund Manager, CIO, …). |
| `email` | Personal email if found on the page, else an on-domain generic (service@/info@), else blank — most AMCs don't publish per-manager emails. |
| `location` | Best-effort HQ city (Indian-city match near an office/address cue). |
| `source_url` | The team page the row was extracted from. |

Heuristic output — expect some misses and the occasional heading picked up as a name. An LLM pass would tighten it.

## `data/fund_managers_enriched.csv` (Phase 4 output)

Phase 3 columns plus:

| Column | Meaning |
|---|---|
| `email_source` | Where a verified `email` came from: `amc_page`, `hunter`, `smtp`, or blank. |
| `email_guess` | Most-likely corporate pattern (`first.last@domain`). A guess — never verified, kept separate from `email`. |
| `linkedin_url` | Profile URL from a web search (stored, not scraped). Sparse in scrape mode (Bing throttles); full coverage with a configured search backend. |

Env toggles: `SEARXNG_URL` (self-hosted search, recommended), `ANTHROPIC_API_KEY` (web_search backend), `SERPAPI_KEY` (hosted search), `HUNTER_API_KEY` (verified emails), `VERIFY_SMTP=1` (SMTP RCPT check, needs dnspython).

## Source of a run (logged, not stored in the file)

- `live_payload` — extracted from the members page's embedded hydration JSON (has `mf_id`, `legal_name`, official websites). Normal case; yields ~55 records as of July 2026, including not-yet-launched members (e.g. ASK, Lakshya) that have no website and get a slug guess.
- `live_dom_scan` — payload extraction failed; names scraped from rendered DOM text, domains resolved via `KNOWN_DOMAINS`.
- `static_fallback` — live scrape unusable; embedded 49-name roster used.
