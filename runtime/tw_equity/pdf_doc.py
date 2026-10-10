"""pdf_doc.py — pdfplumber／PyMuPDF 封裝層，含 sha256 快取。

提供 Page／PdfDoc dataclass 與 load_pdf 函式。
快取格式版本由 _CACHE_VERSION 控制；版本不符視同無快取。
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

_CACHE_VERSION = 5  # 4：橫向頁轉正後抽取；5：Page.image_cover／PdfDoc.image_pages
_DEFAULT_CACHE_DIR = Path("data/cache/tw_equity")


@dataclass
class Page:
    number: int                              # 1-indexed
    text: str                                # pdfplumber extract_text()，None → ""
    tables: list[list[list[str | None]]]     # pdfplumber extract_tables() 原樣
    lines: list[str] = field(default_factory=list)  # PyMuPDF words 重組的列文字
    image_cover: float = 0.0                 # 圖片矩形面積合計／頁面積（PyMuPDF；可 >1）


@dataclass
class PdfDoc:
    path: Path
    pages: list[Page]
    garbled_pages: list[int] = field(default_factory=list)  # 偵測到的亂碼頁
    ocr_pages: list[int] = field(default_factory=list)      # 已以 OCR 取代內容的頁
    image_pages: list[int] = field(default_factory=list)    # 偵測到的整頁圖片頁

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


_IMAGE_TEXT_MAX = 50     # 去空白後文字 <50 字
_IMAGE_COVER_MIN = 0.9   # 且圖片覆蓋頁面 ≥90%


def is_image_page(page: Page) -> bool:
    """整頁圖片（掃描／圖檔頁）：去空白文字 <50 字且圖片覆蓋率 ≥0.9；章節分隔頁、封面覆蓋率低不算。"""
    return len("".join(page.text.split())) < _IMAGE_TEXT_MAX and page.image_cover >= _IMAGE_COVER_MIN


def _is_scanned_page(page: Page) -> bool:
    """全頁掃描（image_cover ≥0.9），不論文字層字數（掃描頁常帶低品質垃圾文字層）。"""
    return page.image_cover >= _IMAGE_COVER_MIN


def apply_ocr_policy(doc: PdfDoc, ocr: OcrFn | None = None, *, ocr_scanned: bool = False) -> PdfDoc:
    """偵測亂碼頁與圖片頁；有 ocr 則對兩者聯集呼叫一次並取代。
    未取代的亂碼頁清空，未取代的圖片頁原樣保留。

    ocr_scanned=True：image_cover ≥0.9 的頁不管字數一律視為圖片頁（送 OCR）；預設 False 判定不變。

    ocr 例外不吞，原樣往上拋。回傳新 PdfDoc（不改傳入物件的頁）。
    """
    garbled = [p.number for p in doc.pages if is_garbled(p)]
    is_img = _is_scanned_page if ocr_scanned else is_image_page
    image = [p.number for p in doc.pages if is_img(p) and p.number not in garbled]
    targets = sorted(garbled + image)
    replaced: dict[int, Page] = {}
    if ocr is not None and targets:
        got = ocr(doc.path, list(targets))
        replaced = {n: got[n] for n in targets if n in got}
    pages: list[Page] = []
    for p in doc.pages:
        if p.number in replaced:
            r = replaced[p.number]
            pages.append(Page(number=p.number, text=r.text, tables=r.tables, lines=r.lines,
                              image_cover=p.image_cover))
        elif p.number in garbled:
            pages.append(Page(number=p.number, text="", tables=[], lines=[], image_cover=p.image_cover))
        else:
            pages.append(p)
    return PdfDoc(
        path=doc.path,
        pages=pages,
        garbled_pages=garbled,
        ocr_pages=sorted(replaced),
        image_pages=image,
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
                "image_cover": p.image_cover,
            }
            for p in doc.pages
        ],
        "garbled_pages": list(doc.garbled_pages),
        "ocr_pages": list(doc.ocr_pages),
        "image_pages": list(doc.image_pages),
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
            image_cover=pg.get("image_cover", 0.0),
        )
        for pg in data["pages"]
    ]
    return PdfDoc(
        path=Path(data["path"]),
        pages=pages,
        garbled_pages=list(data.get("garbled_pages", [])),
        ocr_pages=list(data.get("ocr_pages", [])),
        image_pages=list(data.get("image_pages", [])),
    )


# ── 快取工具 ─────────────────────────────────────────────────────────────────

def _sha256_prefix(path: Path) -> str:
    """回傳檔案 bytes 的 sha256 前 16 碼。"""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest[:16]


def _cache_path(pdf_path: Path, cache_dir: Path, *, with_ocr: bool = False, scanned: bool = False) -> Path:
    suffix = (".ocr-scan.json" if scanned else ".ocr.json") if with_ocr else ".json"
    return cache_dir / f"{_sha256_prefix(pdf_path)}{suffix}"


# ── 主入口 ───────────────────────────────────────────────────────────────────

def load_pdf(
    path: Path,
    *,
    cache_dir: Path | None = None,
    _opener: Any = None,
    _line_opener: Any = None,
    ocr: OcrFn | None = None,
    ocr_scanned: bool = False,
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
        ocr: 亂碼頁與圖片頁 OCR 備援；None 則亂碼頁清空、圖片頁原樣保留。
        ocr_scanned: True 時 image_cover ≥0.9 的頁不管字數都送 OCR（ocr 為 None 時無作用）；
                 快取檔名加 `.ocr-scan` 後綴避開舊快取。預設 False，判定與快取同修改前。

    Returns:
        PdfDoc 實例。
    """
    if cache_dir is None:
        cache_dir = _DEFAULT_CACHE_DIR
    scanned = ocr_scanned and ocr is not None

    # 有注入點時，跳過快取讀取（直接用注入資料），但仍寫快取
    if _opener is not None:
        doc = apply_ocr_policy(_build_from_opener(path, _opener, _line_opener), ocr, ocr_scanned=scanned)
        _write_cache(doc, path, cache_dir, with_ocr=ocr is not None, scanned=scanned)
        return doc

    # 嘗試讀快取
    cp = _cache_path(path, cache_dir, with_ocr=ocr is not None, scanned=scanned)
    if cp.exists():
        try:
            cached = from_json(json.loads(cp.read_text(encoding="utf-8")))
            if cached is not None:
                return cached
        except Exception:
            pass  # 快取損毀：重抽
    if scanned:  # 舊政策快取若無任何多出的掃描頁 → 判定相同、直接沿用（不重打 OCR）
        legacy = _cache_path(path, cache_dir, with_ocr=True)
        if legacy.exists():
            try:
                cached = from_json(json.loads(legacy.read_text(encoding="utf-8")))
                if cached is not None and not _extra_scanned_pages(cached):
                    return cached
            except Exception:
                pass

    # 從真實 PDF 抽取
    import pdfplumber  # 延遲 import

    doc = apply_ocr_policy(_build_from_pdfplumber(path, _line_opener), ocr, ocr_scanned=scanned)
    _write_cache(doc, path, cache_dir, with_ocr=ocr is not None, scanned=scanned)
    return doc


def _extra_scanned_pages(doc: PdfDoc) -> list[int]:
    """舊政策處理過的文件中，ocr_scanned 政策會多送 OCR 的頁（掃描頁、非亂碼、非舊政策圖片頁）。"""
    old = set(doc.garbled_pages) | set(doc.image_pages) | set(doc.ocr_pages)
    return [p.number for p in doc.pages if _is_scanned_page(p) and p.number not in old]


def _write_cache(
    doc: PdfDoc, pdf_path: Path, cache_dir: Path, *, with_ocr: bool = False, scanned: bool = False
) -> None:
    """寫快取；失敗靜默忽略。"""
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cp = _cache_path(pdf_path, cache_dir, with_ocr=with_ocr, scanned=scanned)
        cp.write_text(
            json.dumps(to_json(doc), ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


_Y_TOLERANCE = 3.0


def _page_rotation_fix(fitz_page: Any) -> int:
    """依頁內文字方向判斷需設定的 /Rotate：(0,-1) → 90、(0,1) → 270、其他 → 0。

    以 line 的字元數加權多數決；無文字回 0。
    """
    votes: dict[int, int] = {}
    for block in fitz_page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            dy = line.get("dir", (1.0, 0.0))[1]
            key = 90 if dy < -0.5 else 270 if dy > 0.5 else 0
            n = sum(len(sp.get("text", "")) for sp in line.get("spans", []))
            votes[key] = votes.get(key, 0) + n
    return max(votes, key=votes.get) if votes else 0


def _rotated_words(fitz_page: Any) -> list[Any]:
    """取 words；頁有 /Rotate 時把座標乘 rotation_matrix，使分群依視覺列。"""
    words = fitz_page.get_text("words")
    if not getattr(fitz_page, "rotation", 0):
        return words
    import fitz  # 延遲 import

    m = fitz_page.rotation_matrix
    out = []
    for w in words:
        r = fitz.Rect(w[:4]) * m
        out.append((r.x0, r.y0, r.x1, r.y1, *w[4:]))
    return out


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


def _image_cover(fitz_page: Any) -> float:
    """圖片矩形面積合計／頁面積；注入的假 opener 無 get_images 時回 0.0。"""
    if not hasattr(fitz_page, "get_images"):
        return 0.0
    area = fitz_page.rect.width * fitz_page.rect.height
    if not area:
        return 0.0
    total = sum(r.width * r.height for img in fitz_page.get_images() for r in fitz_page.get_image_rects(img[0]))
    return total / area


def _lines_from_opener(line_opener: Any, n_pages: int) -> list[list[str]]:
    if len(line_opener) != n_pages:
        raise ValueError(
            f"頁數不一致：_opener {n_pages} 頁、_line_opener {len(line_opener)} 頁"
        )
    return [_words_to_lines(_rotated_words(line_opener[i])) for i in range(n_pages)]


def _build_from_pdfplumber(path: Path, line_opener: Any = None) -> PdfDoc:
    import pdfplumber

    close_fitz = None
    source: Any = path
    if line_opener is None:
        import fitz  # 延遲 import

        line_opener = close_fitz = fitz.open(path)
        # 橫向排版頁（文字方向非水平）：pdfplumber 會反序、words 依 y 分群會把直欄當列。
        # 對這些頁設 /Rotate 轉正，兩個通道改讀轉正後的同一份 bytes。
        rotated = {i: _page_rotation_fix(line_opener[i]) for i in range(len(line_opener))}
        if any(rotated.values()):
            for i, rot in rotated.items():
                if rot:
                    line_opener[i].set_rotation(rot)
            buf = line_opener.tobytes()
            close_fitz.close()
            line_opener = close_fitz = fitz.open("pdf", buf)
            source = io.BytesIO(buf)
    try:
        with pdfplumber.open(source) as pdf:
            all_lines = _lines_from_opener(line_opener, len(pdf.pages))
            covers = [_image_cover(line_opener[i]) for i in range(len(pdf.pages))]
            pages = []
            for i, pg in enumerate(pdf.pages, start=1):
                text = pg.extract_text() or ""
                tables = pg.extract_tables() or []
                pages.append(
                    Page(number=i, text=text, tables=tables, lines=all_lines[i - 1],
                         image_cover=covers[i - 1])
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
