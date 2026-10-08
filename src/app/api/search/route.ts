import { NextRequest, NextResponse } from "next/server";
import indexData from "@data/search_index.json";
import type { IndexFile } from "@/lib/types";
import { search, searchAll } from "@/lib/search/engine";
import { csvCell } from "@/lib/search/normalize";

const index = indexData as unknown as IndexFile;

function params(sp: URLSearchParams) {
  const num = (k: string) => (sp.get(k) && !Number.isNaN(Number(sp.get(k))) ? Number(sp.get(k)) : undefined);
  return {
    q: (sp.get("q") ?? "").slice(0, 200),
    year: num("year"),
    therapy: sp.get("therapy") || undefined,
    decision: sp.get("decision") || undefined,
    company: sp.get("company") || undefined,
    recentDays: num("recentDays"),
    sort: sp.get("sort") === "date" ? ("date" as const) : sp.get("sort") === "relevance" ? ("relevance" as const) : undefined,
    page: num("page"),
    pageSize: num("pageSize"),
  };
}

export async function GET(req: NextRequest) {
  const p = params(req.nextUrl.searchParams);
  if (req.nextUrl.searchParams.get("format") === "csv") {
    const cols = ["date", "drug", "company", "indication", "recommendation", "decision", "therapy", "drugType", "sourceUrl", "linkKind"] as const;
    const rows = searchAll(index, p).map((r) => cols.map((c) => csvCell(r[c])).join(","));
    return new NextResponse("\uFEFF" + [cols.join(","), ...rows].join("\r\n"), {
      headers: { "content-type": "text/csv; charset=utf-8", "content-disposition": 'attachment; filename="cdsco-results.csv"' },
    });
  }
  return NextResponse.json({ ...search(index, p), meta: index.meta });
}
