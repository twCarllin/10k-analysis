"""make_fs_fixture.py — 從 3653 合併財報 PDF 抽指定頁，序列化為 fs_3653_pages.json。

執行方式：
    ./.venv/bin/python tests/fixtures/tw_equity/make_fs_fixture.py

輸出：tests/fixtures/tw_equity/fs_3653_pages.json（進版控，含 lines）
來源：tw_report/3653_2025Q4合併財報.pdf（不進版控）

SSOT 原則：JSON 形狀由 pdf_doc.to_json 決定；抽頁邏輯與 make_ar_fixture 共用。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

from runtime.tw_equity import pdf_doc as _pdf_doc  # noqa: E402
from tests.fixtures.tw_equity.make_ar_fixture import extract_pages  # noqa: E402

_PDF_PATH = _REPO_ROOT / "tw_report" / "3653_2025Q4合併財報.pdf"
_OUT_PATH = Path(__file__).resolve().parent / "fs_3653_pages.json"

_SELECTED_PAGES: list[int] = [
    2, 3, 5, 6, 10, 11, 12, 13, 14, 15, 22, 29, 31, 46, 47, 51, 55, 64, 67,
]


def produce(
    pdf_path: Path = _PDF_PATH,
    out_path: Path = _OUT_PATH,
    page_numbers: list[int] | None = None,
) -> None:
    """產生 fixture JSON。來源 PDF 不存在 → FileNotFoundError。"""
    if page_numbers is None:
        page_numbers = _SELECTED_PAGES

    doc = extract_pages(pdf_path, page_numbers)
    data = _pdf_doc.to_json(doc)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"寫出 {out_path}（{len(doc.pages)} 頁）")


if __name__ == "__main__":
    produce()
