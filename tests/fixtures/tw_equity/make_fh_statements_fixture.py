"""make_fh_statements_fixture.py — 從金控半年報 PDF 切三表頁，序列化為 fh_statements_pages.json（run 2026-10-09-tw-equity-fh-schema item 1.2）。

執行方式：
    ./.venv/bin/python tests/fixtures/tw_equity/make_fh_statements_fixture.py

輸出：tests/fixtures/tw_equity/fh_statements_pages.json（進版控；測試只讀此檔，不讀 data/cache、不載入本產生器）
來源：tw_report/<ticker>_2026Q2財報.pdf 經 `pdf_doc.load_pdf` 讀 data/cache/tw_equity 快取（不打外部 API）。
頁選擇（PDF 頁 `Page.number`，Spec fh-schema §0.4 F2）：
  2881 BS p8（左右並排）、IS p9–10、CF p11–12；2882 BS p9、IS p10、CF p12–13；
  2885 BS p12–13、IS p14–15、CF p17–18；2886 BS p10–11、IS p12–13、CF p15–16；
  2887 BS p10–11、IS p12–13、CF p15–16；2891 BS p8、IS p9、CF p11–12。
  （2882／2885／2887／2891 頁碼由 FS_HEADING_ANCHORS 與標題文字搜尋於快取定位；權益變動表頁不收。）
JSON 形狀：{ticker: {"_source": 說明, "fs_anchors": {key: [start, end] | null}, "doc": <pdf_doc.to_json 輸出>}}
  - fs_anchors：`find_heading_sections(doc, FS_HEADING_ANCHORS)` 的頁範圍（原 PDF 頁碼）
  - doc：只含上列頁
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

from runtime.tw_equity import pdf_doc as _pdf_doc  # noqa: E402
from runtime.tw_equity.doc_anchor import FS_HEADING_ANCHORS, find_heading_sections  # noqa: E402

_PDF_DIR = _REPO_ROOT / "tw_report"
_OUT_PATH = Path(__file__).resolve().parent / "fh_statements_pages.json"
_PAGES: dict[str, list[int]] = {
    "2881": [8, 9, 10, 11, 12],
    "2882": [9, 10, 12, 13],
    "2885": [12, 13, 14, 15, 17, 18],
    "2886": [10, 11, 12, 13, 15, 16],
    "2887": [10, 11, 12, 13, 15, 16],
    "2891": [8, 9, 11, 12],
}


def _pdf_path(pdf_dir: Path, ticker: str) -> Path:
    return pdf_dir / f"{ticker}_2026Q2財報.pdf"


def _extract_one(pdf_path: Path, ticker: str) -> dict:
    doc = _pdf_doc.load_pdf(pdf_path)
    anchors = find_heading_sections(doc, FS_HEADING_ANCHORS, required=set())
    pages = [p for p in doc.pages if p.number in _PAGES[ticker]]
    sub = _pdf_doc.PdfDoc(path=Path(f"tw_report/{ticker}_2026Q2財報.pdf"), pages=pages)
    return {
        "_source": f"tw_report/{ticker}_2026Q2財報.pdf p{','.join(str(n) for n in _PAGES[ticker])}"
        "（pdf_doc 頁文字輸出；Spec fh-schema §0.4 F2）",
        "fs_anchors": {k: ([r.start, r.end] if r is not None else None) for k, r in anchors.items()},
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
