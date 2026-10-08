"""pdf_doc.py — pdfplumber／PyMuPDF 封裝層，含 sha256 快取。

提供 Page／PdfDoc dataclass 與 load_pdf 函式。
快取格式版本由 _CACHE_VERSION 控制；版本不符視同無快取。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

_CACHE_VERSION = 3
_DEFAULT_CACHE_DIR = Path("data/cache/tw_equity")


@dataclass
class Page:
    number: int                              # 1-indexed
    text: str                                # pdfplumber extract_text()，None → ""
    tables: list[list[list[str | None]]]     # pdfplumber extract_tables() 原樣
    lines: list[str] = field(default_factory=list)  # PyMuPDF words 重組的列文字


@dataclass
class PdfDoc:
    path: Path
    pages: list[Page]
    garbled_pages: list[int] = field(default_factory=list)  # 偵測到的亂碼頁
    ocr_pages: list[int] = field(default_factory=list)      # 已以 OCR 取代內容的頁

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

    def lines_of(self, start: int, end: int) -> list[str]:
        """回傳頁碼 start..end（含兩端）的列文字，依頁序串接。"""
        result: list[str] = []
        for p in self.pages:
            if start <= p.number <= end:
                result.extend(p.lines)
        return result


# ── 亂碼偵測與 OCR 政策 ─────────────────────────────────────────────────────

_CID_RE = re.compile(r"\(cid:\d+\)")
_GARBLED_THRESHOLD = 20

OcrFn = Callable[[Path, "list[int]"], "dict[int, Page]"]  # 頁碼 → 取代用 Page


def is_garbled(page: Page) -> bool:
    """page.text 中 `(cid:\d+)` 出現 ≥20 次視為亂碼頁。"""
    return len(_CID_RE.findall(page.text)) >= _GARBLED_THRESHOLD


def apply_ocr_policy(doc: PdfDoc, ocr: OcrFn | None = None) -> PdfDoc:
    """偵測亂碼頁；有 ocr 則呼叫一次並取代，未取代的亂碼頁清空。

    ocr 例外不吞，原樣往上拋。回傳新 PdfDoc（不改傳入物件的頁）。
    """
    garbled = [p.number for p in doc.pages if is_garbled(p)]
    replaced: dict[int, Page] = {}
    if ocr is not None and garbled:
        got = ocr(doc.path, list(garbled))
        replaced = {n: got[n] for n in garbled if n in got}
    pages: list[Page] = []
    for p in doc.pages:
        if p.number in replaced:
            r = replaced[p.number]
            pages.append(Page(number=p.number, text=r.text, tables=r.tables, lines=r.lines))
        elif p.number in garbled:
            pages.append(Page(number=p.number, text="", tables=[], lines=[]))
        else:
            pages.append(p)
    return PdfDoc(
        path=doc.path,
        pages=pages,
        garbled_pages=garbled,
        ocr_pages=sorted(replaced),
    )


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
                "lines": p.lines,
            }
            for p in doc.pages
        ],
        "garbled_pages": list(doc.garbled_pages),
        "ocr_pages": list(doc.ocr_pages),
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
            lines=pg.get("lines", []),
        )
        for pg in data["pages"]
    ]
    return PdfDoc(
        path=Path(data["path"]),
        pages=pages,
        garbled_pages=list(data.get("garbled_pages", [])),
        ocr_pages=list(data.get("ocr_pages", [])),
    )


# ── 快取工具 ─────────────────────────────────────────────────────────────────

def _sha256_prefix(path: Path) -> str:
    """回傳檔案 bytes 的 sha256 前 16 碼。"""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest[:16]


def _cache_path(pdf_path: Path, cache_dir: Path, *, with_ocr: bool = False) -> Path:
    suffix = ".ocr.json" if with_ocr else ".json"
    return cache_dir / f"{_sha256_prefix(pdf_path)}{suffix}"


# ── 主入口 ───────────────────────────────────────────────────────────────────

def load_pdf(
    path: Path,
    *,
    cache_dir: Path | None = None,
    _opener: Any = None,
    _line_opener: Any = None,
    ocr: OcrFn | None = None,
) -> PdfDoc:
    """載入 PDF 並回傳 PdfDoc，第二次呼叫讀快取。

    Args:
        path: PDF 檔案路徑。
        cache_dir: 快取目錄；預設 data/cache/tw_equity/。
        _opener: 測試注入點——回傳有 .pages 屬性的物件，
                 每頁有 extract_text() 與 extract_tables()。
                 提供時跳過快取讀取（直接用注入資料）。
        _line_opener: 測試注入點——支援 __getitem__／__len__，每頁有
                 get_text("words")；預設 fitz.open。_opener 提供時若未提供
                 本參數，lines 為空（不開真實 PDF）。
        ocr: 亂碼頁 OCR 備援；None 則亂碼頁清空。

    Returns:
        PdfDoc 實例。
    """
    if cache_dir is None:
        cache_dir = _DEFAULT_CACHE_DIR

    # 有注入點時，跳過快取讀取（直接用注入資料），但仍寫快取
    if _opener is not None:
        doc = apply_ocr_policy(_build_from_opener(path, _opener, _line_opener), ocr)
        _write_cache(doc, path, cache_dir, with_ocr=ocr is not None)
        return doc

    # 嘗試讀快取
    cp = _cache_path(path, cache_dir, with_ocr=ocr is not None)
    if cp.exists():
        try:
            cached = from_json(json.loads(cp.read_text(encoding="utf-8")))
            if cached is not None:
                return cached
        except Exception:
            pass  # 快取損毀：重抽

    # 從真實 PDF 抽取
    import pdfplumber  # 延遲 import

    doc = apply_ocr_policy(_build_from_pdfplumber(path, _line_opener), ocr)
    _write_cache(doc, path, cache_dir, with_ocr=ocr is not None)
    return doc


def _write_cache(
    doc: PdfDoc, pdf_path: Path, cache_dir: Path, *, with_ocr: bool = False
) -> None:
    """寫快取；失敗靜默忽略。"""
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cp = _cache_path(pdf_path, cache_dir, with_ocr=with_ocr)
        cp.write_text(
            json.dumps(to_json(doc), ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


_Y_TOLERANCE = 3.0


def _words_to_lines(words: Any) -> list[str]:
    """words（(x0, y0, x1, y1, word, ...)）依 y1 分群成列文字，由上而下。"""
    ordered = sorted(words, key=lambda w: w[3])
    rows: list[list[Any]] = []
    for w in ordered:
        if rows and w[3] - rows[-1][0][3] <= _Y_TOLERANCE:
            rows[-1].append(w)
        else:
            rows.append([w])
    lines: list[str] = []
    for row in rows:
        row.sort(key=lambda w: w[0])
        line = " ".join(str(w[4]) for w in row).strip()
        if line:
            lines.append(line)
    return lines


def _lines_from_opener(line_opener: Any, n_pages: int) -> list[list[str]]:
    if len(line_opener) != n_pages:
        raise ValueError(
            f"頁數不一致：_opener {n_pages} 頁、_line_opener {len(line_opener)} 頁"
        )
    return [_words_to_lines(line_opener[i].get_text("words")) for i in range(n_pages)]


def _build_from_pdfplumber(path: Path, line_opener: Any = None) -> PdfDoc:
    import pdfplumber

    close_fitz = None
    if line_opener is None:
        import fitz  # 延遲 import

        line_opener = close_fitz = fitz.open(path)
    try:
        with pdfplumber.open(path) as pdf:
            all_lines = _lines_from_opener(line_opener, len(pdf.pages))
            pages = []
            for i, pg in enumerate(pdf.pages, start=1):
                text = pg.extract_text() or ""
                tables = pg.extract_tables() or []
                pages.append(
                    Page(number=i, text=text, tables=tables, lines=all_lines[i - 1])
                )
    finally:
        if close_fitz is not None:
            close_fitz.close()
    return PdfDoc(path=path, pages=pages)


def _build_from_opener(path: Path, opener: Any, line_opener: Any = None) -> PdfDoc:
    """從 _opener 注入物件建立 PdfDoc。"""
    n = len(opener.pages)
    all_lines = (
        _lines_from_opener(line_opener, n) if line_opener is not None else [[] for _ in range(n)]
    )
    pages = []
    for i, pg in enumerate(opener.pages, start=1):
        text = pg.extract_text() or ""
        tables = pg.extract_tables() or []
        pages.append(Page(number=i, text=text, tables=tables, lines=all_lines[i - 1]))
    return PdfDoc(path=path, pages=pages)
