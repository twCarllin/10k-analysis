"""make_fy_income_fixture.py — 從年報 PDF 抽 FY 損益比較頁文字列，序列化為 fy_income_lines.json。

執行方式：
    ./.venv/bin/python tests/fixtures/tw_equity/make_fy_income_fixture.py

輸出：tests/fixtures/tw_equity/fy_income_lines.json（進版控）
JSON 形狀：{ticker: {"source": 說明, "pdf": 檔名, "page": 原 PDF 頁碼(1-indexed), "lines": [...]}}
  - lines 依據 pdf_doc.py:26 `Page.lines`（PyMuPDF words 重組的列文字），取頁首 _N_LINES 列（涵蓋損益比較表）
  - 來源 PDF：tw_report/（不進版控）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

from runtime.tw_equity import pdf_doc as _pdf_doc  # noqa: E402

_OUT_PATH = Path(__file__).resolve().parent / "fy_income_lines.json"
_N_LINES = 22
# ticker → (PDF 檔名, 頁碼)
_SOURCES: dict[str, tuple[str, int]] = {
    "3653": ("2025_3653_健策年報.pdf", 93),
    "2301": ("2301_2025年報.pdf", 135),
    "2308": ("2308_2025年報.pdf", 113),
    "4958": ("4958_2025年報.pdf", 69),
}


def produce(pdf_dir: Path = _REPO_ROOT / "tw_report", out_path: Path = _OUT_PATH) -> None:
    missing = [str(pdf_dir / f) for f, _ in _SOURCES.values() if not (pdf_dir / f).exists()]
    if missing:
        raise FileNotFoundError("來源 PDF 不存在：" + "、".join(missing))
    data = {}
    for ticker, (fname, page) in _SOURCES.items():
        doc = _pdf_doc.load_pdf(pdf_dir / fname)
        data[ticker] = {
            "source": f"依據 pdf_doc.py:26 Page.lines；tw_report/{fname} 第 {page} 頁",
            "pdf": fname,
            "page": page,
            "lines": doc.pages[page - 1].lines[:_N_LINES],
        }
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"寫出 {out_path}（{len(data)} 檔）")


if __name__ == "__main__":
    try:
        produce()
    except FileNotFoundError as e:
        print(f"錯誤：{e}", file=sys.stderr)
        sys.exit(1)
