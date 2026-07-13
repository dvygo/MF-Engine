# MF-Engine

Pipeline that extracts fund-manager data from India's ~55 AMFI-member Asset Management Companies (AMCs). The AMFI members directory (https://www.amfiindia.com/aboutamfi?tab=members — note: `/members` is a 404) is the source of truth for which AMCs exist. Phase 1 (implemented, `main.py`) scrapes that directory, resolves each AMC's corporate domain, and emits the crawler seed list `data/amc_seed_list.json`. Later phases crawl each AMC's site for team pages, extract fund-manager profiles, and persist to a MinIO data lake.

Read the `context/` docs before working on pipeline logic:

- `context/project-overview.md` — mission and data source
- `context/pipeline-phases.md` — what each phase does and its status
- `context/data-schema.md` — seed-list JSON schema

## Stack

- Python 3.11+, async-first (`asyncio`)
- Crawl4AI (`AsyncWebCrawler`) on Playwright/Chromium for JS-rendered pages
- BeautifulSoup for DOM parsing
- Docker + compose (`docker/docker-compose.yml`): scraper image, MinIO :9000 (Phase 4 persistence), vLLM :8000 serving Qwen2.5-3B-Instruct-AWQ (Phase 3 extraction — sized for the dev machine's RTX 3050 6GB VRAM), Open WebUI :3000 (chat UI for prompt testing), Qdrant :6333 (future semantic search)

## Commands

Local run:

```bash
pip install -r requirements.txt
playwright install chromium   # one-time browser download
python main.py                # Phase 1: writes data/amc_seed_list.json
python phase2_discover.py     # Phase 2: writes data/amc_page_inventory.json
python phase3_extract.py      # Phase 3: writes data/fund_managers.csv
```

Docker (scraper image only):

```bash
docker build -t mf-engine .
docker run -v ./data:/app/data mf-engine
```

Full stack (MinIO + vLLM/Qwen + scraper) — compose lives in `docker/`:

```bash
cd docker
cp .env.example .env        # set real creds first
docker compose up -d minio vllm open-webui qdrant
docker compose run --rm scraper   # one-shot; writes ../data/amc_seed_list.json
```

The Dockerfile packages `main.py` into the scraper image; compose builds/runs that image — `main.py` never invokes Docker itself. vLLM needs an NVIDIA GPU exposed to Docker; model/context are tuned for 6GB VRAM via `VLLM_MODEL` / `VLLM_MAX_MODEL_LEN` in `.env`.

## Conventions

- One self-contained script per pipeline phase; `main.py` is Phase 1.
- All network work goes through Crawl4AI's async context manager (`async with AsyncWebCrawler(...)`), driven by `asyncio.run(main())`.
- Scrapers must degrade gracefully: if a live scrape fails or looks wrong, fall back to embedded static data and log which path ran — never emit an empty output file.
- JSON outputs go to `data/` (gitignored), written with `indent=2`.
- Domain knowledge lives in `KNOWN_DOMAINS` in `main.py`; add new AMC mappings there rather than relying on the slug-guess fallback.
