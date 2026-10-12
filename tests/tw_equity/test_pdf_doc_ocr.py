"""test_pdf_doc_ocr.py — 亂碼頁偵測與 OCR 政策（1B-2 §2.2）。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.tw_equity.ocr_adapters import AdapterError
from runtime.tw_equity.pdf_doc import Page, PdfDoc, apply_ocr_policy, is_garbled, load_pdf

GARBLED = "(cid:123)" * 20
GOOD = "正常內容"


def _doc() -> PdfDoc:
    return PdfDoc(path=Path("x.pdf"), pages=[
        Page(1, GOOD, [[["a"]]], ["正常列"]),
        Page(2, GARBLED, [[["b"]]], ["(cid:1)"]),
        Page(3, GARBLED, [[["c"]]], ["(cid:2)"]),
    ])


def test_is_garbled_threshold():
    assert is_garbled(Page(1, "(cid:1)" * 20, [])) is True
    assert is_garbled(Page(1, "(cid:1)" * 19, [])) is False


def test_no_ocr_clears_garbled_pages():
    out = apply_ocr_policy(_doc(), None)
    assert out.garbled_pages == [2, 3]
    assert out.ocr_pages == []
    for n in (2, 3):
        pg = out.pages[n - 1]
        assert (pg.text, pg.lines, pg.tables) == ("", [], [])
    assert out.pages[0].text == GOOD and out.pages[0].lines == ["正常列"]


def test_ocr_replaces_page_keeps_number():
    calls = []

    def ocr(path, pages):
        calls.append(list(pages))
        return {2: Page(99, "OCR文字", [[["x"]]], ["OCR列"]),
                3: Page(3, "OCR3", [], ["l3"])}

    out = apply_ocr_policy(_doc(), ocr)
    assert out.pages[1].number == 2
    assert out.pages[1].text == "OCR文字" and out.pages[1].lines == ["OCR列"]
    assert out.pages[1].tables == [[["x"]]]
    assert out.ocr_pages == [2, 3]
    assert calls == [[2, 3]]


def test_ocr_missing_page_is_cleared():
    out = apply_ocr_policy(_doc(), lambda p, pages: {2: Page(2, "OK", [], ["ok"])})
    assert out.ocr_pages == [2]
    assert out.garbled_pages == [2, 3]
    assert (out.pages[2].text, out.pages[2].lines, out.pages[2].tables) == ("", [], [])


def test_ocr_error_propagates():
    def ocr(path, pages):
        raise AdapterError("boom")

    with pytest.raises(AdapterError):
        apply_ocr_policy(_doc(), ocr)


def _opener(texts):
    return SimpleNamespace(pages=[
        SimpleNamespace(extract_text=(lambda t=t: t), extract_tables=lambda: [])
        for t in texts
    ])


def test_load_pdf_ocr_hook(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"x")
    doc = load_pdf(pdf, cache_dir=tmp_path / "c", _opener=_opener([GOOD, GARBLED]),
                   ocr=lambda p, pages: {2: Page(2, "OCR", [], ["OCR"])})
    assert doc.pages[0].text == GOOD
    assert doc.pages[1].text == "OCR"
    assert doc.garbled_pages == [2] and doc.ocr_pages == [2]


def test_load_pdf_without_ocr_keeps_clean_pages(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"x")
    doc = load_pdf(pdf, cache_dir=tmp_path / "c", _opener=_opener([GOOD, GARBLED]))
    assert doc.pages[0].text == GOOD
    assert doc.pages[1].text == ""
    assert doc.garbled_pages == [2] and doc.ocr_pages == []
