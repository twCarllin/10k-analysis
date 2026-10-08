"""橫向排版頁轉正（run 2026-10-08-tw-equity-rotated-pages，item 1.1）。

不進二進位 fixture：以 fitz 在 tmp_path 合成「文字方向 (0,-1)」的頁，重現 pdfplumber 反序 bug。
"""
from pathlib import Path

import fitz
import pytest

from runtime.tw_equity import pdf_doc
from runtime.tw_equity.pdf_doc import _page_rotation_fix, _rotated_words, load_pdf

_TITLE = "貳、公司治理報告"
_REVERSED = _TITLE[::-1]


def _make_pdf(path: Path) -> None:
    """p1：橫向（文字 rotate=90）＋ 2×2 格線表；p2：正常橫書。"""
    doc = fitz.open()
    pg = doc.new_page(width=595, height=842)
    pg.insert_text((560, 800), _TITLE, fontname="china-t", fontsize=14, rotate=90)
    # 2×2 表格：格線 + 直書儲存格文字
    x0, y0, x1, y1 = 300, 300, 500, 700
    for x in (x0, 400, x1):
        pg.draw_line((x, y0), (x, y1))
    for y in (y0, 500, y1):
        pg.draw_line((x0, y), (x1, y))
    pg.insert_text((480, 680), "姓名", fontname="china-t", fontsize=12, rotate=90)
    pg.insert_text((480, 480), "職稱", fontname="china-t", fontsize=12, rotate=90)
    pg.insert_text((380, 680), "王小明", fontname="china-t", fontsize=12, rotate=90)
    pg.insert_text((380, 480), "董事長", fontname="china-t", fontsize=12, rotate=90)
    pg2 = doc.new_page(width=595, height=842)
    pg2.insert_text((72, 72), "一、業務內容", fontname="china-t", fontsize=14)
    doc.save(path)


@pytest.fixture
def rotated_pdf(tmp_path: Path) -> Path:
    p = tmp_path / "rot.pdf"
    _make_pdf(p)
    return p


def test_bug_reproduced_without_fix(rotated_pdf: Path) -> None:
    """前提確認：pdfplumber 直接抽 → 反序（修法的對照組）。"""
    import pdfplumber

    with pdfplumber.open(rotated_pdf) as pdf:
        assert _REVERSED in (pdf.pages[0].extract_text() or "")


def test_load_pdf_derotates_text_tables_lines(rotated_pdf: Path, tmp_path: Path) -> None:
    doc = load_pdf(rotated_pdf, cache_dir=tmp_path / "cache")
    p1, p2 = doc.pages
    assert _TITLE in p1.text and _REVERSED not in p1.text
    assert p1.tables, "轉正後應偵測到格線表"
    cells = {c for row in p1.tables[0] for c in row if c}
    assert "姓名" in cells
    assert any(_TITLE in line for line in p1.lines)
    assert "一、業務內容" in p2.text  # 未轉正頁不受影響


def test_cache_written_with_derotated_content(rotated_pdf: Path, tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    load_pdf(rotated_pdf, cache_dir=cache)
    doc2 = load_pdf(rotated_pdf, cache_dir=cache)  # 第二次讀快取
    assert _TITLE in doc2.pages[0].text


class _FakePage:
    def __init__(self, lines):
        self._lines = lines

    def get_text(self, kind):
        assert kind == "dict"
        return {"blocks": [{"lines": [
            {"dir": d, "spans": [{"text": t}]} for d, t in self._lines
        ]}]}


def test_page_rotation_fix_votes() -> None:
    assert _page_rotation_fix(_FakePage([((1.0, 0.0), "橫書")])) == 0
    assert _page_rotation_fix(_FakePage([((0.0, -1.0), "直直直"), ((1.0, 0.0), "頁")])) == 90
    assert _page_rotation_fix(_FakePage([((0.0, 1.0), "直直直"), ((1.0, 0.0), "頁")])) == 270
    assert _page_rotation_fix(_FakePage([])) == 0


def test_rotated_words_passthrough_without_rotation_attr() -> None:
    class _P:
        def get_text(self, kind):
            return [(0, 0, 10, 10, "w")]

    assert _rotated_words(_P()) == [(0, 0, 10, 10, "w")]
