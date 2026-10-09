"""test_fixture_producers.py — fs／ar fixture producer 產物契約（item 1.2）。

契約 row：
  R1: fs JSON 頁碼集合＝17 頁、每頁 lines 非空
  R2: ar JSON 頁碼集合＝1A 既有頁∪{8,57,58,59,65}、每頁 lines 非空
  R3: from_json 載回兩份 → PdfDoc、page.number 對應原頁碼
  R4: [邊界] 來源 PDF 不存在 → 明確 raise
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from runtime.tw_equity import pdf_doc as _pdf_doc  # noqa: E402
from runtime.tw_equity.doc_anchor import PageRange  # noqa: E402
from runtime.tw_equity.statements import _FS_ANCHOR_KEY, _TITLE_KW, statement_pages  # noqa: E402
from tests.fixtures.tw_equity import (  # noqa: E402
    make_ar2024_fixture,
    make_fs_fixture,
    make_fs_h1_fixture,
)

_FIX = _REPO_ROOT / "tests" / "fixtures" / "tw_equity"
_FS_PAGES = {2, 3, 5, 6, 10, 11, 12, 14, 22, 29, 31, 46, 47, 51, 55, 64, 67, 13, 15}
_AR_1A_PAGES = {3, 4, 5, 6, 65, 66, 67, 76, 81, 82, 92, 93, 94, 95, 96, 97, 98, 99}
_AR_PAGES = _AR_1A_PAGES | {8, 57, 58, 59, 65}


def _load(name: str) -> _pdf_doc.PdfDoc:
    doc = _pdf_doc.from_json(json.loads((_FIX / name).read_text(encoding="utf-8")))
    assert isinstance(doc, _pdf_doc.PdfDoc)
    return doc


@pytest.mark.parametrize(
    "name,expected",
    [("fs_3653_pages.json", _FS_PAGES), ("ar_3653_pages.json", _AR_PAGES)],
)
def test_fixture_pages_and_lines(name: str, expected: set[int]) -> None:
    doc = _load(name)
    assert {p.number for p in doc.pages} == expected
    assert all(p.lines for p in doc.pages)


def test_fs_producer_missing_pdf_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        make_fs_fixture.produce(
            pdf_path=tmp_path / "nope.pdf", out_path=tmp_path / "out.json"
        )
    assert not (tmp_path / "out.json").exists()


# ── 2024 年報 fixture（1B-2 item 1.4）──────────────────────────────────────

_AR2024_PAGES = {3, 4, 5, 50, 51, 57, 68, 72, 73, 79, 80}


def test_ar2024_fixture_pages_and_raw_garbled() -> None:
    doc = _load("ar2024_3653_pages.json")
    assert {p.number for p in doc.pages} == _AR2024_PAGES
    assert doc.garbled_pages == [] and doc.ocr_pages == []
    by = {p.number: p for p in doc.pages}
    assert by[51].text.count("(cid:") >= 20
    assert by[79].text.count("(cid:") >= 20
    assert "(cid:" not in by[50].text


def test_ar2024_fixture_apply_ocr_policy_clears_garbled() -> None:
    out = _pdf_doc.apply_ocr_policy(_load("ar2024_3653_pages.json"), None)
    assert 51 in out.garbled_pages and 79 in out.garbled_pages
    assert 50 not in out.garbled_pages
    by = {p.number: p for p in out.pages}
    for n in (51, 79):
        assert (by[n].text, by[n].lines, by[n].tables) == ("", [], [])
    assert by[50].text != ""


def test_ar2024_fixture_version_matches_cache_version() -> None:
    data = json.loads((_FIX / "ar2024_3653_pages.json").read_text(encoding="utf-8"))
    assert data["version"] == _pdf_doc._CACHE_VERSION


def test_ar2024_producer_missing_pdf_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        make_ar2024_fixture.produce(
            pdf_path=tmp_path / "nope.pdf", out_path=tmp_path / "out.json"
        )
    assert not (tmp_path / "out.json").exists()


# ── 半年報 fixture（fs-generalize item 1.1）────────────────────────────────
# 契約 row：
#   H1: json 含 4 個 ticker；每個 ticker 至少 1 頁 BS、1 頁 IS、1 頁 CF
#   H2: 1303 BS 頁含 `2100` 開頭的右半科目文字
#   H3: [邊界] PDF 不存在 → producer 印錯誤並以非 0 結束，不寫半份 json

_H1_TICKERS = {"2059", "2308", "2303", "1303"}


def _h1() -> dict:
    return json.loads((_FIX / "fs_h1_pages.json").read_text(encoding="utf-8"))


def test_h1_fixture_has_four_tickers_each_with_three_statements() -> None:
    data = _h1()
    assert set(data) == _H1_TICKERS
    for ticker, entry in data.items():
        doc = _pdf_doc.from_json(entry["doc"])
        assert isinstance(doc, _pdf_doc.PdfDoc)
        anchors = {k: (PageRange(*r) if r else None) for k, r in entry["fs_anchors"].items()}
        for st in ("bs", "is", "cf"):
            pages = statement_pages(doc, anchors[_FS_ANCHOR_KEY[st]], _TITLE_KW[st])
            assert len(pages) >= 1, f"{ticker} {st}"


def test_h1_fixture_1303_bs_has_right_half_code_2100() -> None:
    entry = _h1()["1303"]
    doc = _pdf_doc.from_json(entry["doc"])
    anchors = {k: (PageRange(*r) if r else None) for k, r in entry["fs_anchors"].items()}
    bs_pages = set(statement_pages(doc, anchors["fs_bs"], _TITLE_KW["bs"]))
    lines = [ln for p in doc.pages if p.number in bs_pages for ln in p.lines]
    assert any(tok.startswith("2100") for ln in lines for tok in ln.split())


def test_h1_producer_missing_pdf_exits_nonzero_and_writes_nothing(tmp_path: Path, capsys) -> None:
    out = tmp_path / "out.json"
    rc = make_fs_h1_fixture.main(pdf_dir=tmp_path, out_path=out)
    assert rc != 0
    assert capsys.readouterr().err.strip() != ""
    assert not out.exists()
