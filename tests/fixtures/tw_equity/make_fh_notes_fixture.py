"""make_fh_notes_fixture.py — 從金控半年報 PDF 切附註頁，序列化為 fh_notes_pages.json（run 2026-10-09-tw-equity-fh-schema item 2.1；2.2／2.3 續擴）。

執行方式：
    ./.venv/bin/python tests/fixtures/tw_equity/make_fh_notes_fixture.py

輸出：tests/fixtures/tw_equity/fh_notes_pages.json（進版控；測試只讀此檔，不讀 data/cache、不載入本產生器）
來源：tw_report/<ticker>_2026Q2財報.pdf 經 `pdf_doc.load_pdf` 讀 data/cache/tw_equity 快取（不打外部 API）。
頁選擇（PDF 頁 `Page.number`，Spec fh-schema §0.4 F7）：
  CAR（F7）：2881 p354；2882 p280；2885 p212；2886 p159–160（p159 為 115.6.30 金額欄全「註」）；2887 p220；2891 p118。
  逾放比（F8，item 2.2）：2881 p290–291；2882 p285；2885 p247；2886 p114–115；2891 p95。
  多銀行（F8，item 2.3）：2887 p240（台新銀行小節標題）、p242（台新，兩期並排）、p257（臺灣新光商銀小節標題）、p259（新光，僅 115.6.30）。
JSON 形狀：{ticker: {"_source": 說明, "doc": <pdf_doc.to_json 輸出>}}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

from runtime.tw_equity import pdf_doc as _pdf_doc  # noqa: E402

_PDF_DIR = _REPO_ROOT / "tw_report"
_OUT_PATH = Path(__file__).resolve().parent / "fh_notes_pages.json"
_PAGES: dict[str, list[int]] = {
    "2881": [290, 291, 354],
    "2882": [280, 285],
    "2885": [212, 247],
    "2886": [114, 115, 159, 160],
    "2887": [220, 240, 242, 257, 259],
    "2891": [95, 118],
}


def _pdf_path(pdf_dir: Path, ticker: str) -> Path:
    return pdf_dir / f"{ticker}_2026Q2財報.pdf"


def _extract_one(pdf_path: Path, ticker: str) -> dict:
    doc = _pdf_doc.load_pdf(pdf_path)
    pages = [p for p in doc.pages if p.number in _PAGES[ticker]]
    sub = _pdf_doc.PdfDoc(path=Path(f"tw_report/{ticker}_2026Q2財報.pdf"), pages=pages)
    return {
        "_source": f"tw_report/{ticker}_2026Q2財報.pdf p{','.join(str(n) for n in _PAGES[ticker])}"
        "（pdf_doc 頁文字輸出；Spec fh-schema §0.4 F7／F8）",
        "doc": _pdf_doc.to_json(sub),
    }


def produce(pdf_dir: Path = _PDF_DIR, out_path: Path = _OUT_PATH) -> None:
    missing = [str(_pdf_path(pdf_dir, t)) for t in _PAGES if not _pdf_path(pdf_dir, t).exists()]
    if missing:
        raise FileNotFoundError("來源 PDF 不存在：" + "、".join(missing))
    data = {t: _extract_one(_pdf_path(pdf_dir, t), t) for t in _PAGES}
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"寫出 {out_path}（{len(data)} 檔）")


if __name__ == "__main__":
    try:
        produce()
    except FileNotFoundError as e:
        print(f"錯誤：{e}", file=sys.stderr)
        sys.exit(1)
