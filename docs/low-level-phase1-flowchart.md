# Phase 1 Scraper (`main.py`) — Low-Level Flowchart

## Control flow

```mermaid
flowchart TD
    START(["asyncio.run(main())"]) --> FETCH["fetch_members_html()"]

    subgraph CRAWL["Crawl4AI"]
        FETCH --> BC["BrowserConfig:<br/>headless, Chrome UA, 1366x900"]
        BC --> RC["CrawlerRunConfig:<br/>CacheMode.BYPASS, wait_for css:body,<br/>delay 4s, timeout 60s"]
        RC --> ARUN["crawler.arun(AMFI_MEMBERS_URL)"]
    end

    ARUN --> OK{"result.success?"}
    OK -- "no / exception" --> NONE["html = None"]
    OK -- yes --> HTML["result.html"]

    HTML --> PAYLOAD["parse_member_payload(html)<br/>unescape + regex over hydration JSON:<br/>mf_id, mf_name, amc_name, amc_website"]
    PAYLOAD --> P20{">= 20 records?"}
    P20 -- yes --> BUILDP["build_records_from_payload<br/>official website to base_domain<br/>source=live_payload"]
    P20 -- no --> SCAN["parse_member_names(html)<br/>scan leaf nodes for<br/>'mutual fund | asset management' strings"]
    SCAN --> S20{">= 20 names?"}
    S20 -- yes --> BUILDN["build_records(names)<br/>KNOWN_DOMAINS / slug guess<br/>source=live_dom_scan"]
    S20 -- no --> STATIC["STATIC_AMC_NAMES (49)<br/>source=static_fallback"]
    NONE --> STATIC
    STATIC --> BUILDS["build_records(names)"]

    BUILDP --> WRITE["write data/amc_seed_list.json<br/>indent=2, utf-8"]
    BUILDN --> WRITE
    BUILDS --> WRITE
    WRITE --> END(["exit 0"])
```

## Domain resolution (`resolve_domain`)

```mermaid
flowchart TD
    IN["clean name, lowercased"] --> EXACT{"exact key in<br/>KNOWN_DOMAINS?"}
    EXACT -- yes --> D1["return mapped domain"]
    EXACT -- no --> PART["iterate KNOWN_DOMAINS<br/>sorted longest key first"]
    PART --> HIT{"key substring of name<br/>or name substring of key?"}
    HIT -- yes --> D2["return mapped domain<br/>(longest-first: 'quantum' beats 'quant')"]
    HIT -- no --> SLUG["slugify: strip non-alphanumerics"]
    SLUG --> GUESS["return www.{slug}mf.com<br/>+ log warning"]
```

## Name cleaning (`clean_name`)

```mermaid
flowchart LR
    RAW["raw firm name"] --> WS["collapse whitespace"]
    WS --> LOOP{"trailing legal suffix?<br/>(longest patterns first)"}
    LOOP -- "yes: strip + rstrip ' ,.-'" --> LOOP
    LOOP -- no --> OUT["core firm name"]
```
