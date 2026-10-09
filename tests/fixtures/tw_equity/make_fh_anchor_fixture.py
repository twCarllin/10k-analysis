"""make_fh_anchor_fixture.py — 從 6 家金控年報切章名頁，序列化為 fh_ar_headings.json（run 2026-10-09-tw-equity-fh-schema item 4.1）。

執行方式：
    ./.venv/bin/python tests/fixtures/tw_equity/make_fh_anchor_fixture.py

輸出：tests/fixtures/tw_equity/fh_ar_headings.json（進版控；測試只讀此檔，不讀 data/cache、不載入本產生器）
來源：tw_report/<ticker>_2025年報.pdf 經 `pdf_doc.load_pdf` 讀 data/cache/tw_equity 快取（不打外部 API）。
頁選擇（PDF 頁 `Page.number`；Spec fh-schema §0.4 F10 章名起始頁、F9 財務績效節頁）：
  目錄頁（錨點須避開）：2881 p3–6；2882 p4–5；2885 p3–4；2886 p3；2887 p3–4；2891 p3。
  金控判定頁（提及「金融控股公司」，供 doc_anchor 金控門檻）：各家前 5 頁左右。
  章名頁：2881 4.1 營運概況 157、4.2 子公司營運概況 161、5. 240、5.2 財務績效 243；
        2882 肆 159、伍 230、財務績效 231；2885 肆 168、伍 264、二、財務績效 266；
        2886 營運概況 62、伍 118、一、財務狀況 119、二、財務績效 120；
        2887 肆 132（章分隔頁）、伍 240、一、個體財務狀況 241、二、個體財務績效 242；
        2891 肆 95、伍 160、一頁後 161。
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
_OUT_PATH = Path(__file__).resolve().parent / "fh_ar_headings.json"
_PAGES: dict[str, list[int]] = {
    "2881": [3, 4, 5, 6, 24, 25, 28, 35, 68, 157, 161, 240, 243],
    "2882": [4, 5, 16, 20, 21, 37, 46, 159, 230, 231],
    "2885": [3, 4, 18, 19, 20, 21, 22, 168, 264, 266],
    "2886": [3, 6, 14, 15, 18, 62, 118, 119, 120],
    "2887": [3, 4, 14, 16, 17, 18, 19, 132, 240, 241, 242],
    "2891": [3, 15, 16, 30, 32, 95, 160, 161],
}


def _pdf_path(pdf_dir: Path, ticker: str) -> Path:
    return pdf_dir / f"{ticker}_2025年報.pdf"


def _extract_one(pdf_path: Path, ticker: str) -> dict:
    doc = _pdf_doc.load_pdf(pdf_path)
    pages = [p for p in doc.pages if p.number in _PAGES[ticker]]
    sub = _pdf_doc.PdfDoc(path=Path(f"tw_report/{ticker}_2025年報.pdf"), pages=pages)
    return {
        "_source": f"依據 tw_report/{ticker}_2025年報.pdf p{','.join(str(n) for n in _PAGES[ticker])}"
        "（pdf_doc 頁文字輸出；Spec fh-schema §0.4 F9／F10）",
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
    produce()
