"""MistralPageOcr／markdown_to_page（假 adapter，不打真實 API）。"""
import os

import fitz
import pytest

from runtime.tw_equity.ocr_adapters import AdapterError
from runtime.tw_equity.ocr import MistralPageOcr, markdown_to_page


@pytest.fixture
def pdf(tmp_path):
    p = tmp_path / "src.pdf"
    d = fitz.open()
    for i in range(5):
        d.new_page().insert_text((72, 72), f"p{i + 1}")
    d.save(str(p))
    return p


class FakeAdapter:
    def __init__(self, mds=None, exc=None):
        self.mds, self.exc = mds, exc
        self.seen_pages = None
        self.seen_path = None

    def extract_pages(self, pdf_path):
        self.seen_path = pdf_path
        doc = fitz.open(pdf_path)
        self.seen_pages = len(doc)
        self.seen_texts = [pg.get_text().strip() for pg in doc]
        if self.exc:
            raise self.exc
        return self.mds


def test_fetch_maps_pages_and_sends_subpdf(pdf):
    a = FakeAdapter(["md1", "md2"])
    out = MistralPageOcr(_adapter=a).fetch(pdf, [4, 2])
    assert out == {4: "md1", 2: "md2"}
    assert a.seen_pages == 2
    assert a.seen_texts == ["p4", "p2"]
    assert not os.path.exists(a.seen_path)


def test_fetch_page_count_mismatch_raises(pdf):
    a = FakeAdapter(["only-one"])
    with pytest.raises(AdapterError):
        MistralPageOcr(_adapter=a).fetch(pdf, [1, 2])
    assert not os.path.exists(a.seen_path)


def test_fetch_adapter_error_propagates_and_tempfile_removed(pdf):
    a = FakeAdapter(exc=AdapterError("boom"))
    with pytest.raises(AdapterError, match="boom"):
        MistralPageOcr(_adapter=a).fetch(pdf, [1])
    assert not os.path.exists(a.seen_path)


def test_call_returns_pages(pdf):
    out = MistralPageOcr(_adapter=FakeAdapter(["# T\n| a | b |\n|---|---|\n| 1 | |"]))(pdf, [3])
    assert out[3].number == 3 and out[3].tables == [[["a", "b"], ["1", None]]]


def test_markdown_table_and_lines():
    p = markdown_to_page(7, "| a | b |\n|---|---|\n| 1 | |")
    assert p.number == 7
    assert p.tables == [[["a", "b"], ["1", None]]]
    assert "a b" in p.lines
    assert p.text == "\n".join(p.lines)


def test_markdown_marks_stripped_and_image_dropped():
    p = markdown_to_page(1, "## 標題\n**粗體**\n![img](x)\n\n文字")
    assert p.lines == ["標題", "粗體", "文字"]
    assert not any("img" in ln for ln in p.lines)


def test_markdown_negative_numbers_kept_and_markers_stripped():
    p = markdown_to_page(1, "-5.2%\n-1,234\n- 項目\n# 標題\n> 引言")
    assert p.lines == ["-5.2%", "-1,234", "項目", "標題", "引言"]
