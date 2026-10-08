#!/usr/bin/env python3
"""Raw CDSCO responses -> normalized, deduplicated search index.

Usage:
  python scripts/cdsco/normalize.py                      # data/raw -> data/search_index.json
  python scripts/cdsco/normalize.py --raw tests/fixtures --sample   # build demo index
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).parent))
from common import BASE, DATA, ENDPOINTS, RAW, iter_raw, parse_body  # noqa: E402

TAXONOMY = json.loads((DATA / "taxonomy.json").read_text(encoding="utf-8"))
SYNONYMS = json.loads((DATA / "synonyms.json").read_text(encoding="utf-8"))["groups"]

# Column-name aliases, applied after canonicalising headers (lowercase, a-z0-9 -> "_").
ALIASES = {
    "url": ["url", "link", "document", "pdf", "file", "file_url", "download", "attachment", "href"],
    "date": ["sec_date", "meeting_date", "date_of_meeting", "approval_date", "date_of_approval", "approved_on",
             "recommendation_date", "date", "dated"],
    "drug_type": ["drug_type", "drugtype", "type_of_drug", "application_type", "drug_category", "category", "type"],
    "recommendation": ["recommendation", "recommendations", "sec_recommendation", "committee_recommendation",
                       "decision", "outcome", "status", "remarks"],
    "company": ["applicant", "applicant_name", "name_of_applicant", "company", "company_name", "firm",
                "manufacturer", "sponsor"],
    "indication": ["indication", "indications", "proposed_indication", "therapeutic_indication", "use"],
    "drug": ["drug_name", "drugname", "name_of_drug", "name_of_the_drug", "product_name", "product", "molecule",
             "new_drug", "drug", "name"],
    "subject": ["subject", "title", "description", "agenda", "details", "proposal"],
}
SUBSTR = {  # second-chance matching on header fragments
    "url": ["link", "pdf", "url"], "date": ["date"], "drug_type": ["type"],
    "recommendation": ["recommend", "decision", "remark"], "company": ["applicant", "company", "firm"],
    "indication": ["indication"], "drug": ["drug", "product", "molecule"], "subject": ["subject", "title"],
}
CLAIM_ORDER = ["url", "date", "drug_type", "recommendation", "company", "indication", "drug", "subject"]
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


# ---------- text helpers ----------
def clean(v) -> str:
    if v is None:
        return ""
    s = re.sub(r"<[^>]+>", " ", str(v))
    return re.sub(r"\s+", " ", s).strip(" \t\r\n-–—:;,")


def fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def key_of(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", fold(s))


def canon(k) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(k).lower()).strip("_")


# ---------- field mapping ----------
def map_fields(rec: dict) -> dict:
    claimed: set[str] = set()
    out: dict[str, str] = {}
    for field in CLAIM_ORDER:
        val = ""
        for a in ALIASES[field]:
            if a in rec and a not in claimed and clean(rec[a]):
                claimed.add(a)
                val = clean(rec[a])
                break
        if not val:
            for k, v in rec.items():
                if k in claimed or not clean(v):
                    continue
                if any(frag in k for frag in SUBSTR[field]):
                    claimed.add(k)
                    val = clean(v)
                    break
        out[field] = val
    return out


# ---------- dates ----------
def parse_date(s: str):
    """-> (iso_or_partial, year, month) ; any may be None. Indian dd/mm/yyyy assumed."""
    s = clean(s)
    if not s:
        return None, None, None

    def ok(y, m, d=None):
        try:
            datetime(y, m, d or 1)
            return True
        except ValueError:
            return False

    m = re.search(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b", s)
    if m and ok(int(m[3]), int(m[2]), int(m[1])):
        d, mo, y = int(m[1]), int(m[2]), int(m[3])
        return f"{y:04d}-{mo:02d}-{d:02d}", y, mo
    m = re.search(r"\b(\d{4})[./-](\d{1,2})[./-](\d{1,2})\b", s)
    if m and ok(int(m[1]), int(m[2]), int(m[3])):
        return f"{int(m[1]):04d}-{int(m[2]):02d}-{int(m[3]):02d}", int(m[1]), int(m[2])
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s-]+([A-Za-z]{3,9})[\s,.-]+(\d{4})\b", s)
    if m and m[2][:3].lower() in MONTHS and ok(int(m[3]), MONTHS[m[2][:3].lower()], int(m[1])):
        mo = MONTHS[m[2][:3].lower()]
        return f"{int(m[3]):04d}-{mo:02d}-{int(m[1]):02d}", int(m[3]), mo
    m = re.search(r"\b([A-Za-z]{3,9})[\s,.-]+(\d{4})\b", s)
    if m and m[1][:3].lower() in MONTHS:
        mo = MONTHS[m[1][:3].lower()]
        return f"{int(m[2]):04d}-{mo:02d}", int(m[2]), mo
    m = re.search(r"\b(19|20)\d{2}\b", s)
    if m:
        return m[0], int(m[0]), None
    return None, None, None


# ---------- classification ----------
def classify_decision(text: str) -> str:
    t = fold(text)
    for label in ("Not recommended", "Additional data requested", "Recommended"):
        if any(p in t for p in TAXONOMY["decisions"][label]):
            return label
    return "Other"


def classify_therapy(*texts: str) -> list[str]:
    t = " " + fold(" ".join(texts)) + " "
    hits = []
    for label, spec in TAXONOMY["therapies"].items():
        if any((re.search(rf"\b{re.escape(kw)}\b", t) if len(kw) <= 4 else kw in t) for kw in spec["keywords"]):
            hits.append(label)
    return hits[:3]


def classify_drug_type(raw_type: str, drug: str, subject: str) -> str:
    t = fold(" ".join([raw_type, subject]))
    if "+" in drug or " and " in fold(drug) and "/" in drug:
        return "Fixed-dose combination"
    for label, kws in TAXONOMY["drugTypes"].items():
        if any(k in t for k in kws):
            return label
    return clean(raw_type) or "Unspecified"


def tidy_name(s: str) -> str:
    s = clean(s)
    s = re.sub(r"\s*\+\s*", " + ", s)
    if s.isupper() and len(s) > 3:
        s = s.title()
    return s


# ---------- links ----------
def pick_document_link(links: list[str], url_field: str) -> str:
    cands = list(links or []) + ([url_field] if url_field.startswith("http") else [])
    for u in cands:
        if re.search(r"\.(pdf|docx?|xlsx?)(\?|$)", u, re.I):
            return u
    return cands[0] if cands else ""


def listing_url(ctx: dict, drug: str) -> str:
    params = dict(ctx.get("params") or {})
    params["searchText"] = drug
    endpoint = ENDPOINTS.get(ctx.get("endpoint", "approvals"), ENDPOINTS["approvals"])
    for k in ("year", "month", "drugTypeValue"):
        params.setdefault(k, "")
    return f"{BASE}{endpoint}?{urlencode(params)}"


# ---------- record ----------
def normalize_record(raw: dict, ctx: dict) -> tuple[dict | None, str | None]:
    rec = {canon(k): v for k, v in raw.items() if not str(k).startswith("_")}
    f = map_fields(rec)
    drug = tidy_name(f["drug"] or f["subject"][:120])
    if not drug:
        return None, "no drug name"
    iso, year, month = parse_date(f["date"])
    flags = []
    if not iso:
        p = ctx.get("params") or {}
        if str(p.get("year", "")).isdigit():
            year = int(p["year"])
            month = int(p["month"]) if str(p.get("month", "")).isdigit() else None
            iso = f"{year:04d}-{month:02d}" if month else str(year)
            flags.append("date_from_query")
        else:
            flags.append("no_date")
    company = tidy_name(f["company"])
    if not company:
        flags.append("no_company")
    reco = clean(f["recommendation"]) or clean(f["subject"])
    indication = clean(f["indication"])
    doc = pick_document_link(raw.get("_links", []), f["url"])
    r = {
        "drug": drug,
        "company": company,
        "date": iso,
        "year": year,
        "month": month,
        "indication": indication,
        "recommendation": reco,
        "decision": classify_decision(reco),
        "therapy": classify_therapy(indication, drug, f["subject"], reco),
        "drugType": classify_drug_type(f["drug_type"], drug, f["subject"]),
        "sourceUrl": doc or listing_url(ctx, drug),
        "linkKind": "document" if doc else "listing",
    }
    if flags:
        r["quality"] = flags
    ident = "|".join([key_of(drug), key_of(company), iso or "", key_of(reco)[:60]])
    r["id"] = hashlib.sha1(ident.encode()).hexdigest()[:12]
    return r, None


def completeness(r: dict) -> int:
    return sum(bool(r.get(k)) for k in ("company", "date", "indication", "recommendation")) + (r["linkKind"] == "document") * 2


def build(raw_dir: Path):
    best: dict[str, dict] = {}
    rejects, seen = [], 0
    for env in iter_raw(raw_dir):
        ctx = {"endpoint": env.get("endpoint", "approvals"), "params": env.get("params") or {}}
        for raw in parse_body(env.get("body", ""), env.get("content_type", "")):
            seen += 1
            r, why = normalize_record(raw, ctx)
            if r is None:
                rejects.append({"reason": why, "raw": {k: raw[k] for k in list(raw)[:6]}})
                continue
            cur = best.get(r["id"])
            if cur is None or completeness(r) > completeness(cur):
                best[r["id"]] = r
    return list(best.values()), rejects, seen


# ---------- watchlist ----------
def expand_terms(terms: list[str]) -> set[str]:
    out = {fold(t).strip() for t in terms if t.strip()}
    for g in SYNONYMS:
        if out & set(g):
            out |= set(g)
    return out


def watchlist_hits(new: list[dict], terms: list[str]) -> list[dict]:
    wanted = expand_terms(terms)
    hits = []
    for r in new:
        blob = fold(r["drug"])
        matched = sorted(t for t in wanted if t and t in blob)
        if matched:
            hits.append({**{k: r[k] for k in ("id", "drug", "company", "date", "decision", "sourceUrl")}, "matched": matched})
    return hits


# ---------- main ----------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(RAW))
    ap.add_argument("--out", default=str(DATA / "search_index.json"))
    ap.add_argument("--sample", action="store_true", help="mark index as demo data")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    records, rejects, seen = build(Path(args.raw))
    print(f"parsed {seen} raw rows -> {len(records)} unique records, {len(rejects)} rejected")
    if not records:
        print("No records produced. Check data/raw and run discover.py.", file=sys.stderr)
        return 2

    out_path = Path(args.out)
    first_seen: dict[str, str] = {}
    if out_path.exists() and not args.sample:
        old = json.loads(out_path.read_text(encoding="utf-8"))
        if not old.get("meta", {}).get("sample"):
            first_seen = {r["id"]: r.get("firstSeen", today) for r in old["records"]}
            kept = {r["id"]: r for r in old["records"]}
            for r in records:  # new run wins, but records that vanished from CDSCO are kept
                kept[r["id"]] = r
            records = list(kept.values())
    new = []
    for r in records:
        if r["id"] in first_seen:
            r["firstSeen"] = first_seen[r["id"]]
        else:
            r["firstSeen"] = today
            new.append(r)
    records.sort(key=lambda r: ((r.get("date") or ""), r["drug"]), reverse=True)

    index = {"meta": {"version": 1, "generatedAt": now.isoformat(timespec="seconds"), "count": len(records),
                      "sample": bool(args.sample)}, "records": records}
    out_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")

    cols = ["date", "drug", "company", "indication", "recommendation", "decision", "therapy", "drugType", "sourceUrl", "firstSeen"]
    with (out_path.parent / "drug_database.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for r in records:
            w.writerow([("; ".join(r[c]) if c == "therapy" else r.get(c, "")) for c in cols])

    wl_path = Path(__file__).resolve().parents[2] / "config" / "watchlist.json"
    terms = json.loads(wl_path.read_text(encoding="utf-8")).get("terms", []) if wl_path.exists() else []
    changes = {"generatedAt": index["meta"]["generatedAt"], "newCount": len(new),
               "watchlistHits": watchlist_hits(new, terms),
               "newRecords": [{k: r[k] for k in ("id", "drug", "company", "date", "decision")} for r in new[:200]]}
    (out_path.parent / "changes.json").write_text(json.dumps(changes, ensure_ascii=False, indent=1), encoding="utf-8")
    if rejects:
        (out_path.parent / "rejects.json").write_text(json.dumps(rejects[:500], ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"index: {len(records)} records ({len(new)} new, {len(changes['watchlistHits'])} watchlist hits)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
