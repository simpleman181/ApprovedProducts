import assert from "node:assert/strict";
import indexData from "../data/search_index.json";
import type { IndexFile } from "../src/lib/types";
import { search, parseQuery } from "../src/lib/search/engine";

const idx = indexData as unknown as IndexFile;
const names = (q: string, extra = {}) => search(idx, { q, ...extra }).results.map((r) => r.drug);

// exact + brand synonym + typo + prefix
assert.ok(names("semaglutide")[0].toLowerCase().startsWith("semaglutide"));
assert.ok(names("ozempic")[0].toLowerCase().startsWith("semaglutide"), "brand -> INN");
assert.ok(names("semaglutid")[0].toLowerCase().startsWith("semaglutide"), "prefix");
assert.ok(names("trastuzmab")[0].toLowerCase().startsWith("trastuzumab"), "typo");

// natural-language query -> therapy + year filters, no text terms
const r = search(idx, { q: "oncology drugs approved in 2026" });
assert.deepEqual(r.interpretation.years, [2026]);
assert.equal(r.interpretation.therapy, "Oncology");
assert.ok(r.total >= 2 && r.results.every((x) => x.therapy.includes("Oncology") && x.year === 2026));

// decision phrases
const nr = search(idx, { q: "not recommended" });
assert.ok(nr.total >= 1 && nr.results.every((x) => x.decision === "Not recommended"));
assert.ok(search(idx, { q: "trastuzumab SEC recommendation" }).results[0].drug.toLowerCase().startsWith("trastuzumab"));

// AND semantics + partial fallback
assert.equal(search(idx, { q: "tadalafil dapoxetine" }).partial, false);
const p = search(idx, { q: "tadalafil nonexistentzzz" });
assert.equal(p.partial, true); assert.ok(p.total >= 1);

// explicit filters + facets + pagination
const f = search(idx, { therapy: "Urology & Nephrology", pageSize: 2 });
assert.ok(f.results.length <= 2 && f.total >= 3);
assert.ok(f.facets.year.some((y) => y.value === "2026"));
assert.equal(search(idx, { q: "", year: 1999 }).total, 0);
assert.equal(parseQuery("xy").terms.length, 1);
console.log("search tests passed:", idx.meta.count, "records");
