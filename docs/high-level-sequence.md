# High-Level Sequence Diagrams

## Full pipeline run (all phases, target state)

```mermaid
sequenceDiagram
    actor U as User
    participant DC as docker compose
    participant S as scraper container
    participant AMFI as amfiindia.com
    participant AMC as AMC websites
    participant V as vLLM (Qwen)
    participant M as MinIO
    participant Q as Qdrant

    U->>DC: docker compose up -d minio vllm qdrant
    U->>DC: docker compose run --rm scraper
    DC->>S: build image (cached) + fresh container
    S->>AMFI: render members directory (headless Chromium)
    AMFI-->>S: hydration payload: ~55 AMCs with official websites
    S->>S: clean names, derive domains (official first, map/guess fallback)
    S-->>U: data/amc_seed_list.json (container exits, --rm deletes)

    Note over S,AMC: Phase 2 — per seed record
    S->>AMC: crawl base_domain, locate team page
    AMC-->>S: verified team_url

    Note over S,Q: Phase 3 + 4 — per team page
    S->>AMC: render team page
    AMC-->>S: HTML
    S->>M: put raw HTML (dated, immutable)
    S->>V: markdown + extraction prompt
    V-->>S: structured manager JSON
    S->>M: put extracted JSON (dated)
    S->>Q: upsert profile vectors (latest state)
```

## User query via chat (Phase 5, RAG target state)

```mermaid
sequenceDiagram
    actor U as User
    participant W as Open WebUI :3000
    participant E as embedding model
    participant Q as Qdrant :6333
    participant V as vLLM / Qwen :8000

    U->>W: "small cap value manager in Chennai?"
    W->>E: embed query text
    E-->>W: query vector
    W->>Q: cosine top-k search
    Q-->>W: matching manager profiles (payloads)
    W->>V: question + retrieved profiles (RAG prompt)
    V-->>W: readable answer citing profiles
    W-->>U: answer
    Note over U,V: today only U->>W->>V plain chat works;<br/>E and Q wiring lands with Phase 5
```
