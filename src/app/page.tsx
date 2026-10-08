"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { CdscoRecord, IndexFile } from "@/lib/types";
import type { FacetCount, Interpretation } from "@/lib/search/engine";

type Row = CdscoRecord & { score: number };
interface Resp {
  total: number; page: number; pageSize: number; partial: boolean;
  interpretation: Interpretation; results: Row[];
  facets: { year: FacetCount[]; therapy: FacetCount[]; decision: FacetCount[]; company: FacetCount[] };
  meta: IndexFile["meta"];
}
interface Filters { year: string; therapy: string; decision: string; company: string; recent: boolean; sort: string }
const EMPTY: Filters = { year: "", therapy: "", decision: "", company: "", recent: false, sort: "" };
const EXAMPLES = ["semaglutide", "oncology drugs approved in 2026", "trastuzumab SEC recommendation", "erectile dysfunction", "not recommended 2026"];

function fmtDate(d: string | null) {
  if (!d) return "Date not given";
  if (d.length === 10) return new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  if (d.length === 7) return new Date(d + "-01T00:00:00").toLocaleDateString("en-IN", { month: "short", year: "numeric" });
  return d;
}

export default function Page() {
  const [q, setQ] = useState("");
  const [f, setF] = useState<Filters>(EMPTY);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Resp | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const ready = useRef(false);

  // restore state from the URL once, so searches are shareable
  useEffect(() => {
    const sp = new URLSearchParams(window.location.search);
    setQ(sp.get("q") ?? "");
    setF({ year: sp.get("year") ?? "", therapy: sp.get("therapy") ?? "", decision: sp.get("decision") ?? "",
      company: sp.get("company") ?? "", recent: sp.get("recent") === "1", sort: sp.get("sort") ?? "" });
    setPage(Number(sp.get("page")) || 1);
    ready.current = true;
  }, []);

  const qs = useMemo(() => {
    const sp = new URLSearchParams();
    if (q.trim()) sp.set("q", q.trim());
    if (f.year) sp.set("year", f.year);
    if (f.therapy) sp.set("therapy", f.therapy);
    if (f.decision) sp.set("decision", f.decision);
    if (f.company) sp.set("company", f.company);
    if (f.recent) sp.set("recent", "1");
    if (f.sort) sp.set("sort", f.sort);
    if (page > 1) sp.set("page", String(page));
    return sp;
  }, [q, f, page]);

  useEffect(() => {
    if (!ready.current) return;
    const api = new URLSearchParams(qs);
    if (api.get("recent")) { api.delete("recent"); api.set("recentDays", "30"); }
    const ctl = new AbortController();
    const t = setTimeout(async () => {
      setLoading(true); setError("");
      try {
        const r = await fetch(`/api/search?${api}`, { signal: ctl.signal });
        if (!r.ok) throw new Error(`Search failed (${r.status})`);
        setData(await r.json());
        window.history.replaceState(null, "", qs.toString() ? `?${qs}` : window.location.pathname);
      } catch (e) {
        if ((e as Error).name !== "AbortError") setError((e as Error).message);
      } finally { setLoading(false); }
    }, 180);
    return () => { clearTimeout(t); ctl.abort(); };
  }, [qs]);

  const set = (patch: Partial<Filters>) => { setF((p) => ({ ...p, ...patch })); setPage(1); };
  const csvHref = useMemo(() => {
    const api = new URLSearchParams(qs); api.delete("page"); api.set("format", "csv");
    if (api.get("recent")) { api.delete("recent"); api.set("recentDays", "30"); }
    return `/api/search?${api}`;
  }, [qs]);
  const pages = data ? Math.max(1, Math.ceil(data.total / data.pageSize)) : 1;
  const filtered = Object.entries(f).some(([k, v]) => k !== "sort" && v);

  return (
    <main className="wrap">
      <header className="top">
        <h1>CDSCO approvals and SEC recommendations</h1>
        <p className="fresh">
          {data ? <>{data.meta.count.toLocaleString("en-IN")} records · refreshed {new Date(data.meta.generatedAt).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}</> : "Loading index…"}
        </p>
      </header>

      {data?.meta.sample && (
        <p className="banner" role="status">
          This is demo data with made-up companies. Run the refresh job (see README) to replace it with real CDSCO records.
        </p>
      )}

      <div className="searchbox">
        <input
          className="q" type="search" value={q} autoFocus
          onChange={(e) => { setQ(e.target.value); setPage(1); }}
          placeholder="Drug, company, indication — or a question like “oncology drugs approved in 2026”"
          aria-label="Search CDSCO records"
        />
        {!q && (
          <p className="examples">
            Try{" "}
            {EXAMPLES.map((ex, i) => (
              <span key={ex}><button type="button" className="linkbtn" onClick={() => setQ(ex)}>{ex}</button>{i < EXAMPLES.length - 1 ? ", " : ""}</span>
            ))}
          </p>
        )}
      </div>

      <section className="filters" aria-label="Filters">
        <Select label="Year" value={f.year} onChange={(v) => set({ year: v })} options={data?.facets.year} />
        <Select label="Therapy area" value={f.therapy} onChange={(v) => set({ therapy: v })} options={data?.facets.therapy} />
        <Select label="Decision" value={f.decision} onChange={(v) => set({ decision: v })} options={data?.facets.decision} />
        <Select label="Company" value={f.company} onChange={(v) => set({ company: v })} options={data?.facets.company} />
        <label className="check"><input type="checkbox" checked={f.recent} onChange={(e) => set({ recent: e.target.checked })} /> Added in the last 30 days</label>
        {filtered && <button type="button" className="linkbtn" onClick={() => { setF(EMPTY); setPage(1); }}>Clear filters</button>}
      </section>

      {data && (
        <div className="meta">
          <p aria-live="polite">
            <strong>{data.total.toLocaleString("en-IN")}</strong> {data.total === 1 ? "record" : "records"}
            {data.interpretation.notes.length > 0 && q && <span className="interp"> · read as {data.interpretation.notes.join(", ")}</span>}
          </p>
          <div className="meta-actions">
            <label>Sort{" "}
              <select value={f.sort} onChange={(e) => set({ sort: e.target.value })}>
                <option value="">Best match</option><option value="date">Newest first</option>
              </select>
            </label>
            {data.total > 0 && <a className="linkbtn" href={csvHref}>Download CSV</a>}
          </div>
        </div>
      )}
      {data?.partial && <p className="note">No record matches every word, so these match some of them.</p>}
      {error && <p className="error" role="alert">{error}. Check your connection and try again.</p>}

      {data && data.total === 0 && !loading && (
        <div className="empty">
          <p>No records match{q ? <> “{q}”</> : " these filters"}.</p>
          <p>Try a generic name instead of a brand, fewer words, or clear the filters.</p>
        </div>
      )}

      <div className={`list ${loading ? "busy" : ""}`}>
        {data?.results.map((r) => (
          <article key={r.id} className={`row d-${r.decision.replace(/[^a-z]/gi, "").toLowerCase()}`}>
            <div className="c-date">{fmtDate(r.date)}</div>
            <div className="c-drug">
              <h2>{r.drug}</h2>
              <p className="sub">{r.company || "Applicant not given"}{r.drugType && r.drugType !== "Unspecified" ? ` · ${r.drugType}` : ""}</p>
            </div>
            <div className="c-ind">
              {r.indication || <span className="dim">Indication not given</span>}
              {r.therapy.length > 0 && <p className="sub">{r.therapy.join(", ")}</p>}
            </div>
            <div className="c-dec">
              <strong className="dec">{r.decision}</strong>
              <p className={open === r.id ? "reco open" : "reco"}>{r.recommendation || <span className="dim">No recommendation text</span>}</p>
              {r.recommendation.length > 120 && (
                <button type="button" className="linkbtn small" onClick={() => setOpen(open === r.id ? null : r.id)}>
                  {open === r.id ? "Show less" : "Show full text"}
                </button>
              )}
            </div>
            <div className="c-src">
              <a href={r.sourceUrl} target="_blank" rel="noopener noreferrer">
                {r.linkKind === "document" ? "Open CDSCO document" : "Find on CDSCO"}
              </a>
              <p className="sub">{r.linkKind === "document" ? "Record-specific file" : "Listing filtered to this drug and period"}</p>
            </div>
          </article>
        ))}
      </div>

      {pages > 1 && (
        <nav className="pager" aria-label="Pages">
          <button type="button" disabled={page <= 1} onClick={() => { setPage(page - 1); window.scrollTo(0, 0); }}>Previous</button>
          <span>Page {page} of {pages}</span>
          <button type="button" disabled={page >= pages} onClick={() => { setPage(page + 1); window.scrollTo(0, 0); }}>Next</button>
        </nav>
      )}

      <footer className="foot">
        <p>
          Built from CDSCO’s public records. Decision labels are assigned by keyword matching on the recommendation text,
          so read the full text and confirm against the CDSCO source before relying on a record.
        </p>
      </footer>
    </main>
  );
}

function Select({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options?: FacetCount[] }) {
  const list = options ?? [];
  const withCurrent = value && !list.some((o) => o.value === value) ? [{ value, count: 0 }, ...list] : list;
  return (
    <label className="sel">
      <span>{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">All</option>
        {withCurrent.map((o) => <option key={o.value} value={o.value}>{o.value} ({o.count})</option>)}
      </select>
    </label>
  );
}
