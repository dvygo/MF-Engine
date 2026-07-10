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

## Source of a run (logged, not stored in the file)

- `live_payload` — extracted from the members page's embedded hydration JSON (has `mf_id`, `legal_name`, official websites). Normal case; yields ~55 records as of July 2026, including not-yet-launched members (e.g. ASK, Lakshya) that have no website and get a slug guess.
- `live_dom_scan` — payload extraction failed; names scraped from rendered DOM text, domains resolved via `KNOWN_DOMAINS`.
- `static_fallback` — live scrape unusable; embedded 49-name roster used.
