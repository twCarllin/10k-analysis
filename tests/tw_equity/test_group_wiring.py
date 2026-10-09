"""group 接線（fh-schema Spec §2.5；task 1.4）。

契約 row：
  G1: 輸入檔含 "group": "fh" → TwEquityInputs.group == "fh"
  G2: 輸入檔無 group → None
  G3: extract_tables(..., group="fh") → bundle.statements.schema == "fh"
  G4: group=None → schema == "industrial" 且 bundle.to_dict() 與未傳 group 者逐值相同
  G5: [邊界] group="industrial"（任意非 fh 值）→ 走工業流程、不報錯
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.tw_equity import pdf_doc  # noqa: E402
from runtime.tw_equity.doc_anchor import PageRange  # noqa: E402
from runtime.tw_equity.inputs import load_inputs  # noqa: E402
from runtime.tw_equity.tables import extract_tables  # noqa: E402

_FIX = ROOT / "tests/fixtures/tw_equity"
_FH = json.loads((_FIX / "fh_statements_pages.json").read_text(encoding="utf-8"))["2881"]


def _write(tmp_path: Path, extra: dict) -> None:
    pdf = tmp_path / "ar.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    d = tmp_path / "tw_equity_inputs"
    d.mkdir()
    (d / "2881.json").write_text(json.dumps({
        "ticker": "2881", "company_name": "富邦金", "fiscal_year": 2025,
        "annual_report_path": "ar.pdf", **extra,
    }, ensure_ascii=False), encoding="utf-8")


def test_inputs_group_fh(tmp_path) -> None:
    _write(tmp_path, {"group": "fh"})
    assert load_inputs("2881", base_dir=tmp_path).group == "fh"


def test_inputs_group_absent_is_none(tmp_path) -> None:
    _write(tmp_path, {})
    assert load_inputs("2881", base_dir=tmp_path).group is None


def _bundle(**kw):
    fs = pdf_doc.from_json(_FH["doc"])
    anchors = {k: (PageRange(*r) if r else None) for k, r in _FH["fs_anchors"].items()}
    ar = pdf_doc.PdfDoc(path=Path(""), pages=[])
    return extract_tables(ar, {}, fs, anchors, None, None, roc_year=115, **kw)


def test_extract_tables_group_fh_sets_schema() -> None:
    assert _bundle(group="fh").statements.schema == "fh"


def test_extract_tables_group_none_matches_default_industrial() -> None:
    b_none, b_default = _bundle(group=None), _bundle()
    assert b_none.statements.schema == "industrial"
    assert b_none.to_dict() == b_default.to_dict()


@pytest.mark.parametrize("group", ["industrial", "xyz"])
def test_extract_tables_non_fh_group_is_industrial(group) -> None:
    assert _bundle(group=group).statements.schema == "industrial"
