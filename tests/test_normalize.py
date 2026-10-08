"""Run: python tests/test_normalize.py   (no pytest needed)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "cdsco"))
import normalize as n  # noqa: E402
from common import parse_body  # noqa: E402

def test_dates():
    assert n.parse_date("14/03/2026")[0] == "2026-03-14"
    assert n.parse_date("02-Apr-2026")[0] == "2026-04-02"
    assert n.parse_date("2026-04-02")[0] == "2026-04-02"
    assert n.parse_date("May 2026") == ("2026-05", 2026, 5)
    assert n.parse_date("31/02/2026")[0] is None or n.parse_date("31/02/2026")[1] == 2026
    assert n.parse_date("") == (None, None, None)

def test_decisions():
    assert n.classify_decision("Not recommended; justification inadequate") == "Not recommended"
    assert n.classify_decision("Firm to submit additional data") == "Additional data requested"
    assert n.classify_decision("Recommended for approval") == "Recommended"
    assert n.classify_decision("noted") == "Other"

def test_build_and_dedup():
    records, rejects, seen = n.build(Path(__file__).parent / "fixtures")
    names = sorted(r["drug"] for r in records)
    assert seen == 9, seen
    assert len(records) == 7, (len(records), names)          # duplicate FDC collapsed
    assert len(rejects) == 1 and rejects[0]["reason"] == "no drug name"
    fdc = [r for r in records if "Dapoxetine" in r["drug"]][0]
    assert fdc["linkKind"] == "document" and fdc["sourceUrl"].endswith("sec_14032026_b.pdf")  # richer duplicate wins
    assert fdc["drugType"] == "Fixed-dose combination"
    sema = [r for r in records if r["drug"].lower().startswith("semaglutide")][0]
    assert sema["decision"] == "Additional data requested" and "Diabetes & Endocrine" in sema["therapy"]
    silo = [r for r in records if r["drug"] == "Silodosin 8 mg"][0]
    assert silo["linkKind"] == "listing" and "searchText=Silodosin" in silo["sourceUrl"] and "year=2026" in silo["sourceUrl"]
    tir = [r for r in records if r["drug"].startswith("Tirzepatide")][0]      # JSON payload with different key names
    assert tir["company"] == "Example Pharma F" and tir["date"] == "2026-05-11" and tir["decision"] == "Recommended"
    pem = [r for r in records if r["drug"].startswith("Pembro")][0]
    assert "Oncology" in pem["therapy"]

def test_short_keywords_need_word_boundaries():
    assert "Urology & Nephrology" not in n.classify_therapy("Chronic weight management; submit additional data on outcomes")
    assert "Urology & Nephrology" in n.classify_therapy("recurrent UTI in adults")

def test_watchlist():
    recs, _, _ = n.build(Path(__file__).parent / "fixtures")
    hits = n.watchlist_hits(recs, ["ozempic"])      # brand name should hit INN via synonyms
    assert any("Semaglutide" in h["drug"] or "SEMAGLUTIDE" in h["drug"].upper() for h in hits), hits

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok ", name)
