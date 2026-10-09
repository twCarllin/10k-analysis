"""make_industrial_batch_record.py — 產生 industrial_batch_record.json（run 2026-10-09-tw-equity-fh-schema item 5.5）。

快照＝本 run 修改 batch.py 之前（HEAD 12cadec）的 `_empty_record`／`_fill` 對 3653 年度帳本產生的工業記錄。
舊 batch.py 以 `git show HEAD:runtime/tw_equity/batch.py` 取得（需在 batch.py 尚未提交本 run 變更時執行）。
本檔不被測試載入；執行一次後勿重跑覆蓋。
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

from runtime.tw_equity import pdf_doc  # noqa: E402
from runtime.tw_equity.doc_anchor import FS_HEADING_ANCHORS, find_heading_sections  # noqa: E402
from runtime.tw_equity.metrics import compute_metrics  # noqa: E402
from runtime.tw_equity.statements import extract_statements  # noqa: E402

_FIX = Path(__file__).resolve().parent


def produce() -> dict:
    src = subprocess.run(["git", "show", "HEAD:runtime/tw_equity/batch.py"], capture_output=True, text=True,
                         check=True, cwd=_REPO_ROOT).stdout
    old = types.ModuleType("old_batch")
    exec(compile(src, "old_batch.py", "exec"), old.__dict__)
    doc = pdf_doc.from_json(json.loads((_FIX / "fs_3653_pages.json").read_text(encoding="utf-8")))
    led = extract_statements(doc, find_heading_sections(doc, FS_HEADING_ANCHORS, required=set()))
    rec = old._empty_record("3653")
    old._fill(rec, SimpleNamespace(statements=led, metrics=compute_metrics(led), fy_income=None))
    rec["status"] = "ok"
    return rec


if __name__ == "__main__":
    (_FIX / "industrial_batch_record.json").write_text(
        json.dumps(produce(), ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
