"use client";

import MiniSearch from "minisearch";
import GitHubButton from "react-github-btn";
import { useEffect, useMemo, useState } from "react";
import { allowsKind, allowsType2, authenticate, type User } from "./users";

const REPO = "dvygo/Fund-Manager-Web-Scraper";
const REPO_URL = `https://github.com/${REPO}`;

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
  const [user, setUser] = useState<User | null>(null);
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

  // What this user is allowed to see. Cosmetic only — the shards in
  // /public/data are fetchable regardless; this just shapes the UI.
  const visible = useMemo(() => {
    if (!user) return [];
    return rows.filter(
      (r) => allowsKind(user, r.k) && (r.k === "manager" || allowsType2(user, r.t)),
    );
  }, [rows, user]);

  // Index once, in the browser. ~3.9k rows is small enough to search entirely
  // client-side — no database, no API, no round-trip per keystroke.
  const index = useMemo(() => {
    const rows = visible;
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
  }, [visible]);

  const states = useMemo(
    () => [...new Set(visible.map((r) => r.s).filter(Boolean))].sort() as string[],
    [visible],
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
    let out: Row[] = visible;
    if (query.trim() && index) {
      out = index.search(query).map((h) => visible[h.id as number]);
    }
    if (kind !== "all") out = out.filter((r) => r.k === kind);
    if (type !== "all") out = out.filter((r) => r.t === type);
    if (state !== "all") out = out.filter((r) => r.s === state);
    return out;
  }, [visible, index, query, kind, type, state]);

  useEffect(() => setLimit(PAGE_SIZE), [query, kind, type, state]);

  if (!user) return <Login onSignIn={setUser} />;

  return (
    <main className="mx-auto max-w-6xl px-4 py-10">
      <header className="mb-6">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h1 className="text-3xl font-bold tracking-tight">
            India Fund &amp; Wealth Manager Search
          </h1>
          <div className="text-xs text-neutral-500">
            {user.email}
            <button
              onClick={() => setUser(null)}
              className="ml-3 border border-neutral-300 px-2 py-1 hover:bg-neutral-50"
            >
              Sign out
            </button>
          </div>
        </div>
        <p className="mt-2 text-sm text-neutral-600">
          {loading
            ? "Loading…"
            : `${visible.length.toLocaleString()} records visible to you — SEBI-registered firms (AMC · PMS · AIF · RIA) and the fund managers who run the money. Public sources only.`}
        </p>
      </header>

      <div className="sticky top-0 z-10 -mx-4 mb-6 border-b border-neutral-200 bg-white/90 px-4 py-4 backdrop-blur">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search name, firm, city, pincode, reg no…  e.g. bangalore · 400051 · Naren"
          className="w-full border border-neutral-300 bg-white px-4 py-3 text-base outline-none focus:border-neutral-900"
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
            <tr className="border-b border-neutral-300 text-left">
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
                className="border-b border-neutral-100 align-top"
              >
                <td className="py-3 pr-3 font-medium">
                  {r.n}
                  {r.r && (
                    <div className="font-mono text-xs text-neutral-500">{r.r}</div>
                  )}
                </td>
                <td className="py-3 pr-3">
                  <span className="whitespace-nowrap bg-neutral-100 px-2 py-0.5 text-xs">
                    {r.k === "manager" ? "Manager" : (TYPE_LABELS[r.t ?? ""] ?? "Firm")}
                  </span>
                </td>
                <td className="py-3 pr-3 text-neutral-600">
                  {r.firm ?? r.cp ?? "—"}
                  {r.role && <div className="text-xs text-neutral-500">{r.role}</div>}
                </td>
                <td className="py-3 pr-3 text-neutral-600">
                  {r.c ?? "—"}
                  <div className="text-xs text-neutral-500">
                    {[r.d !== r.c ? r.d : null, r.s, r.p].filter(Boolean).join(" · ")}
                  </div>
                </td>
                <td className="py-3 text-xs">
                  {r.e && (
                    <a
                      href={`mailto:${r.e}`}
                      className="block text-blue-600 hover:underline"
                    >
                      {r.e}
                    </a>
                  )}
                  {r.w && (
                    <a
                      href={`https://${r.w}`}
                      target="_blank"
                      rel="noreferrer"
                      className="block text-blue-600 hover:underline"
                    >
                      {r.w}
                    </a>
                  )}
                  {r.li && (
                    <a
                      href={r.li}
                      target="_blank"
                      rel="noreferrer"
                      className="block text-blue-600 hover:underline"
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
                className="mt-2 text-sm text-blue-600 hover:underline"
              >
                Did you mean <strong>{suggestion}</strong>?
              </button>
            )}
          </div>
        )}
        {results.length > limit && (
          <button
            onClick={() => setLimit((l) => l + PAGE_SIZE)}
            className="mx-auto mt-6 block border border-neutral-300 px-5 py-2 text-sm hover:bg-neutral-50"
          >
            Show more ({(results.length - limit).toLocaleString()} left)
          </button>
        )}
      </div>

      <footer className="mt-16 border-t border-neutral-200 pt-6 text-xs text-neutral-500">
        {/* GitHub's own button widgets — live star / fork / issue counts,
            rendered by buttons.github.io. */}
        <div className="flex flex-wrap items-center gap-3">
          <GitHubButton
            href={REPO_URL}
            data-icon="octicon-star"
            data-size="large"
            data-show-count="true"
            aria-label={`Star ${REPO} on GitHub`}
          >
            Star
          </GitHubButton>
          <GitHubButton
            href={`${REPO_URL}/fork`}
            data-icon="octicon-repo-forked"
            data-size="large"
            data-show-count="true"
            aria-label={`Fork ${REPO} on GitHub`}
          >
            Fork
          </GitHubButton>
          <GitHubButton
            href={`${REPO_URL}/issues`}
            data-icon="octicon-issue-opened"
            data-size="large"
            data-show-count="true"
            aria-label={`Issue ${REPO} on GitHub`}
          >
            Issue
          </GitHubButton>
          <GitHubButton href={REPO_URL} data-size="large">
            View source
          </GitHubButton>
        </div>
        <p className="mt-4 max-w-3xl leading-relaxed">
          Built from public sources: AMFI, SEBI registered-intermediary
          directories, AMC websites, GeoNames pincodes. Firm contact details are
          as published by SEBI. Apache-2.0 —{" "}
          <a
            href={`${REPO_URL}/tree/main/data/csv`}
            target="_blank"
            rel="noreferrer"
            className="underline hover:text-neutral-900"
          >
            download the data as CSV
          </a>
          .
        </p>
      </footer>
    </main>
  );
}

function Login({ onSignIn }: { onSignIn: (u: User) => void }) {
  const [email, setEmail] = useState("");
  const [pass, setPass] = useState("");
  const [error, setError] = useState("");

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const u = authenticate(email, pass);
    if (u) onSignIn(u);
    else setError("Wrong email or password.");
  }

  return (
    <main className="mx-auto flex max-w-sm flex-col justify-center px-4 py-24">
      <h1 className="text-2xl font-bold tracking-tight">
        India Fund &amp; Wealth Manager Search
      </h1>
      <p className="mt-2 text-sm text-neutral-600">Sign in to continue.</p>
      <form onSubmit={submit} className="mt-6 flex flex-col gap-3">
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@brightstar-research.com"
          autoComplete="username"
          className="border border-neutral-300 px-3 py-2 outline-none focus:border-neutral-900"
        />
        <input
          type="password"
          value={pass}
          onChange={(e) => setPass(e.target.value)}
          placeholder="Password"
          autoComplete="current-password"
          className="border border-neutral-300 px-3 py-2 outline-none focus:border-neutral-900"
        />
        <button
          type="submit"
          className="border border-neutral-900 bg-neutral-900 px-3 py-2 text-sm font-medium text-white hover:bg-neutral-700"
        >
          Sign in
        </button>
        {error && <p className="text-sm text-red-600">{error}</p>}
      </form>
      <p className="mt-6 text-xs text-neutral-400">
        Demo sign-in only — it shapes what this page shows, it does not protect
        the data.
      </p>
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
      className="border border-neutral-300 bg-white px-3 py-1.5"
    >
      {options.map(([v, label]) => (
        <option key={v} value={v}>
          {label}
        </option>
      ))}
    </select>
  );
}
