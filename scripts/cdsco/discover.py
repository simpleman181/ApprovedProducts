#!/usr/bin/env python3
"""Find out what CDSCO's page really calls. Writes data/discovery/report.md + report.json.

  python scripts/cdsco/discover.py --url <the CDSCO page you use today>

Captures every XHR/fetch the page makes (URL, method, form/JSON payload, status, content-type, body
sample), then also probes the two known endpoints directly with a few parameter shapes.
Paste report.md back to the assistant to tune collect.py (host, month format, payload fields).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from common import BASE, DATA, ENDPOINTS, UA, parse_body  # noqa: E402


def shape(body: str, ctype: str) -> dict:
    recs = parse_body(body, ctype)
    return {"records": len(recs), "sample_keys": list(recs[0].keys())[:12] if recs else [],
            "first_record": {k: str(v)[:80] for k, v in list(recs[0].items())[:8]} if recs else {}}


def capture(url: str, click: str | None) -> list[dict]:
    from playwright.sync_api import sync_playwright
    calls: list[dict] = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(user_agent=UA, ignore_https_errors=True)
        page = ctx.new_page()

        def on_response(resp):
            req = resp.request
            if req.resource_type not in ("xhr", "fetch", "document"):
                return
            try:
                body = resp.text()
            except Exception:  # noqa: BLE001
                body = ""
            ctype = resp.headers.get("content-type", "")
            calls.append({
                "method": req.method, "url": resp.url, "status": resp.status, "content_type": ctype,
                "post_data": req.post_data, "request_headers": {k: v for k, v in req.headers.items()
                                                                 if k.lower() in ("content-type", "x-requested-with", "x-csrf-token", "referer", "origin")},
                "body_sample": body[:1500], "shape": shape(body, ctype),
            })

        page.on("response", on_response)
        page.goto(url, wait_until="networkidle", timeout=90_000)
        if click:
            page.click(click)
            page.wait_for_load_state("networkidle")
        b.close()
    return calls


def probe_direct() -> list[dict]:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "X-Requested-With": "XMLHttpRequest"})
    now = datetime.now(timezone.utc)
    shapes = [
        ("approvals", {"searchText": "", "year": "", "month": "", "drugTypeValue": ""}),
        ("approvals", {"searchText": "", "year": str(now.year), "month": "", "drugTypeValue": ""}),
        ("approvals", {"searchText": "", "year": str(now.year), "month": str(now.month - 1 or 12), "drugTypeValue": ""}),
        ("approvals", {"searchText": "", "year": str(now.year), "month": "January", "drugTypeValue": ""}),
        ("recent", {}),
    ]
    out = []
    for ep, params in shapes:
        url = BASE + ENDPOINTS[ep]
        for method in ("GET", "POST"):
            try:
                r = s.request(method, url, params=params if method == "GET" else None,
                              data=params if method == "POST" else None, timeout=40, verify=False)
                out.append({"endpoint": ep, "method": method, "params": params, "status": r.status_code,
                            "content_type": r.headers.get("content-type", ""), "shape": shape(r.text, r.headers.get("content-type", "")),
                            "body_sample": r.text[:600]})
            except requests.RequestException as e:
                out.append({"endpoint": ep, "method": method, "params": params, "error": str(e)})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=BASE + ENDPOINTS["approvals"])
    ap.add_argument("--click", default=None, help="CSS/text selector of a Search button, e.g. 'text=Search'")
    args = ap.parse_args()
    out_dir = DATA / "discovery"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        calls = capture(args.url, args.click)
    except Exception as e:  # noqa: BLE001
        calls = [{"error": f"browser capture failed: {e}"}]
    direct = probe_direct()
    (out_dir / "report.json").write_text(json.dumps({"page": args.url, "captured": calls, "direct": direct}, indent=1, ensure_ascii=False), encoding="utf-8")

    md = [f"# CDSCO discovery report\n\nPage: {args.url}\nBase: {BASE}\n", "## Calls made by the page\n"]
    for c in calls:
        if "error" in c:
            md.append(f"- {c['error']}")
            continue
        md.append(f"- **{c['method']}** `{c['url']}` -> {c['status']} ({c['content_type']}) | records parsed: {c['shape']['records']} | payload: `{(c['post_data'] or '')[:200]}`")
        if c["shape"]["records"]:
            md.append(f"  - columns: {c['shape']['sample_keys']}\n  - first record: {c['shape']['first_record']}")
    md.append("\n## Direct endpoint probes\n")
    for d in direct:
        if "error" in d:
            md.append(f"- {d['method']} {d['endpoint']} {d['params']} -> ERROR {d['error']}")
        else:
            md.append(f"- {d['method']} {d['endpoint']} {d['params']} -> {d['status']} | records: {d['shape']['records']} | columns: {d['shape']['sample_keys']}")
    (out_dir / "report.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
