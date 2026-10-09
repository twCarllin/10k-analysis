"""make_fs_h1_fixture.py — 從半年報 PDF 抽三表頁，序列化為 fs_h1_pages.json（Spec 2026-10-09-tw-equity-fs-generalize §6）。

執行方式：
    ./.venv/bin/python tests/fixtures/tw_equity/make_fs_h1_fixture.py

輸出：tests/fixtures/tw_equity/fs_h1_pages.json（進版控，含 lines）
來源：tw_report/<ticker>_2026Q2財報.pdf（不進版控）；ticker ∈ 2059、2308、2303、1303

JSON 形狀：{ticker: {"fs_anchors": {key: [start, end] | null}, "doc": <pdf_doc.to_json 輸出>}}
  - fs_anchors：`find_heading_sections(doc, FS_HEADING_ANCHORS)` 的頁範圍（原 PDF 頁碼）
  - doc：只含 fs_bs／fs_is／fs_cf 範圍內、`statement_pages` 選出的頁（每表全部頁，含承前頁續頁）
SSOT 原則：JSON 形狀由 pdf_doc.to_json 決定；頁選擇邏輯重用 statements.statement_pages。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

from runtime.tw_equity import pdf_doc as _pdf_doc  # noqa: E402
from runtime.tw_equity.doc_anchor import FS_HEADING_ANCHORS, find_heading_sections  # noqa: E402
from runtime.tw_equity.statements import _FS_ANCHOR_KEY, _TITLE_KW, statement_pages  # noqa: E402

_PDF_DIR = _REPO_ROOT / "tw_report"
_OUT_PATH = Path(__file__).resolve().parent / "fs_h1_pages.json"
_TICKERS: list[str] = ["2059", "2308", "2303", "1303"]


def _pdf_path(pdf_dir: Path, ticker: str) -> Path:
    return pdf_dir / f"{ticker}_2026Q2財報.pdf"


def _extract_one(pdf_path: Path, ticker: str) -> dict:
    doc = _pdf_doc.load_pdf(pdf_path)
    anchors = find_heading_sections(doc, FS_HEADING_ANCHORS, required=set())
    selected: set[int] = set()
    for st in ("bs", "is", "cf"):
        selected.update(statement_pages(doc, anchors.get(_FS_ANCHOR_KEY[st]), _TITLE_KW[st]))
    pages = [p for p in doc.pages if p.number in selected]
    sub = _pdf_doc.PdfDoc(path=Path(f"tw_report/{ticker}_2026Q2財報.pdf"), pages=pages)
    return {
        "fs_anchors": {
            k: ([r.start, r.end] if r is not None else None) for k, r in anchors.items()
        },
        "doc": _pdf_doc.to_json(sub),
    }


def produce(
    pdf_dir: Path = _PDF_DIR,
    out_path: Path = _OUT_PATH,
    tickers: list[str] | None = None,
) -> None:
    """產生 fixture JSON。任一來源 PDF 不存在 → FileNotFoundError，且不寫出任何檔。"""
    tickers = list(tickers) if tickers is not None else list(_TICKERS)
    missing = [str(_pdf_path(pdf_dir, t)) for t in tickers if not _pdf_path(pdf_dir, t).exists()]
    if missing:
        raise FileNotFoundError("來源 PDF 不存在：" + "、".join(missing))

    data = {t: _extract_one(_pdf_path(pdf_dir, t), t) for t in tickers}  # 全部成功才寫檔
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"寫出 {out_path}（{len(data)} 檔）")


def main(pdf_dir: Path = _PDF_DIR, out_path: Path = _OUT_PATH) -> int:
    try:
        produce(pdf_dir=pdf_dir, out_path=out_path)
    except FileNotFoundError as e:
        print(f"錯誤：{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
