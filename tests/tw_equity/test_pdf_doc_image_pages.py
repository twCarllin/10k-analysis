"""test_pdf_doc_image_pages.py — 圖片頁偵測與 OCR 路由（run 2026-10-09-tw-equity-anchor-ocr，item 2.1）。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.tw_equity import pdf_doc
from runtime.tw_equity.pdf_doc import Page, PdfDoc, _image_cover, apply_ocr_policy, is_image_page

_ROOT = Path(__file__).resolve().parents[2]
_GARBLED = "(cid:1)" * 25


def _doc(*pages: Page) -> PdfDoc:
    return PdfDoc(path=Path("x.pdf"), pages=list(pages))


class _RecOcr:
    def __init__(self):
        self.calls: list[list[int]] = []

    def __call__(self, path, pages):
        self.calls.append(list(pages))
        return {n: Page(number=n, text=f"OCR{n}", tables=[], lines=[f"OCR{n}"]) for n in pages}


# ── is_image_page（契約表）──────────────────────────────────────────────────


def test_text_50_chars_or_more_is_not_image_page():
    assert not is_image_page(Page(1, "字" * 50, [], image_cover=1.0))


def test_low_text_low_cover_is_not_image_page():
    assert not is_image_page(Page(1, "第 貳 章", [], image_cover=0.43))


def test_low_text_high_cover_is_image_page():
    assert is_image_page(Page(1, " 頁 3 \n", [], image_cover=0.9))


# ── apply_ocr_policy ───────────────────────────────────────────────────────


def test_image_page_sent_to_ocr_and_replaced():
    ocr = _RecOcr()
    out = apply_ocr_policy(_doc(Page(1, "正文" * 30, []), Page(2, "", [], image_cover=1.0)), ocr)
    assert ocr.calls == [[2]]
    assert out.pages[1].text == "OCR2" and out.pages[1].lines == ["OCR2"]
    assert out.ocr_pages == [2] and out.image_pages == [2] and out.garbled_pages == []


def test_garbled_and_image_pages_one_ocr_call_union():
    ocr = _RecOcr()
    out = apply_ocr_policy(_doc(Page(1, "", [], image_cover=1.0), Page(2, "正文" * 30, []),
                                Page(3, _GARBLED, [])), ocr)
    assert ocr.calls == [[1, 3]]
    assert out.ocr_pages == [1, 3] and out.garbled_pages == [3] and out.image_pages == [1]


def test_no_ocr_image_page_kept_and_recorded():
    img = Page(2, "", [["a"]], lines=["x"], image_cover=1.0)
    out = apply_ocr_policy(_doc(Page(1, "正文" * 30, []), img))
    assert out.pages[1] == img
    assert out.image_pages == [2] and out.ocr_pages == []


def test_no_ocr_garbled_page_still_cleared():
    out = apply_ocr_policy(_doc(Page(1, _GARBLED, [["t"]], lines=["l"])))
    assert out.pages[0].text == "" and out.pages[0].tables == [] and out.garbled_pages == [1]


def test_no_targets_ocr_not_called():
    ocr = _RecOcr()
    apply_ocr_policy(_doc(Page(1, "第 貳 章", [], image_cover=0.1)), ocr)
    assert ocr.calls == []


# ── 序列化／快取版本 ─────────────────────────────────────────────────────────


def test_json_roundtrip_keeps_image_cover_and_pages():
    doc = apply_ocr_policy(_doc(Page(1, "", [], image_cover=1.0)))
    back = pdf_doc.from_json(pdf_doc.to_json(doc))
    assert back.pages[0].image_cover == 1.0 and back.image_pages == [1]


def test_v4_cache_treated_as_missing():
    data = pdf_doc.to_json(_doc(Page(1, "a", [])))
    data["version"] = 4
    assert pdf_doc.from_json(data) is None


# ── _image_cover ───────────────────────────────────────────────────────────


def test_image_cover_ratio_from_fitz_like_page():
    rect = SimpleNamespace(width=100.0, height=200.0)
    page = SimpleNamespace(rect=rect, get_images=lambda: [(7,)],
                           get_image_rects=lambda xref: [SimpleNamespace(width=100.0, height=180.0)])
    assert _image_cover(page) == pytest.approx(0.9)


def test_image_cover_fake_opener_without_images_is_zero():
    assert _image_cover(SimpleNamespace()) == 0.0


# ── 真實 PDF（不打 API）─────────────────────────────────────────────────────


@pytest.mark.parametrize("name,expected", [("2330_2026Q2財報.pdf", list(range(3, 11))),
                                           ("3711_2026Q2財報.pdf", list(range(4, 11)))])
def test_real_h1_statement_image_pages(name, expected):
    path = _ROOT / "tw_report" / name
    if not path.exists():
        pytest.skip(f"缺 {name}")
    assert pdf_doc.load_pdf(path).image_pages == expected
