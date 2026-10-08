"""pdf_doc.py — pdfplumber 封裝層，含 sha256 快取。

提供 Page／PdfDoc dataclass 與 load_pdf 函式。
快取格式版本由 _CACHE_VERSION 控制；版本不符視同無快取。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_CACHE_VERSION = 1
_DEFAULT_CACHE_DIR = Path("data/cache/tw_equity")


@dataclass
class Page:
    number: int                              # 1-indexed
    text: str                                # pdfplumber extract_text()，None → ""
    tables: list[list[list[str | None]]]     # pdfplumber extract_tables() 原樣


@dataclass
class PdfDoc:
    path: Path
    pages: list[Page]

    def text_of(self, start: int, end: int) -> str:
        """回傳頁碼 start..end（含兩端）的文字，頁間以 '\\f' 接。"""
        parts = [p.text for p in self.pages if start <= p.number <= end]
        return "\f".join(parts)

    def tables_of(self, start: int, end: int) -> list[list[list[str | None]]]:
        """回傳頁碼 start..end（含兩端）所有 pdfplumber tables 的合併串列。"""
        result: list[list[list[str | None]]] = []
        for p in self.pages:
            if start <= p.number <= end:
                result.extend(p.tables)
        return result


# ── 序列化 ──────────────────────────────────────────────────────────────────

def to_json(doc: PdfDoc) -> dict[str, Any]:
    """將 PdfDoc 序列化為可 JSON 儲存的 dict（含版本）。"""
    return {
        "version": _CACHE_VERSION,
        "path": str(doc.path),
        "pages": [
            {
                "number": p.number,
                "text": p.text,
                "tables": p.tables,
            }
            for p in doc.pages
        ],
    }


def from_json(data: dict[str, Any]) -> PdfDoc | None:
    """從 dict 還原 PdfDoc；版本不符回傳 None（視同無快取）。"""
    if data.get("version") != _CACHE_VERSION:
        return None
    pages = [
        Page(
            number=pg["number"],
            text=pg["text"],
            tables=pg["tables"],
        )
        for pg in data["pages"]
    ]
    return PdfDoc(path=Path(data["path"]), pages=pages)


# ── 快取工具 ─────────────────────────────────────────────────────────────────

def _sha256_prefix(path: Path) -> str:
    """回傳檔案 bytes 的 sha256 前 16 碼。"""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest[:16]


def _cache_path(pdf_path: Path, cache_dir: Path) -> Path:
    return cache_dir / f"{_sha256_prefix(pdf_path)}.json"


# ── 主入口 ───────────────────────────────────────────────────────────────────

def load_pdf(
    path: Path,
    *,
    cache_dir: Path | None = None,
    _opener: Any = None,
) -> PdfDoc:
    """載入 PDF 並回傳 PdfDoc，第二次呼叫讀快取。

    Args:
        path: PDF 檔案路徑。
        cache_dir: 快取目錄；預設 data/cache/tw_equity/。
        _opener: 測試注入點——回傳有 .pages 屬性的物件，
                 每頁有 extract_text() 與 extract_tables()。
                 提供時跳過快取讀取（直接用注入資料）。

    Returns:
        PdfDoc 實例。
    """
    if cache_dir is None:
        cache_dir = _DEFAULT_CACHE_DIR

    # 有注入點時，跳過快取讀取（直接用注入資料），但仍寫快取
    if _opener is not None:
        doc = _build_from_opener(path, _opener)
        _write_cache(doc, path, cache_dir)
        return doc

    # 嘗試讀快取
    cp = _cache_path(path, cache_dir)
    if cp.exists():
        try:
            cached = from_json(json.loads(cp.read_text(encoding="utf-8")))
            if cached is not None:
                return cached
        except Exception:
            pass  # 快取損毀：重抽

    # 從真實 PDF 抽取
    import pdfplumber  # 延遲 import

    doc = _build_from_pdfplumber(path)
    _write_cache(doc, path, cache_dir)
    return doc


def _write_cache(doc: PdfDoc, pdf_path: Path, cache_dir: Path) -> None:
    """寫快取；失敗靜默忽略。"""
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cp = _cache_path(pdf_path, cache_dir)
        cp.write_text(
            json.dumps(to_json(doc), ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _build_from_pdfplumber(path: Path) -> PdfDoc:
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        pages = []
        for i, pg in enumerate(pdf.pages, start=1):
            text = pg.extract_text() or ""
            tables = pg.extract_tables() or []
            pages.append(Page(number=i, text=text, tables=tables))
    return PdfDoc(path=path, pages=pages)


def _build_from_opener(path: Path, opener: Any) -> PdfDoc:
    """從 _opener 注入物件建立 PdfDoc。"""
    pages = []
    for i, pg in enumerate(opener.pages, start=1):
        text = pg.extract_text() or ""
        tables = pg.extract_tables() or []
        pages.append(Page(number=i, text=text, tables=tables))
    return PdfDoc(path=path, pages=pages)
