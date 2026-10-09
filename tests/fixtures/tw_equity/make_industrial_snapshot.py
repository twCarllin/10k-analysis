"""make_industrial_snapshot.py — 產生 industrial_snapshot.json（run 2026-10-09-tw-equity-fh-schema item 1.2）。

快照＝本 run 修改 statements.py 之前（HEAD 行為）的工業帳本 `to_dict()`，供「工業股回歸不變」測試鎖定。
來源（皆為既有 fixture，不讀 data/cache）：
  - fs_3653_pages.json（3653 年度財報，anchors 取 find_heading_sections(doc, FS_HEADING_ANCHORS)）
  - fs_h1_pages.json 的 2059、2308 半年報（anchors 取該檔 fs_anchors）
快照內容：每家 rows／checks／unmapped_labels（to_dict 對應鍵）。
注意：本檔不被測試載入；於 statements.py 改動前執行一次，之後勿重跑覆蓋。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

from runtime.tw_equity import pdf_doc  # noqa: E402
from runtime.tw_equity.doc_anchor import FS_HEADING_ANCHORS, PageRange, find_heading_sections  # noqa: E402
from runtime.tw_equity.statements import extract_statements  # noqa: E402

_FIX = Path(__file__).resolve().parent
_KEYS = ("rows", "checks", "unmapped_labels")


def _pick(led) -> dict:
    d = led.to_dict()
    return {k: d[k] for k in _KEYS}


def produce() -> dict:
    out: dict = {}
    doc = pdf_doc.from_json(json.loads((_FIX / "fs_3653_pages.json").read_text(encoding="utf-8")))
    anchors = find_heading_sections(doc, FS_HEADING_ANCHORS, required=set())
    out["3653_FY"] = {
        "_source": "tests/fixtures/tw_equity/fs_3653_pages.json（HEAD 12cadec 行為）",
        **_pick(extract_statements(doc, anchors)),
    }
    h1 = json.loads((_FIX / "fs_h1_pages.json").read_text(encoding="utf-8"))
    for t in ("2059", "2308"):
        e = h1[t]
        a = {k: (PageRange(*r) if r else None) for k, r in e["fs_anchors"].items()}
        out[f"{t}_H1"] = {
            "_source": f"tests/fixtures/tw_equity/fs_h1_pages.json[{t}]（HEAD 12cadec 行為）",
            **_pick(extract_statements(pdf_doc.from_json(e["doc"]), a)),
        }
    return out


if __name__ == "__main__":
    (_FIX / "industrial_snapshot.json").write_text(
        json.dumps(produce(), ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )
    print("ok")
