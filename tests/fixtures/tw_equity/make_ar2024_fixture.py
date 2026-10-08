"""make_ar2024_fixture.py — 從健策 2024 年報 PDF 抽指定頁，序列化為 ar2024_3653_pages.json。

執行方式：
    ./.venv/bin/python tests/fixtures/tw_equity/make_ar2024_fixture.py

輸出：tests/fixtures/tw_equity/ar2024_3653_pages.json（進版控；測試實際載入的 single source）
來源：tw_report/3653_2024年報.pdf（不進版控）

fixture 只存「原始頁」：p51、p79 的字型亂碼（`(cid:NNNN)`）原樣保留，
`garbled_pages` 為 []，本腳本不呼叫 apply_ocr_policy；測試以 fixture＋apply_ocr_policy 載入。
SSOT 原則：JSON 形狀由 pdf_doc.to_json 決定；`_blocks` 為說明用額外鍵（from_json 忽略）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

from runtime.tw_equity import pdf_doc as _pdf_doc  # noqa: E402
from tests.fixtures.tw_equity.make_ar_fixture import extract_pages  # noqa: E402

_PDF_PATH = _REPO_ROOT / "tw_report" / "3653_2024年報.pdf"
_OUT_PATH = Path(__file__).resolve().parent / "ar2024_3653_pages.json"

# 區塊：(頁碼, 依據)。依據字串在本檔的行號會寫進 JSON `_blocks`。
_BLOCKS: list[tuple[list[int], str]] = [
    ([3, 4], "BLOCK:目錄頁"),
    ([5], "BLOCK:致股東報告書"),
    ([50], "BLOCK:股權質押資訊（可讀頁，非亂碼對照）"),
    ([51], "BLOCK:前十大股東 T10（字型亂碼，原樣保留）"),
    ([57], "BLOCK:業務內容起頁"),
    ([68], "BLOCK:二、市場及產銷概況（標題在第 348 字，需標題行備援）"),
    ([72, 73], "BLOCK:T8 進貨／銷貨表"),
    ([79], "BLOCK:伍章財務狀況首頁（字型亂碼，原樣保留）"),
    ([80], "BLOCK:T7b 財務績效表"),
]
_SELECTED_PAGES: list[int] = [n for pages, _ in _BLOCKS for n in pages]


def _block_lines() -> list[dict]:
    src = Path(__file__).read_text(encoding="utf-8").splitlines()
    out = []
    for pages, reason in _BLOCKS:
        marker = f'"{reason}"'
        line_no = next(i for i, ln in enumerate(src, 1) if marker in ln and "_BLOCKS" not in ln)
        out.append({"pages": pages, "reason": reason, "producer_line": line_no})
    return out


def produce(
    pdf_path: Path = _PDF_PATH,
    out_path: Path = _OUT_PATH,
    page_numbers: list[int] | None = None,
) -> None:
    """產生 fixture JSON。

    Raises:
        FileNotFoundError: 來源 PDF 不存在。
    """
    if page_numbers is None:
        page_numbers = _SELECTED_PAGES

    doc = extract_pages(pdf_path, page_numbers)
    data = _pdf_doc.to_json(doc)
    data["_blocks"] = _block_lines()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"寫出 {out_path}（{len(doc.pages)} 頁）")


if __name__ == "__main__":
    produce()
