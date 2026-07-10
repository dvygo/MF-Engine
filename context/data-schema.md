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
| `team_url_guess` | string | Unverified guess at the fund-managers page: `https://{base_domain}/fund-managers`. Phase 2 validates/replaces it. |

Example object (live path):

```json
{
  "amc_id": 64,
  "firm_name": "PPFAS Mutual Fund",
  "legal_name": "PPFAS Asset Management Pvt. Ltd.",
  "clean_name": "PPFAS",
  "base_domain": "amc.ppfas.com",
  "team_url_guess": "https://amc.ppfas.com/fund-managers"
}
```

## Source of a run (logged, not stored in the file)

- `live_payload` — extracted from the members page's embedded hydration JSON (has `mf_id`, `legal_name`, official websites). Normal case; yields ~55 records as of July 2026, including not-yet-launched members (e.g. ASK, Lakshya) that have no website and get a slug guess.
- `live_dom_scan` — payload extraction failed; names scraped from rendered DOM text, domains resolved via `KNOWN_DOMAINS`.
- `static_fallback` — live scrape unusable; embedded 49-name roster used.
