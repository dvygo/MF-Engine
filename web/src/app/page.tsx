"use client";

import MiniSearch from "minisearch";
import { useEffect, useMemo, useState } from "react";

type Row = {
  k: "firm" | "manager";
  n: string;
  role?: string;
  firm?: string;
  t?: string;
  r?: string;
  cp?: string;
  e?: string;
  ph?: string;
  w?: string;
  li?: string;
  p?: string;
  c?: string;
  d?: string;
  s?: string;
  lat?: number;
  lon?: number;
  tags?: string;
};

type Place = { name: string; kind: string; n: number };

type Manifest = {
  generated: string;
  total_rows: number;
  shards: { file: string; rows: number; hash: string }[];
};

const PLACES_SHARD = "places.json";

const TYPE_LABELS: Record<string, string> = {
  "mutual-funds": "Mutual Fund",
  "portfolio-managers": "PMS",
  aif: "AIF",
  "investment-advisers": "RIA",
};

const PAGE_SIZE = 50;

export default function Home() {
  const [rows, setRows] = useState<Row[]>([]);
  const [places, setPlaces] = useState<Place[]>([]);
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("all");
  const [type, setType] = useState("all");
  const [state, setState] = useState("all");
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [loading, setLoading] = useState(true);

  // The data ships as one shard per dataset. Each shard's content hash comes
  // from the manifest and rides along as ?v=<hash>, so re-scraping (say) AIF
  // busts only that file — every other shard stays in the browser cache.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const manifest: Manifest = await (
          await fetch("/data/manifest.json", { cache: "no-cache" })
        ).json();
        const loaded = await Promise.all(
          manifest.shards.map(async (s) => ({
            file: s.file,
            data: await fetch(`/data/${s.file}?v=${s.hash}`).then((r) => r.json()),
          })),
        );
        if (cancelled) return;
        setRows(
          loaded.filter((s) => s.file !== PLACES_SHARD).flatMap((s) => s.data as Row[]),
        );
        setPlaces(
          (loaded.find((s) => s.file === PLACES_SHARD)?.data as Place[]) ?? [],
        );
      } catch {
        if (!cancelled) setRows([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Index once, in the browser. ~3.9k rows is small enough to search entirely
  // client-side — no database, no API, no round-trip per keystroke.
  const index = useMemo(() => {
    if (!rows.length) return null;
    const mini = new MiniSearch({
      fields: ["n", "firm", "role", "tags", "r", "e", "w", "cp"],
      storeFields: [],
      searchOptions: {
        combineWith: "AND",
        // Fuzzy/prefix help on names, but on a pincode they're actively wrong:
        // "400051" would fuzzy-match 400052, 400053… and prefix-match 4000519.
        // Numeric terms must be exact.
        prefix: (term) => !/^\d+$/.test(term),
        fuzzy: (term) => (/^\d+$/.test(term) ? false : 0.2),
      },
    });
    mini.addAll(rows.map((r, id) => ({ ...r, id })));
    return mini;
  }, [rows]);

  const states = useMemo(
    () => [...new Set(rows.map((r) => r.s).filter(Boolean))].sort() as string[],
    [rows],
  );

  // Suggestions come from the small, clean places corpus — not the main index.
  // MiniSearch's autoSuggest spans every field, so it offers firm-name noise
  // ("delightfinancial delight") instead of "Delhi".
  const placeIndex = useMemo(() => {
    if (!places.length) return null;
    const mini = new MiniSearch({
      fields: ["name"],
      storeFields: ["name", "n"],
      searchOptions: { fuzzy: 0.4, prefix: true },
    });
    mini.addAll(places.map((p, id) => ({ ...p, id })));
    return mini;
  }, [places]);

  // Best place match for a typo, e.g. "deli" -> "Delhi", "banglore" -> "Bangalore".
  // Boost by how many records sit in a place: BM25 alone rewards rare terms, so
  // "banglore" would otherwise suggest Mangalore (3 records) over Bangalore (443).
  const suggestion = useMemo(() => {
    const q = query.trim();
    if (!q || !placeIndex) return null;
    const hit = placeIndex.search(q, {
      boostDocument: (_id, _term, stored) =>
        Math.log10(((stored?.n as number) ?? 1) + 10),
    })[0] as unknown as { name: string } | undefined;
    if (!hit || hit.name.toLowerCase() === q.toLowerCase()) return null;
    return hit.name;
  }, [query, placeIndex]);

  const results = useMemo(() => {
    let out: Row[] = rows;
    if (query.trim() && index) {
      out = index.search(query).map((h) => rows[h.id as number]);
    }
    if (kind !== "all") out = out.filter((r) => r.k === kind);
    if (type !== "all") out = out.filter((r) => r.t === type);
    if (state !== "all") out = out.filter((r) => r.s === state);
    return out;
  }, [rows, index, query, kind, type, state]);

  useEffect(() => setLimit(PAGE_SIZE), [query, kind, type, state]);

  return (
    <main className="mx-auto max-w-6xl px-4 py-10">
      <header className="mb-6">
        <h1 className="text-3xl font-bold tracking-tight">
          India Fund &amp; Wealth Manager Search
        </h1>
        <p className="mt-2 text-sm text-neutral-600 dark:text-neutral-400">
          {loading
            ? "Loading…"
            : `${rows.length.toLocaleString()} records — SEBI-registered firms (AMC · PMS · AIF · RIA) and the fund managers who run the money. Public sources only.`}
        </p>
      </header>

      <div className="sticky top-0 z-10 -mx-4 mb-6 border-b border-neutral-200 bg-white/90 px-4 py-4 backdrop-blur dark:border-neutral-800 dark:bg-black/90">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search name, firm, city, pincode, reg no…  e.g. bangalore · 400051 · Naren"
          className="w-full rounded-lg border border-neutral-300 bg-white px-4 py-3 text-base outline-none focus:border-neutral-900 dark:border-neutral-700 dark:bg-neutral-900 dark:focus:border-neutral-300"
        />
        <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
          <Select
            value={kind}
            onChange={setKind}
            options={[
              ["all", "Everything"],
              ["firm", "Firms"],
              ["manager", "Managers"],
            ]}
          />
          <Select
            value={type}
            onChange={setType}
            options={[["all", "All types"], ...Object.entries(TYPE_LABELS)]}
          />
          <Select
            value={state}
            onChange={setState}
            options={[
              ["all", "All states"],
              ...states.map((s) => [s, s] as [string, string]),
            ]}
          />
          <span className="ml-auto text-neutral-500">
            {results.length.toLocaleString()} result
            {results.length === 1 ? "" : "s"}
          </span>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-neutral-300 text-left dark:border-neutral-700">
              <Th>Name</Th>
              <Th>Type</Th>
              <Th>Firm / Role</Th>
              <Th>Location</Th>
              <Th>Contact</Th>
            </tr>
          </thead>
          <tbody>
            {results.slice(0, limit).map((r, i) => (
              <tr
                key={`${r.n}-${i}`}
                className="border-b border-neutral-100 align-top dark:border-neutral-900"
              >
                <td className="py-3 pr-3 font-medium">
                  {r.n}
                  {r.r && (
                    <div className="font-mono text-xs text-neutral-500">{r.r}</div>
                  )}
                </td>
                <td className="py-3 pr-3">
                  <span className="whitespace-nowrap rounded bg-neutral-100 px-2 py-0.5 text-xs dark:bg-neutral-800">
                    {r.k === "manager" ? "Manager" : (TYPE_LABELS[r.t ?? ""] ?? "Firm")}
                  </span>
                </td>
                <td className="py-3 pr-3 text-neutral-600 dark:text-neutral-400">
                  {r.firm ?? r.cp ?? "—"}
                  {r.role && <div className="text-xs text-neutral-500">{r.role}</div>}
                </td>
                <td className="py-3 pr-3 text-neutral-600 dark:text-neutral-400">
                  {r.c ?? "—"}
                  <div className="text-xs text-neutral-500">
                    {[r.d !== r.c ? r.d : null, r.s, r.p].filter(Boolean).join(" · ")}
                  </div>
                </td>
                <td className="py-3 text-xs">
                  {r.e && (
                    <a
                      href={`mailto:${r.e}`}
                      className="block text-blue-600 hover:underline dark:text-blue-400"
                    >
                      {r.e}
                    </a>
                  )}
                  {r.w && (
                    <a
                      href={`https://${r.w}`}
                      target="_blank"
                      rel="noreferrer"
                      className="block text-blue-600 hover:underline dark:text-blue-400"
                    >
                      {r.w}
                    </a>
                  )}
                  {r.li && (
                    <a
                      href={r.li}
                      target="_blank"
                      rel="noreferrer"
                      className="block text-blue-600 hover:underline dark:text-blue-400"
                    >
                      LinkedIn
                    </a>
                  )}
                  {r.ph && <span className="text-neutral-500">{r.ph}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {!loading && !results.length && (
          <div className="py-16 text-center">
            <p className="text-neutral-500">
              None found{query ? ` for “${query}”` : ""}.
            </p>
            {suggestion && (
              <button
                onClick={() => setQuery(suggestion)}
                className="mt-2 text-sm text-blue-600 hover:underline dark:text-blue-400"
              >
                Did you mean <strong>{suggestion}</strong>?
              </button>
            )}
          </div>
        )}
        {results.length > limit && (
          <button
            onClick={() => setLimit((l) => l + PAGE_SIZE)}
            className="mx-auto mt-6 block rounded-lg border border-neutral-300 px-5 py-2 text-sm hover:bg-neutral-50 dark:border-neutral-700 dark:hover:bg-neutral-900"
          >
            Show more ({(results.length - limit).toLocaleString()} left)
          </button>
        )}
      </div>

      <footer className="mt-16 border-t border-neutral-200 pt-6 text-xs text-neutral-500 dark:border-neutral-800">
        Built by{" "}
        <a
          href="https://github.com/dvygo/Fund-Manager-Web-Scraper"
          className="underline"
        >
          MF-Engine
        </a>{" "}
        from public sources: AMFI, SEBI registered-intermediary directories, AMC
        websites, GeoNames pincodes. Contact details are as published by SEBI.
      </footer>
    </main>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="py-2 pr-3 font-semibold text-neutral-500">{children}</th>;
}

function Select({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: [string, string][];
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded-lg border border-neutral-300 bg-white px-3 py-1.5 dark:border-neutral-700 dark:bg-neutral-900"
    >
      {options.map(([v, label]) => (
        <option key={v} value={v}>
          {label}
        </option>
      ))}
    </select>
  );
}
