# Phase 1 Scraper (`main.py`) — Low-Level Sequence

## Call-level sequence with failure paths

```mermaid
sequenceDiagram
    participant M as main()
    participant F as fetch_members_html()
    participant C as AsyncWebCrawler
    participant B as Chromium (Playwright)
    participant A as amfiindia.com
    participant P as parse_member_names()
    participant BS as BeautifulSoup
    participant R as build_records()
    participant FS as data/amc_seed_list.json

    M->>F: await
    F->>C: async with AsyncWebCrawler(BrowserConfig)
    C->>B: launch headless, Chrome UA
    F->>C: arun(url, CrawlerRunConfig)
    C->>B: navigate + wait_for css:body + 4s settle
    B->>A: GET /aboutamfi?tab=members
    A-->>B: JS-rendered members tab

    alt crawl succeeds
        B-->>C: DOM captured
        C-->>F: result (success, html)
        F-->>M: html
    else network drop / bot block / timeout
        C-->>F: result.success = false or exception
        F-->>M: None (logged)
    end

    opt html present
        M->>P: parse_member_payload(html)
        Note over P: unescape \" then regex the hydration JSON:<br/>mf_id, mf_name, amc_name, amc_website
        alt >= 20 payload records (normal: ~55)
            P-->>M: official records (source=live_payload)
            M->>R: build_records_from_payload(members)
            loop each member
                R->>R: base_domain = official amc_website netloc
                R->>R: no website? resolve_domain fallback
            end
        else payload extraction failed
            M->>P: parse_member_names(html)
            P->>BS: find_all leaf nodes, regex filter
            BS-->>P: candidate strings
            P-->>M: deduped names (source=live_dom_scan)
            M->>R: build_records(names)
        end
    end

    opt still no records
        M->>M: STATIC_AMC_NAMES (49, source=static_fallback)
        M->>R: build_records(names)
    end

    loop each record
        R->>R: clean_name — strip legal suffixes
    end
    R-->>M: records

    participant W as AMC websites
    M->>W: enrich_with_sitemaps — concurrent probes
    Note over M,W: robots.txt Sitemap: directive, else<br/>/sitemap.xml, /sitemap_index.xml, /sitemap, /site-map<br/>redirect-to-homepage guarded
    W-->>M: sitemap_url + type (xml/html) + verified flag

    M->>FS: mkdir data/, write JSON indent=2
    M-->>M: log count + source, exit 0
```

## One-shot container lifecycle

```mermaid
sequenceDiagram
    actor U as User
    participant DC as docker compose
    participant IMG as image cache
    participant CT as mf-scraper container
    participant VOL as ../data bind mount

    U->>DC: docker compose run --rm scraper
    DC->>IMG: build from Dockerfile (cached after first)
    DC->>CT: create fresh container
    CT->>CT: CMD python main.py
    CT->>VOL: write /app/data/amc_seed_list.json
    CT-->>DC: exit 0
    DC->>CT: --rm deletes container
    Note over VOL: JSON persists on host disk;<br/>container is gone
```
