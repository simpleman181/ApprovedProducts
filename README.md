# CDSCO approvals and SEC recommendations search

A searchable layer over CDSCO's public approval / SEC records. Nothing runs on your laptop:
GitHub collects the data on a schedule, and Vercel serves the search site.

```
GitHub Actions (weekly)                         Vercel
CDSCO ──▶ collect.py ──▶ normalize.py ──▶ data/search_index.json ──▶ Next.js /api/search ──▶ search page
          (replays CDSCO's own requests,   (clean, dedupe, classify,   (typo-tolerant, brand↔generic,
           browser fallback)                new-record + watchlist)      plain-English filters)
```

## Set up (all in the browser, no installs)

1. **Create a GitHub repo** (e.g. `cdsco-intel`) and upload everything in this folder. Check that
   `.github/workflows/` appears in the repo; if the upload skipped it (hidden folder), use *Add file → Create new file*
   and type `.github/workflows/refresh.yml`, then paste the file contents. Repeat for `discover.yml` and `ci.yml`.
2. **Import the repo in Vercel** (Add New → Project). Defaults are correct (Next.js). It redeploys automatically
   whenever the data is refreshed.
3. In the repo, open *Settings → Actions → General → Workflow permissions* and choose **Read and write permissions**.
4. **Run discovery first.** Actions → *Discover CDSCO endpoints* → Run workflow (paste the CDSCO page you normally use).
   Open the run summary: it lists every request the page makes, its payload, and how many records parsed.
   If the host differs from `cdscoonline.gov.in`, add a repository variable `CDSCO_BASE` (Settings → Secrets and variables → Actions → Variables).
   Send me the summary and I will tune `collect.py` / `normalize.py` to the real payload.
5. **Backfill:** Actions → *Refresh CDSCO data* → Run workflow → mode `backfill`, from_year `2022`.
   Afterwards the schedule runs every Monday (last 3 months re-fetched, history untouched).
6. Edit `config/watchlist.json` with the products you monitor. New matching records open a GitHub issue, which emails you.

The site ships with **demo data** (made-up companies) so you can see it working before step 5; a banner says so, and the first real refresh replaces it.

## Files you will touch

| File | Purpose |
|---|---|
| `config/watchlist.json` | Products to flag when new records appear |
| `data/synonyms.json` | Brand ↔ generic names for search |
| `data/taxonomy.json` | Therapy areas, decision keywords, drug types (used by both Python and the site) |
| `data/rejects.json` | Rows that could not be parsed (created after a run) — check it after each refresh |

## Known limits (read these)

- **The CDSCO request format is unverified.** I could not reach CDSCO from my environment, so the collector is built to be
  tolerant (JSON or HTML-table responses, aliased column names, browser fallback) but needs one discovery run to confirm
  host, parameters and month format.
- **Decision labels are keyword-based** (Recommended / Not recommended / Additional data requested / Other). The full
  recommendation text is always shown beside it; treat the label as a filter aid, not a conclusion.
- **Source links:** where CDSCO exposes a document link, it is used ("Open CDSCO document"). Otherwise the link opens CDSCO's
  listing filtered to that drug and period ("Find on CDSCO"). The site says which one you are getting.
- Records that later disappear from CDSCO stay in the index. Use only publicly available information and respect CDSCO's terms and load (the collector waits 1.5 s between requests).

## Local development (optional, only if your IT policy allows)

`npm install && npm run dev` · tests: `python tests/test_normalize.py` and `npm test`.
Rebuild the demo index: `python scripts/cdsco/normalize.py --raw tests/fixtures --sample`.
