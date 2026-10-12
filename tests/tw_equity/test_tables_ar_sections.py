"""TablesBundle 接入年報三章節（run 2026-10-12-tw-equity-ar-sections item 2.1）。

契約 row（item 2.1 DoD）：
  T1: extract_tables 帶上 ar_cashflow／ar_contracts／ar_special（含口徑 basis）；ar_sections_error 為 None
  T2: to_dict 只在非 None 時輸出 ar_cashflow／ar_contracts／ar_special／ar_sections_error；既有欄位不變
  T3: ar_sections 例外不中斷其他表的解析：ar_sections_error "<類型>: <訊息>"、三欄位 None、
      其他表（fin_performance、statements、metrics）與無例外時相同、終端機有警示
測試只用公開介面；例外注入點是三個解析器模組函式（無法用輸入造出例外，比照 test_tables_metrics 的 fy_income 作法）。
"""

import dataclasses
import json
from pathlib import Path

import pytest

from runtime.tw_equity.doc_anchor import (FS_HEADING_ANCHORS, find_annual_report_sections,
                                          find_heading_sections)
from runtime.tw_equity.pdf_doc import from_json
from runtime.tw_equity.tables import extract_tables

_FIX = Path(__file__).parent.parent / "fixtures" / "tw_equity"
_AR_PAGES = _FIX / "ar_sections_pages.json"

pytestmark = pytest.mark.skipif(not _AR_PAGES.exists(), reason="金標 fixture 不存在")

_AR_KEYS = ("ar_cashflow", "ar_contracts", "ar_special", "ar_sections_error")


def _ar():
    doc = from_json(json.loads(_AR_PAGES.read_text(encoding="utf-8"))["3653"])
    return doc, find_annual_report_sections(doc, required=set())


def _fs():
    fs = from_json(json.loads((_FIX / "fs_3653_pages.json").read_text(encoding="utf-8")))
    return fs, find_heading_sections(fs, FS_HEADING_ANCHORS, required=set())


def _bundle(with_fs: bool = True):
    doc, ara = _ar()
    fs, fsa = _fs() if with_fs else (None, None)
    return extract_tables(doc, ara, fs, fsa, None, None, roc_year=114)


def test_extract_tables_carries_three_sections_with_basis():
    """T1：3653 年報三章節都有結果；合併全年帳本（FY）的期初、年底現金與表 A 相符 → consolidated。"""
    b = _bundle()
    assert b.ar_sections_error is None
    assert b.ar_cashflow.status == "parsed" and b.ar_cashflow.actual.closing_cash == 9134067
    assert b.ar_cashflow.basis == "consolidated"
    assert b.ar_contracts.status == "parsed" and len(b.ar_contracts.rows) == 3
    assert b.ar_special.status == "parsed"
    d = b.to_dict()
    assert d["ar_cashflow"]["basis"] == "consolidated" and d["ar_cashflow"]["status"] == "parsed"
    assert d["ar_contracts"]["status"] == "parsed" and d["ar_special"]["status"] == "parsed"
    assert "ar_sections_error" not in d
    json.dumps(d)


def test_without_fs_basis_unknown():
    """T1 邊界：沒有合併財報（無帳本）→ 章節照解析，basis unknown。"""
    b = _bundle(with_fs=False)
    assert b.statements is None
    assert b.ar_cashflow.status == "parsed" and b.ar_cashflow.basis == "unknown"


def test_to_dict_outputs_ar_fields_only_when_not_none():
    """T2：欄位為 None 時 to_dict 沒有該 key；非 None 才輸出；既有欄位不變。"""
    b = _bundle()
    full = b.to_dict()
    for k in ("ar_cashflow", "ar_contracts", "ar_special"):
        assert isinstance(full[k], dict)
    none_all = dataclasses.replace(b, ar_cashflow=None, ar_contracts=None, ar_special=None).to_dict()
    assert not any(k in none_all for k in _AR_KEYS)
    assert set(full) - set(none_all) == {"ar_cashflow", "ar_contracts", "ar_special"}
    only_cf = dataclasses.replace(b, ar_contracts=None, ar_special=None).to_dict()
    assert "ar_cashflow" in only_cf and "ar_contracts" not in only_cf and "ar_special" not in only_cf
    for k in ("fin_performance", "statements", "metrics", "fy_income", "fy_income_error", "missing_tables"):
        assert k in none_all
    with_err = dataclasses.replace(b, ar_sections_error="ValueError: x").to_dict()
    assert with_err["ar_sections_error"] == "ValueError: x"


@pytest.mark.parametrize("which", ["parse_cashflow", "parse_contracts", "parse_special"])
def test_ar_sections_exception_does_not_break_other_tables(which, monkeypatch, capsys, caplog):
    """T3：任一解析器拋例外 → ar_sections_error 記錄、三欄位 None；其他表與無例外時相同。"""
    import runtime.tw_equity.ar_sections as mod

    base = _bundle()

    def boom(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(mod, which, boom)
    with caplog.at_level("WARNING", logger="runtime.tw_equity.tables"):
        b = _bundle()
    assert b.ar_sections_error == "RuntimeError: boom"
    assert b.ar_cashflow is None and b.ar_contracts is None and b.ar_special is None
    d = b.to_dict()
    assert d["ar_sections_error"] == "RuntimeError: boom"
    assert not any(k in d for k in ("ar_cashflow", "ar_contracts", "ar_special"))
    out = capsys.readouterr().out
    assert "[tw-equity 警示]" in out and "RuntimeError: boom" in out
    assert any("RuntimeError: boom" in r.getMessage() for r in caplog.records)
    ref = base.to_dict()
    for k in set(ref) - set(_AR_KEYS):
        assert d[k] == ref[k], k
    assert b.statements is not None and b.metrics is not None
