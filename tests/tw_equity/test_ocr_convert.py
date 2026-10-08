"""analyzeResult → dict[int, Page] 轉換（內嵌小型 analyzeResult，假 HTTP）。"""
import pytest

from runtime.tw_equity import ocr as ocr_mod
from runtime.tw_equity.ocr import DiPageOcr
from runtime.tw_equity.pdf_doc import Page


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    monkeypatch.setattr(ocr_mod, "_load_azure_config",
                        lambda: {"di_endpoint": "https://fake.example.test", "di_key": "K"})


class Resp:
    status_code = 200
    headers = {}

    def __init__(self, body):
        self._b = body

    def json(self):
        return self._b


def run(tmp_path, result, pages):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    d = DiPageOcr(_http_post=lambda url, **kw: Resp({"status": "succeeded", "analyzeResult": result}),
                  _sleep=lambda s: None)
    return d(pdf, pages)


def cell(r, c, text, **kw):
    return {"rowIndex": r, "columnIndex": c, "content": text, **kw}


def table(page, rows, cols, cells):
    return {"rowCount": rows, "columnCount": cols, "cells": cells,
            "boundingRegions": [{"pageNumber": page}]}


def test_lines_and_text(tmp_path):
    res = {"pages": [{"pageNumber": 51, "lines": [
        {"content": "  甲  "}, {"content": "   "}, {"content": ""}, {"content": "乙\t"}]}]}
    out = run(tmp_path, res, [51])
    p = out[51]
    assert isinstance(p, Page) and p.number == 51
    assert p.lines == ["甲", "乙"]
    assert p.text == "甲\n乙"


def test_table_cells_placed_and_assigned_to_pages(tmp_path):
    res = {
        "pages": [{"pageNumber": 51, "lines": []}, {"pageNumber": 79, "lines": []}],
        "tables": [
            table(51, 2, 2, [cell(0, 0, "a"), cell(0, 1, "b"), cell(1, 0, "c"), cell(1, 1, "d")]),
            table(79, 1, 1, [cell(0, 0, "z")]),
        ],
    }
    out = run(tmp_path, res, [51, 79])
    assert out[51].tables == [[["a", "b"], ["c", "d"]]]
    assert out[79].tables == [[["z"]]]


def test_unfilled_cell_is_none(tmp_path):
    res = {"pages": [{"pageNumber": 1, "lines": []}],
           "tables": [table(1, 2, 2, [cell(0, 0, "a"), cell(1, 1, "d")])]}
    assert run(tmp_path, res, [1])[1].tables == [[["a", None], [None, "d"]]]


def test_rowspan_fills_top_left_only(tmp_path):
    res = {"pages": [{"pageNumber": 1, "lines": []}],
           "tables": [table(1, 2, 2, [cell(0, 0, "a", rowSpan=2), cell(0, 1, "b"), cell(1, 1, "d")])]}
    assert run(tmp_path, res, [1])[1].tables == [[["a", "b"], [None, "d"]]]
