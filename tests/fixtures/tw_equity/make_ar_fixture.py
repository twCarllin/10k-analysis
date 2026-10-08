"""make_ar_fixture.py — 從健策年報 PDF 抽指定頁，序列化為 ar_3653_pages.json。

執行方式：
    ./.venv/bin/python tests/fixtures/tw_equity/make_ar_fixture.py

輸出：tests/fixtures/tw_equity/ar_3653_pages.json（進版控）
來源：tw_report/2025_3653_健策年報.pdf（不進版控）

SSOT 原則：fixture 格式由 pdf_doc.to_json 決定，本腳本不自寫 JSON 形狀。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 讓 repo root 進 sys.path，使 import runtime.tw_equity.pdf_doc 可用
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

from runtime.tw_equity import pdf_doc as _pdf_doc  # noqa: E402

# ── 常數 ─────────────────────────────────────────────────────────────────────

_PDF_PATH = _REPO_ROOT / "tw_report" / "2025_3653_健策年報.pdf"
_OUT_PATH = Path(__file__).resolve().parent / "ar_3653_pages.json"

# 抽取的頁碼（1-indexed，對應原 PDF 頁碼）
_SELECTED_PAGES: list[int] = [
    3, 4, 5, 6,          # 目錄頁（含 p3/p4）
    65, 66, 67,          # T7a 前置段
    76,                  # T8 前置頁
    81, 82,              # T8 主體
    92, 93, 94, 95, 96, 97, 98, 99,  # ar_mdna(92)、ar_special(99)
]


# ── 核心函式（可被測試直接呼叫）────────────────────────────────────────────────

def extract_pages(pdf_path: Path, page_numbers: list[int]) -> _pdf_doc.PdfDoc:
    """從 pdf_path 抽指定頁碼，回傳只含這些頁的 PdfDoc。

    Args:
        pdf_path: 來源 PDF 路徑。
        page_numbers: 要抽取的頁碼（1-indexed），必須對應原 PDF 頁碼。

    Raises:
        FileNotFoundError: 來源 PDF 不存在。
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"來源 PDF 不存在：{pdf_path}")

    import pdfplumber

    page_set = set(page_numbers)
    pages: list[_pdf_doc.Page] = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, pg in enumerate(pdf.pages, start=1):
            if i in page_set:
                text = pg.extract_text() or ""
                tables = pg.extract_tables() or []
                pages.append(_pdf_doc.Page(number=i, text=text, tables=tables))

    return _pdf_doc.PdfDoc(path=pdf_path, pages=pages)


def produce(
    pdf_path: Path = _PDF_PATH,
    out_path: Path = _OUT_PATH,
    page_numbers: list[int] | None = None,
) -> None:
    """執行產生 fixture JSON 的主流程。

    Args:
        pdf_path: 來源 PDF（預設 _PDF_PATH）。
        out_path: 輸出 JSON 路徑（預設 _OUT_PATH）。
        page_numbers: 要抽取的頁碼（預設 _SELECTED_PAGES）。

    Raises:
        FileNotFoundError: 來源 PDF 不存在。
    """
    if page_numbers is None:
        page_numbers = _SELECTED_PAGES

    doc = extract_pages(pdf_path, page_numbers)
    data = _pdf_doc.to_json(doc)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"寫出 {out_path}（{len(doc.pages)} 頁）")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    produce()
