import taxonomy from "@data/taxonomy.json";
import synonyms from "@data/synonyms.json";
import type { CdscoRecord, Decision, IndexFile } from "../types";
import { editDistance, fold, tokenize } from "./normalize";

export interface SearchParams {
  q?: string;
  year?: number;
  therapy?: string;
  decision?: string;
  company?: string;
  recentDays?: number;
  sort?: "relevance" | "date";
  page?: number;
  pageSize?: number;
}

export interface Interpretation {
  terms: string[];
  years: number[];
  therapy?: string;
  therapyToken?: string;
  decision?: Decision;
  notes: string[];
}

export interface FacetCount { value: string; count: number }
export interface SearchResult {
  total: number;
  page: number;
  pageSize: number;
  partial: boolean;
  interpretation: Interpretation;
  results: (CdscoRecord & { score: number })[];
  facets: { year: FacetCount[]; therapy: FacetCount[]; decision: FacetCount[]; company: FacetCount[] };
}

const STOP = new Set([
  "a","an","the","of","in","on","for","by","to","and","or","with","from","all","any","new","latest","recent",
  "drug","drugs","product","products","molecule","molecules","approved","approval","approvals","approve",
  "sec","recommendation","recommendations","recommend","committee","cdsco","india","company","companies",
  "show","list","find","me","get","during","since","after","before","year","years",
]);

const THERAPY_ALIASES = new Map<string, string>();
for (const [label, spec] of Object.entries(taxonomy.therapies)) {
  for (const a of spec.aliases) THERAPY_ALIASES.set(fold(a), label);
}
const SYN = new Map<string, string[]>();
for (const g of synonyms.groups) for (const t of g) SYN.set(t, g.filter((x) => x !== t));

const DECISION_PHRASES: [RegExp, Decision][] = [
  [/\bnot recommended\b|\brejected\b|\brefused\b|\bnot approved\b/, "Not recommended"],
  [/\badditional data\b|\bdeferred?\b|\bfurther data\b|\bpending\b/, "Additional data requested"],
  [/\brecommended\b/, "Recommended"],
];

export function parseQuery(q: string): Interpretation {
  let s = " " + fold(q) + " ";
  const notes: string[] = [];
  const years = [...s.matchAll(/\b(19|20)\d{2}\b/g)].map((m) => Number(m[0]));
  s = s.replace(/\b(19|20)\d{2}\b/g, " ");
  if (years.length) notes.push(`year ${years.join(", ")}`);

  let decision: Decision | undefined;
  for (const [re, d] of DECISION_PHRASES) {
    if (re.test(s)) { decision = d; s = s.replace(re, " "); notes.push(`decision “${d}”`); break; }
  }

  let therapy: string | undefined;
  let therapyToken: string | undefined;
  const terms: string[] = [];
  for (const tok of tokenize(s)) {
    const t = THERAPY_ALIASES.get(tok);
    if (t && !therapy) { therapy = t; therapyToken = tok; notes.push(`therapy area ${t}`); continue; }
    if (!STOP.has(tok)) terms.push(tok);
  }
  return { terms, years, therapy, therapyToken, decision, notes };
}

interface Doc {
  rec: CdscoRecord;
  drug: string[]; company: string[]; indication: string[]; reco: string[]; therapy: string[];
  folded: { company: string; therapy: string[] };
  ts: number;
}

const docCache = new WeakMap<IndexFile, Doc[]>();
function docs(index: IndexFile): Doc[] {
  let d = docCache.get(index);
  if (!d) {
    d = index.records.map((rec) => ({
      rec,
      drug: tokenize(rec.drug),
      company: tokenize(rec.company),
      indication: tokenize(rec.indication),
      reco: tokenize(rec.recommendation + " " + rec.drugType),
      therapy: tokenize(rec.therapy.join(" ")),
      folded: { company: fold(rec.company), therapy: rec.therapy },
      ts: rec.date ? Date.parse(rec.date.length === 4 ? rec.date + "-01-01" : rec.date.length === 7 ? rec.date + "-01" : rec.date) || 0 : 0,
    }));
    docCache.set(index, d);
  }
  return d;
}

const WEIGHTS = { drug: 5, company: 3, indication: 2, therapy: 2, reco: 1 } as const;

function fieldMatch(term: string, tokens: string[]): number {
  let best = 0;
  for (const t of tokens) {
    if (t === term) return 1;
    if (term.length >= 3 && t.startsWith(term)) best = Math.max(best, 0.8);
    else if (term.length >= 5 && best < 0.6 && editDistance(term, t, 1) <= 1) best = 0.6;
  }
  return best;
}

function termScore(term: string, d: Doc): number {
  const alts = [term, ...(SYN.get(term) ?? [])];
  let best = 0;
  for (const alt of alts) {
    const bonus = alt === term ? 1 : 0.95;
    for (const f of Object.keys(WEIGHTS) as (keyof typeof WEIGHTS)[]) {
      const m = fieldMatch(alt, d[f]);
      if (m) best = Math.max(best, m * WEIGHTS[f] * bonus);
    }
  }
  return best;
}

function count(map: Map<string, number>): FacetCount[] {
  return [...map].map(([value, count]) => ({ value, count })).sort((a, b) => b.count - a.count || a.value.localeCompare(b.value));
}

export function search(index: IndexFile, p: SearchParams): SearchResult {
  const interp = parseQuery(p.q ?? "");
  const hasTerms = interp.terms.length > 0;
  // When the query also contains text terms, a therapy word is just a term: keep it searchable.
  const therapyFilter = p.therapy || (!hasTerms ? interp.therapy : undefined);
  const years = p.year ? [p.year] : interp.years;
  const decision = p.decision || interp.decision;
  const cutoff = p.recentDays ? Date.now() - p.recentDays * 86_400_000 : 0;
  // With other text terms present, a therapy word is just another search term.
  const terms = [...interp.terms];
  if (hasTerms && interp.therapyToken && !p.therapy) terms.push(interp.therapyToken);

  type Hit = { d: Doc; score: number; matched: number };
  const scored: Hit[] = [];
  for (const d of docs(index)) {
    let score = 0, matched = 0;
    for (const t of terms) { const s = termScore(t, d); if (s > 0) { matched++; score += s; } }
    if (terms.length && matched === 0) continue;
    scored.push({ d, score, matched });
  }
  const full = scored.filter((h) => h.matched === terms.length);
  const partial = terms.length > 1 && full.length === 0;
  const textSet = partial ? scored : full;

  const passes = (d: Doc, skip?: string) =>
    (skip === "year" || !years.length || (d.rec.year != null && years.includes(d.rec.year))) &&
    (skip === "therapy" || !therapyFilter || d.rec.therapy.includes(therapyFilter)) &&
    (skip === "decision" || !decision || d.rec.decision === decision) &&
    (skip === "company" || !p.company || d.rec.company === p.company) &&
    (!cutoff || Date.parse(d.rec.firstSeen) >= cutoff);

  const facet = (key: "year" | "therapy" | "decision" | "company"): FacetCount[] => {
    const m = new Map<string, number>();
    for (const h of textSet) {
      if (!passes(h.d, key)) continue;
      const vals = key === "year" ? [String(h.d.rec.year ?? "")] : key === "therapy" ? h.d.rec.therapy : [String(h.d.rec[key] ?? "")];
      for (const v of vals) if (v) m.set(v, (m.get(v) ?? 0) + 1);
    }
    const out = count(m);
    return key === "year" ? out.sort((a, b) => Number(b.value) - Number(a.value)) : key === "company" ? out.slice(0, 40) : out;
  };

  const hits = textSet.filter((h) => passes(h.d));
  const sort = p.sort ?? (terms.length ? "relevance" : "date");
  hits.sort((a, b) => (sort === "relevance" ? b.score - a.score || b.d.ts - a.d.ts : b.d.ts - a.d.ts || b.score - a.score));

  const pageSize = Math.min(Math.max(p.pageSize ?? 25, 1), 100);
  const page = Math.max(p.page ?? 1, 1);
  const interpretation: Interpretation = { ...interp, therapy: therapyFilter, decision: decision as Decision | undefined, years, terms: interp.terms };
  return {
    total: hits.length, page, pageSize, partial, interpretation,
    results: hits.slice((page - 1) * pageSize, page * pageSize).map((h) => ({ ...h.d.rec, score: Math.round(h.score * 10) / 10 })),
    facets: { year: facet("year"), therapy: facet("therapy"), decision: facet("decision"), company: facet("company") },
  };
}

export function searchAll(index: IndexFile, p: SearchParams, cap = 5000): CdscoRecord[] {
  const out: CdscoRecord[] = [];
  for (let page = 1; out.length < cap; page++) {
    const r = search(index, { ...p, page, pageSize: 100 });
    out.push(...r.results);
    if (page * 100 >= r.total) break;
  }
  return out;
}
