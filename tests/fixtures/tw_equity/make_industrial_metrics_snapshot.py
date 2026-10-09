"""make_industrial_metrics_snapshot.py — 產生 industrial_metrics_snapshot.json（run 2026-10-09-tw-equity-fh-schema item 3.1）。

快照＝本 item 修改 metrics.py 之前的 `compute_metrics(ledger).to_dict()`（工業帳本，fy_income=None），
供「group 非 fh 輸出逐值不變」測試鎖定。來源同 make_industrial_snapshot.py。勿於 metrics.py 改動後重跑覆蓋。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

from runtime.tw_equity import pdf_doc  # noqa: E402
from runtime.tw_equity.doc_anchor import FS_HEADING_ANCHORS, PageRange, find_heading_sections  # noqa: E402
from runtime.tw_equity.metrics import compute_metrics  # noqa: E402
from runtime.tw_equity.statements import extract_statements  # noqa: E402

FIX = Path(__file__).resolve().parent


def ledgers() -> dict:
    out: dict = {}
    doc = pdf_doc.from_json(json.loads((FIX / "fs_3653_pages.json").read_text(encoding="utf-8")))
    anchors = find_heading_sections(doc, FS_HEADING_ANCHORS, required=set())
    out["3653_FY"] = extract_statements(doc, anchors)
    h1 = json.loads((FIX / "fs_h1_pages.json").read_text(encoding="utf-8"))
    for t in ("2059", "2308"):
        e = h1[t]
        a = {k: (PageRange(*r) if r else None) for k, r in e["fs_anchors"].items()}
        out[f"{t}_H1"] = extract_statements(pdf_doc.from_json(e["doc"]), a)
    return out


if __name__ == "__main__":
    snap = {k: compute_metrics(v).to_dict() for k, v in ledgers().items()}
    (FIX / "industrial_metrics_snapshot.json").write_text(
        json.dumps(snap, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    print("ok")
