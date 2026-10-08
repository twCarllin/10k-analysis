"""test_pdf_doc_cache_ocr.py — garbled/ocr 欄位序列化與 .ocr.json 快取（1B-2 §2.2）。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from runtime.tw_equity.pdf_doc import (
    _CACHE_VERSION, Page, PdfDoc, from_json, load_pdf, to_json, _sha256_prefix,
)

GARBLED = "(cid:9)" * 20


def _opener():
    return SimpleNamespace(pages=[
        SimpleNamespace(extract_text=(lambda t=t: t), extract_tables=lambda: [])
        for t in ("正常", GARBLED)
    ])


def _pdf(tmp_path: Path) -> Path:
    p = tmp_path / "a.pdf"
    p.write_bytes(b"pdf-bytes")
    return p


def test_roundtrip_garbled_and_ocr_pages():
    doc = PdfDoc(Path("x.pdf"), [Page(1, "a", [])], garbled_pages=[2, 3], ocr_pages=[3])
    back = from_json(to_json(doc))
    assert back.garbled_pages == [2, 3] and back.ocr_pages == [3]


def test_missing_fields_default_empty():
    data = to_json(PdfDoc(Path("x.pdf"), [Page(1, "a", [])]))
    data.pop("garbled_pages")
    data.pop("ocr_pages")
    back = from_json(data)
    assert back.garbled_pages == [] and back.ocr_pages == []


def test_version_mismatch_returns_none():
    data = to_json(PdfDoc(Path("x.pdf"), [Page(1, "a", [])]))
    data["version"] = _CACHE_VERSION + 1
    assert from_json(data) is None


def test_cache_filenames_coexist(tmp_path):
    pdf = _pdf(tmp_path)
    cache = tmp_path / "c"
    plain = load_pdf(pdf, cache_dir=cache, _opener=_opener())
    withocr = load_pdf(pdf, cache_dir=cache, _opener=_opener(),
                       ocr=lambda p, pages: {2: Page(2, "OCR", [], ["OCR"])})
    sha = _sha256_prefix(pdf)
    assert sorted(f.name for f in cache.iterdir()) == [f"{sha}.json", f"{sha}.ocr.json"]
    assert plain.ocr_pages == [] and withocr.ocr_pages == [2]
    # 內容不互相覆蓋：無 ocr 快取仍為清空頁（不給 _opener，走快取讀取）
    again = load_pdf(pdf, cache_dir=cache)
    assert again.ocr_pages == [] and again.pages[1].text == ""
    # 有 ocr 快取命中：不再呼叫 ocr
    def boom(p, pages):
        raise AssertionError("ocr should not be called on cache hit")
    hit = load_pdf(pdf, cache_dir=cache, ocr=boom)
    assert hit.ocr_pages == [2] and hit.pages[1].text == "OCR"
