"""Shared helpers: paths, raw-file IO, and response parsing (JSON or HTML tables)."""
from __future__ import annotations

import gzip
import json
import os
import re
from pathlib import Path
from typing import Iterator
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"

# CONFIRM with discover.py output: the host that actually serves /CDSCO/loadDrugApprovals.
BASE = os.environ.get("CDSCO_BASE", "https://cdscoonline.gov.in").rstrip("/")
ENDPOINTS = {
    "approvals": "/CDSCO/loadDrugApprovals",
    "recent": "/CDSCO/loadRecentApprovals",
}
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


# ---------- raw envelopes ----------
def write_raw(path: Path, envelope: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(envelope, fh, ensure_ascii=False)


def iter_raw(raw_dir: Path) -> Iterator[dict]:
    """Yield envelopes: {endpoint, params, url, fetched_at, content_type, body}."""
    for p in sorted(raw_dir.rglob("*")):
        if p.suffix == ".gz":
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                yield json.load(fh)
        elif p.suffix == ".json" and p.name.startswith("env_"):
            yield json.loads(p.read_text(encoding="utf-8"))


# ---------- parsing ----------
def _flatten(v):
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v


def _find_records(data) -> list[dict]:
    """Return the largest list of dicts found anywhere in a JSON document."""
    best: list[dict] = []

    def walk(x):
        nonlocal best
        if isinstance(x, list):
            if x and all(isinstance(i, dict) for i in x) and len(x) > len(best):
                best = x
            for i in x:
                walk(i)
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)

    walk(data)
    return [{k: _flatten(v) for k, v in r.items()} for r in best]


def _text(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()


def parse_html_tables(html: str, base: str = BASE) -> list[dict]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        thead = table.find("thead")
        header_cells = thead.find_all(["th", "td"]) if thead else rows[0].find_all(["th", "td"])
        headers = [_text(c) or f"col_{i}" for i, c in enumerate(header_cells)]
        body_rows = [r for r in rows if r.find("td")] if thead else rows[1:]
        for tr in body_rows:
            cells = tr.find_all("td")
            if len(cells) < 2:
                continue
            rec = {}
            for i, c in enumerate(cells):
                key = headers[i] if i < len(headers) else f"col_{i}"
                rec[key] = _text(c)
            links = [urljoin(base + "/", a["href"]) for a in tr.find_all("a", href=True)
                     if not a["href"].lower().startswith(("javascript:", "#", "mailto:"))]
            if links:
                rec["_links"] = links
            if any(v for k, v in rec.items() if not k.startswith("_")):
                out.append(rec)
    return out


def parse_body(body: str, content_type: str = "") -> list[dict]:
    s = (body or "").lstrip()
    if s[:1] in ("[", "{"):
        try:
            return _find_records(json.loads(s))
        except json.JSONDecodeError:
            pass
    return parse_html_tables(body or "")
