"""make_fh_fy_fixture.py — 從 6 家金控年報切財務績效頁，序列化為 fh_fy_income_pages.json（run 2026-10-09-tw-equity-fh-schema item 4.2）。

執行方式：
    ./.venv/bin/python tests/fixtures/tw_equity/make_fh_fy_fixture.py

輸出：tests/fixtures/tw_equity/fh_fy_income_pages.json（進版控；測試只讀此檔，不讀 data/cache、不載入本產生器）
來源：tw_report/<ticker>_2025年報.pdf 經 `pdf_doc.load_pdf` 讀 data/cache/tw_equity 快取（不打外部 API）。
頁（PDF 頁 `Page.number`；Spec fh-schema §0.4 F9）：2881 p243、2885 p266、2886 p120、2882 p231、2887 p242、2891 p160。
錨點：ar_fin_performance／ar_mdna 起頁為 item 4.1 實測值（2881 243／240、2882 231／230、2885 266／264、
  2886 120／118、2887 242／240、2891 160／160）；迄頁在 fixture 內取為財務績效頁（fixture 只含該頁，僅作範圍判定用）。
JSON 形狀：{ticker: {"_source", "anchors": {key: [start, end]}, "doc": <pdf_doc.to_json 輸出>}}；
  另有 "industrial_fy_3653"（本 item 前 HEAD 對 ar_3653_pages.json 的 extract_fy_income(...).to_dict() 快照，
  由工業路徑回歸測試鎖定；本產生器重跑時原樣保留，不重算）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

from runtime.tw_equity import pdf_doc as _pdf_doc  # noqa: E402

_PDF_DIR = _REPO_ROOT / "tw_report"
_OUT_PATH = Path(__file__).resolve().parent / "fh_fy_income_pages.json"
_PAGE = {"2881": 243, "2882": 231, "2885": 266, "2886": 120, "2887": 242, "2891": 160}
_MDNA_START = {"2881": 240, "2882": 230, "2885": 264, "2886": 118, "2887": 240, "2891": 160}
_KEEP_KEY = "industrial_fy_3653"


def _pdf_path(pdf_dir: Path, ticker: str) -> Path:
    return pdf_dir / f"{ticker}_2025年報.pdf"


def _extract_one(pdf_path: Path, ticker: str) -> dict:
    doc = _pdf_doc.load_pdf(pdf_path)
    pages = [p for p in doc.pages if p.number == _PAGE[ticker]]
    sub = _pdf_doc.PdfDoc(path=Path(f"tw_report/{ticker}_2025年報.pdf"), pages=pages)
    return {
        "_source": f"依據 tw_report/{ticker}_2025年報.pdf p{_PAGE[ticker]}（pdf_doc 頁文字輸出；Spec fh-schema §0.4 F9）；"
        "anchors 起頁依據 item 4.1 實測、迄頁為 fixture 取值",
        "anchors": {
            "ar_fin_performance": [_PAGE[ticker], _PAGE[ticker]],
            "ar_mdna": [_MDNA_START[ticker], _PAGE[ticker]],
        },
        "doc": _pdf_doc.to_json(sub),
    }


def produce(pdf_dir: Path = _PDF_DIR, out_path: Path = _OUT_PATH) -> None:
    missing = [str(_pdf_path(pdf_dir, t)) for t in _PAGE if not _pdf_path(pdf_dir, t).exists()]
    if missing:
        raise FileNotFoundError("來源 PDF 不存在：" + "、".join(missing))
    data = {t: _extract_one(_pdf_path(pdf_dir, t), t) for t in _PAGE}
    if out_path.exists():
        old = json.loads(out_path.read_text(encoding="utf-8"))
        if _KEEP_KEY in old:
            data[_KEEP_KEY] = old[_KEEP_KEY]
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"寫出 {out_path}（{len(data)} 檔）")


if __name__ == "__main__":
    produce()
