#!/usr/bin/env python3
"""Replay CDSCO's own data requests and save the raw responses (gzipped envelopes).

Modes:
  --mode incremental   current month + previous N months (default; used by the weekly job)
  --mode backfill      every month from --from-year to today; skips finished months already on disk
Parameters (searchText/year/month/drugTypeValue) mirror the real XHR. If plain HTTP returns zero
records, a headless browser (Playwright) loads the same URL as a fallback.
Exit code 3 if every request came back empty (so the scheduled job fails loudly).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from common import BASE, ENDPOINTS, RAW, UA, parse_body, write_raw  # noqa: E402

VERIFY = os.environ.get("CDSCO_VERIFY_SSL", "1") != "0"
if not VERIFY:
    import urllib3
    urllib3.disable_warnings()


class Fetcher:
    def __init__(self, delay: float, use_browser: bool):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept": "*/*", "X-Requested-With": "XMLHttpRequest"})
        self.delay, self.use_browser = delay, use_browser
        self._pw = self._browser = self._ctx = None
        try:  # prime cookies
            self.s.get(BASE, timeout=30, verify=VERIFY)
        except requests.RequestException as e:
            print(f"warn: landing request failed: {e}")

    def http(self, url: str, params: dict) -> tuple[str, str, str]:
        last = None
        for attempt in range(4):
            try:
                r = self.s.get(url, params=params, timeout=45, verify=VERIFY)
                if r.status_code == 200:
                    return r.text, r.headers.get("content-type", ""), r.url
                last = f"HTTP {r.status_code}"
            except requests.RequestException as e:
                last = str(e)
            time.sleep(2 ** attempt)
        raise RuntimeError(last)

    def browser(self, url: str, params: dict) -> tuple[str, str, str]:
        from urllib.parse import urlencode
        from playwright.sync_api import sync_playwright
        if self._browser is None:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch()
            self._ctx = self._browser.new_context(user_agent=UA, ignore_https_errors=not VERIFY)
        full = f"{url}?{urlencode(params)}" if params else url
        page = self._ctx.new_page()
        try:
            resp = page.goto(full, wait_until="networkidle", timeout=90_000)
            ctype = (resp.headers.get("content-type", "") if resp else "")
            body = resp.text() if resp and "json" in ctype else page.content()
            return body, ctype, full
        finally:
            page.close()

    def close(self):
        if self._browser:
            self._browser.close()
            self._pw.stop()


def periods(args):
    now = datetime.now(timezone.utc)
    if args.mode == "incremental":
        y, m = now.year, now.month
        for _ in range(args.months_back + 1):
            yield y, m
            m -= 1
            if m == 0:
                y, m = y - 1, 12
    else:
        for y in range(args.from_year, now.year + 1):
            for m in range(1, 13):
                if (y, m) <= (now.year, now.month):
                    yield y, m


def is_recent(y: int, m: int) -> bool:
    now = datetime.now(timezone.utc)
    return (now.year * 12 + now.month) - (y * 12 + m) <= 2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["incremental", "backfill"], default="incremental")
    ap.add_argument("--from-year", type=int, default=2022)
    ap.add_argument("--months-back", type=int, default=2)
    ap.add_argument("--drug-types", default="", help="comma list of drugTypeValue values; blank = all")
    ap.add_argument("--delay", type=float, default=1.5)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--month-format", choices=["number", "name"], default="number",
                    help="how the 'month' parameter is sent; confirm with discover.py")
    args = ap.parse_args()

    f = Fetcher(args.delay, not args.no_browser)
    types = args.drug_types.split(",") if args.drug_types else [""]
    month_names = ["January", "February", "March", "April", "May", "June", "July", "August",
                   "September", "October", "November", "December"]
    jobs, ok, empty, failed = 0, 0, 0, 0

    def run(endpoint: str, params: dict, tag: str, overwrite: bool):
        nonlocal jobs, ok, empty, failed
        path = RAW / f"{tag}.json.gz"
        if path.exists() and not overwrite:
            return
        jobs += 1
        url = BASE + ENDPOINTS[endpoint]
        via, body, ctype, final = "http", "", "", url
        try:
            body, ctype, final = f.http(url, params)
        except Exception as e:  # noqa: BLE001
            print(f"  http failed ({e})")
        n = len(parse_body(body, ctype)) if body else 0
        if n == 0 and f.use_browser:
            try:
                body, ctype, final = f.browser(url, params)
                via, n = "browser", len(parse_body(body, ctype))
            except Exception as e:  # noqa: BLE001
                print(f"  browser failed ({e})")
        if not body:
            failed += 1
            print(f"FAIL  {tag}")
            return
        write_raw(path, {"endpoint": endpoint, "params": params, "url": final, "via": via, "records_found": n,
                         "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                         "content_type": ctype, "body": body})
        ok += n > 0
        empty += n == 0
        print(f"{'ok   ' if n else 'EMPTY'} {tag}: {n} records via {via}")
        time.sleep(args.delay)

    # 1) "recent approvals" feed - always refreshed
    run("recent", {}, "recent_latest", overwrite=True)
    # 2) historical / monthly approvals
    for y, m in periods(args):
        for t in types:
            mval = month_names[m - 1] if args.month_format == "name" else str(m)
            params = {"searchText": "", "year": str(y), "month": mval, "drugTypeValue": t}
            tag = f"approvals_{y}_{m:02d}_{t or 'all'}"
            run("approvals", params, tag, overwrite=args.force or is_recent(y, m))
    f.close()
    print(f"\nrequests: {jobs} | with records: {ok} | empty: {empty} | failed: {failed}")
    return 3 if jobs and ok == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
