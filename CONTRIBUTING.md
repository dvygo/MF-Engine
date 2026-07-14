# Contributing to MF-Engine

Thanks for your interest in improving MF-Engine. This guide covers how to set up, the principles the pipeline is built on, and how to get a change merged.

## Ways to contribute

- **Report a bug** — a phase crashes, misparses a site, or produces wrong data.
- **Add / fix an AMC mapping** — a new fund house, a moved domain, a better `KNOWN_DOMAINS` entry, or a hand-verified `linkedin_overrides.json` profile.
- **Improve a phase** — better sitemap classification, extraction heuristics, WAF handling, a new search backend.
- **Refactor** — simplify or speed up existing code without changing behavior.
- **Tests & docs** — coverage for parsing/classification logic, or clearer context docs and diagrams.

Small, focused pull requests are far easier to review and merge than large ones. When in doubt, open an issue first to discuss the approach.

## Project principles (please read)

These are load-bearing. A change that violates them will be sent back regardless of how well it works:

1. **Never fabricate a URL.** Only crawl URLs a site actually publishes — sitemap `<loc>` entries, on-page anchors, robots.txt — followed through redirects to their real destination. Pattern-matching may *classify* discovered URLs (team page vs scheme page); it must never *construct* them (no `https://{domain}/fund-managers` templates).
2. **Degrade gracefully, never emit empty output.** If a live scrape fails or looks wrong, fall back (static roster, canonical-host retry, etc.) and log which path ran. A phase should always produce a usable output file.
3. **Never assert guessed data as fact.** Guessed emails go in `email_guess`, never `email`. Search results are name-matched before they're stored — a wrong LinkedIn URL must never land in the dataset.
4. **Public data only.** Read what sites publish. Don't scrape authenticated pages (e.g. LinkedIn profile bodies), bypass logins, or defeat protections beyond standard headless rendering. Respect `robots.txt` intent and site Terms of Service.

## Development setup

```bash
git clone git@github.com:dvygo/MF-Engine.git
cd MF-Engine
python -m venv .venv && . .venv/Scripts/activate   # or source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Run a phase to confirm your environment works:

```bash
python main.py            # writes data/amc_seed_list.json
```

## Branching & commits

- Branch off `main` with a prefixed, lowercase-hyphenated name: `fix/`, `feat/`, or `issue/`.
  - e.g. `feat/serper-search-backend`, `fix/pgim-canonical-host`
- Write [Conventional Commits](https://www.conventionalcommits.org/): `type: summary` (`feat`, `fix`, `refactor`, `docs`, `chore`). Keep the subject ≤ ~72 chars; use the body to explain **why**.

## Before you open a PR

Run the checks relevant to your change:

```bash
python -m py_compile main.py phase2_discover.py phase3_extract.py phase4_enrich.py
```

- **Exercise the affected phase end-to-end** and confirm the output file is well-formed (don't just rely on a compile). If you touched Phase 2 classification, run it and spot-check `amc_page_inventory.json`.
- If your change alters output schema or behavior, **update `context/data-schema.md` and `context/pipeline-phases.md`** to match.
- Match the surrounding code style: PEP 8, type hints on new functions, comments that explain *why* not *what*.

## Pull request checklist

Copy this into your PR (the template does it for you):

- [ ] Linked to an issue (`Fixes #123`) where applicable
- [ ] `py_compile` passes on changed files
- [ ] Affected phase was run end-to-end and output verified
- [ ] Respects the four project principles above
- [ ] Docs (`context/`, `README.md`) updated if behavior/schema changed
- [ ] Self-reviewed the diff; considered edge cases (bot-blocked sites, empty results, redirects)

## AI-assisted contributions

AI tools are welcome here — this project was largely built with one. But:

- **You own every line you submit.** Read, understand, and be able to explain each change as if you wrote it by hand.
- **Disclose AI assistance** in the PR (the template has a checkbox). This isn't a mark against you; it tells reviewers to look extra hard at plausible-but-wrong details (fabricated URLs, invented API fields, hallucinated function names).
- **Verify against reality**, not the model's confidence — run the code, check the output, confirm any API/field names against real docs.

## Reporting security issues

Do **not** open a public issue for vulnerabilities. See [SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contributions are licensed under the project's [Apache License 2.0](LICENSE).
