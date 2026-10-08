"""test_pdf_doc.py — PdfDoc、Page、load_pdf 單元測試。

_opener 注入點測試：用假物件替換 pdfplumber，驗證快取邏輯與資料結構。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import runtime.tw_equity.pdf_doc as pdf_doc_module
from runtime.tw_equity.pdf_doc import (
    Page,
    PdfDoc,
    _CACHE_VERSION,
    from_json,
    load_pdf,
    to_json,
)


# ── fake opener ───────────────────────────────────────────────────────────────

class _FakePdfPage:
    def __init__(self, text: str | None, tables: list) -> None:
        self._text = text
        self._tables = tables

    def extract_text(self) -> str | None:
        return self._text

    def extract_tables(self) -> list:
        return self._tables


class _FakeOpener:
    def __init__(self, pages: list[tuple[str | None, list]]) -> None:
        self.pages = [_FakePdfPage(t, tbl) for t, tbl in pages]


def _make_opener(
    *,
    texts: list[str | None] | None = None,
    tables: list[list] | None = None,
) -> _FakeOpener:
    n = len(texts) if texts is not None else (len(tables) if tables is not None else 3)
    _texts = texts if texts is not None else ["page text"] * n
    _tables = tables if tables is not None else [[]] * n
    return _FakeOpener(list(zip(_texts, _tables)))


# ── 假 PDF 路徑 ──────────────────────────────────────────────────────────────

def _dummy_pdf(tmp_path: Path) -> Path:
    p = tmp_path / "report.pdf"
    p.write_bytes(b"%PDF-1.4 fake")
    return p


# ── to_json / from_json ───────────────────────────────────────────────────────

class TestSerialisation:
    def test_round_trip(self, tmp_path):
        """to_json → from_json 資料等價。"""
        opener = _make_opener(texts=["p1 text", "p2 text"], tables=[[], []])
        doc = load_pdf(_dummy_pdf(tmp_path), _opener=opener, cache_dir=tmp_path / "cache")
        restored = from_json(to_json(doc))
        assert restored is not None
        assert len(restored.pages) == 2
        assert restored.pages[0].text == "p1 text"

    def test_from_json_wrong_version_returns_none(self, tmp_path):
        """版本不符 → from_json 回傳 None。"""
        opener = _make_opener(texts=["hello"])
        doc = load_pdf(_dummy_pdf(tmp_path), _opener=opener, cache_dir=tmp_path / "cache")
        data = to_json(doc)
        data["version"] = _CACHE_VERSION + 99
        assert from_json(data) is None


# ── load_pdf 基本行為 ─────────────────────────────────────────────────────────

class TestLoadPdf:
    def test_returns_pdf_doc(self, tmp_path):
        """load_pdf 回傳 PdfDoc 實例。"""
        opener = _make_opener(texts=["hello"])
        doc = load_pdf(_dummy_pdf(tmp_path), _opener=opener, cache_dir=tmp_path / "cache")
        assert isinstance(doc, PdfDoc)

    def test_pages_1indexed(self, tmp_path):
        """page.number 從 1 開始。"""
        opener = _make_opener(texts=["p1", "p2", "p3"])
        doc = load_pdf(_dummy_pdf(tmp_path), _opener=opener, cache_dir=tmp_path / "cache")
        assert [p.number for p in doc.pages] == [1, 2, 3]

    def test_none_text_becomes_empty_string(self, tmp_path):
        """pdfplumber extract_text() 回傳 None → page.text == ""。"""
        opener = _make_opener(texts=[None, "text"])
        doc = load_pdf(_dummy_pdf(tmp_path), _opener=opener, cache_dir=tmp_path / "cache")
        assert doc.pages[0].text == ""

    def test_tables_stored_as_is(self, tmp_path):
        """pdfplumber extract_tables() 原樣存入 page.tables。"""
        raw_tables = [[["A", "B"], ["1", "2"]]]
        opener = _make_opener(texts=["p1"], tables=[raw_tables])
        doc = load_pdf(_dummy_pdf(tmp_path), _opener=opener, cache_dir=tmp_path / "cache")
        assert doc.pages[0].tables == raw_tables


# ── 快取 ──────────────────────────────────────────────────────────────────────

class TestCache:
    def test_second_call_reads_cache(self, tmp_path):
        """load_pdf 二次呼叫同檔 → 第二次讀快取、內容等價。"""
        pdf_path = _dummy_pdf(tmp_path)
        cache_dir = tmp_path / "cache"

        opener1 = _make_opener(texts=["original text"])
        # 第一次呼叫：不用 _opener，走真實快取路徑
        # 但為了不依賴 pdfplumber，我們先用 _opener 建立快取
        doc1 = load_pdf(pdf_path, cache_dir=cache_dir, _opener=opener1)

        # 手動寫入快取（模擬第一次不用 _opener 的情況）
        from runtime.tw_equity.pdf_doc import _cache_path, to_json
        cp = _cache_path(pdf_path, cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(to_json(doc1), ensure_ascii=False), encoding="utf-8")

        # 第二次呼叫：不傳 _opener，應讀快取
        doc2 = load_pdf(pdf_path, cache_dir=cache_dir)
        assert doc2.pages[0].text == "original text"

    def test_cache_version_mismatch_ignores_cache(self, tmp_path, monkeypatch):
        """_CACHE_VERSION monkeypatch 改 → 視同無快取、重抽。"""
        pdf_path = _dummy_pdf(tmp_path)
        cache_dir = tmp_path / "cache"

        # 先用 v=1 建立快取
        opener1 = _make_opener(texts=["v1 content"])
        doc1 = load_pdf(pdf_path, cache_dir=cache_dir, _opener=opener1)
        from runtime.tw_equity.pdf_doc import _cache_path, to_json
        cp = _cache_path(pdf_path, cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(to_json(doc1), ensure_ascii=False), encoding="utf-8")

        # monkeypatch _CACHE_VERSION 讓版本不符
        monkeypatch.setattr(pdf_doc_module, "_CACHE_VERSION", _CACHE_VERSION + 1)

        # 第二次呼叫：快取版本不符，應跳過並用 _opener 重抽
        opener2 = _make_opener(texts=["v2 content"])
        doc2 = load_pdf(pdf_path, cache_dir=cache_dir, _opener=opener2)
        assert doc2.pages[0].text == "v2 content"

    def test_stale_cache_overwritten_with_new_version(self, tmp_path, monkeypatch):
        """版本不符 → 忽略快取並重寫新版本。"""
        pdf_path = _dummy_pdf(tmp_path)
        cache_dir = tmp_path / "cache"

        # 舊版快取
        opener1 = _make_opener(texts=["old"])
        doc1 = load_pdf(pdf_path, cache_dir=cache_dir, _opener=opener1)
        from runtime.tw_equity.pdf_doc import _cache_path, to_json
        cp = _cache_path(pdf_path, cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        old_data = to_json(doc1)
        old_data["version"] = _CACHE_VERSION - 1  # 故意寫舊版
        cp.write_text(json.dumps(old_data, ensure_ascii=False), encoding="utf-8")

        # 新版本讀取 → 應重寫快取
        opener2 = _make_opener(texts=["new"])
        doc2 = load_pdf(pdf_path, cache_dir=cache_dir, _opener=opener2)
        assert doc2.pages[0].text == "new"

        # 快取檔案應已更新為新版本
        written = json.loads(cp.read_text(encoding="utf-8"))
        assert written["version"] == _CACHE_VERSION


# ── text_of ──────────────────────────────────────────────────────────────────

class TestTextOf:
    def test_single_page(self, tmp_path):
        """text_of(2, 2) → 第 2 頁文字。"""
        opener = _make_opener(texts=["p1", "p2", "p3"])
        doc = load_pdf(_dummy_pdf(tmp_path), _opener=opener, cache_dir=tmp_path / "cache")
        assert doc.text_of(2, 2) == "p2"

    def test_multi_page_joined_with_form_feed(self, tmp_path):
        """text_of(2, 4) → p2–p4 文字以 \\f 連。"""
        opener = _make_opener(texts=["p1", "p2", "p3", "p4", "p5"])
        doc = load_pdf(_dummy_pdf(tmp_path), _opener=opener, cache_dir=tmp_path / "cache")
        assert doc.text_of(2, 4) == "p2\fp3\fp4"

    def test_inclusive_both_ends(self, tmp_path):
        """start 與 end 兩端都包含在內。"""
        opener = _make_opener(texts=["first", "middle", "last"])
        doc = load_pdf(_dummy_pdf(tmp_path), _opener=opener, cache_dir=tmp_path / "cache")
        result = doc.text_of(1, 3)
        assert result.startswith("first")
        assert result.endswith("last")


# ── tables_of ────────────────────────────────────────────────────────────────

class TestTablesOf:
    def test_returns_tables_in_range(self, tmp_path):
        """tables_of → pdfplumber tables 原樣，含兩端，回傳 list[list[list[str|None]]]。"""
        t1 = [[["a", "b"]]]   # page1.tables = 1 table, 1 row
        t2 = [[["c", "d"]]]   # page2.tables = 1 table, 1 row
        t3 = [[["e", "f"]]]
        opener = _make_opener(texts=["p1", "p2", "p3"], tables=[t1, t2, t3])
        doc = load_pdf(_dummy_pdf(tmp_path), _opener=opener, cache_dir=tmp_path / "cache")
        result = doc.tables_of(1, 2)
        # t1 + t2 = [[["a","b"]], [["c","d"]]] — 兩頁 tables 串列
        assert result == t1 + t2

    def test_out_of_range_excluded(self, tmp_path):
        """範圍外的頁不包含。"""
        t1 = [[["a"]]]
        t2 = [[["b"]]]
        opener = _make_opener(texts=["p1", "p2"], tables=[t1, t2])
        doc = load_pdf(_dummy_pdf(tmp_path), _opener=opener, cache_dir=tmp_path / "cache")
        result = doc.tables_of(2, 2)
        assert result == t2


# ── lines 通道（PyMuPDF words）────────────────────────────────────────────────

class _FakeWordsPage:
    def __init__(self, words: list[tuple]) -> None:
        self._words = words

    def get_text(self, kind: str) -> list[tuple]:
        assert kind == "words"
        return self._words


class _FakeLineOpener:
    def __init__(self, pages: list[list[tuple]]) -> None:
        self._pages = [_FakeWordsPage(w) for w in pages]

    def __getitem__(self, i: int) -> _FakeWordsPage:
        return self._pages[i]

    def __len__(self) -> int:
        return len(self._pages)


def _w(x0: float, y1: float, word: str) -> tuple:
    return (x0, y1 - 10, x0 + 5, y1, word, 0, 0, 0)


def _load_lines(tmp_path: Path, word_pages: list[list[tuple]]) -> PdfDoc:
    opener = _make_opener(texts=["t"] * len(word_pages))
    return load_pdf(
        _dummy_pdf(tmp_path),
        _opener=opener,
        _line_opener=_FakeLineOpener(word_pages),
        cache_dir=tmp_path / "cache",
    )


class TestLines:
    def test_same_row_sorted_by_x0_single_space(self, tmp_path):
        """y1 差 ≤3、x 亂序 → 同一列、x0 升冪、單空白接合。"""
        words = [_w(50, 102.5, "C"), _w(10, 100, "A"), _w(30, 101, "B")]
        doc = _load_lines(tmp_path, [words])
        assert doc.pages[0].lines == ["A B C"]

    def test_y_gap_over_3_splits_rows_top_to_bottom(self, tmp_path):
        """y1 差 >3 → 分兩列、由上而下。"""
        words = [_w(10, 120, "lower"), _w(10, 100, "upper")]
        doc = _load_lines(tmp_path, [words])
        assert doc.pages[0].lines == ["upper", "lower"]

    def test_blank_word_row_dropped(self, tmp_path):
        """[邊界] 全空白 word 的列 → 丟棄。"""
        words = [_w(10, 100, "  "), _w(10, 120, "keep")]
        doc = _load_lines(tmp_path, [words])
        assert doc.pages[0].lines == ["keep"]

    def test_lines_of_concatenates_inclusive(self, tmp_path):
        """lines_of(2,3) → 兩頁 lines 依頁序串接、含兩端。"""
        pages = [[_w(10, 100, f"p{n}")] for n in (1, 2, 3, 4)]
        doc = _load_lines(tmp_path, pages)
        assert doc.lines_of(2, 3) == ["p2", "p3"]

    def test_json_round_trip_preserves_lines(self, tmp_path):
        """to_json → from_json → lines 等價。"""
        doc = _load_lines(tmp_path, [[_w(10, 100, "a"), _w(20, 100, "b")]])
        restored = from_json(to_json(doc))
        assert restored is not None
        assert restored.pages[0].lines == doc.pages[0].lines == ["a b"]

    def test_from_json_missing_lines_defaults_empty(self, tmp_path):
        """舊格式缺 lines 欄 → lines=[]。"""
        doc = _load_lines(tmp_path, [[_w(10, 100, "a")]])
        data = to_json(doc)
        for pg in data["pages"]:
            del pg["lines"]
        restored = from_json(data)
        assert restored is not None
        assert restored.pages[0].lines == []

    def test_page_count_mismatch_raises(self, tmp_path):
        """[邊界] 兩個 opener 頁數不同 → ValueError。"""
        opener = _make_opener(texts=["a", "b"])
        with pytest.raises(ValueError):
            load_pdf(
                _dummy_pdf(tmp_path),
                _opener=opener,
                _line_opener=_FakeLineOpener([[_w(10, 100, "a")]]),
                cache_dir=tmp_path / "cache",
            )

    def test_cache_version_is_2(self):
        """_CACHE_VERSION 比 1A 現值（1）大 1。"""
        assert _CACHE_VERSION == 2

    def test_requirements_has_pymupdf(self):
        """requirements.txt 含 PyMuPDF>=1.27。"""
        req = (Path(__file__).resolve().parents[2] / "requirements.txt").read_text()
        assert "PyMuPDF>=1.27" in req
