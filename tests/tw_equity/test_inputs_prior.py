"""test_inputs_prior.py — TwEquityInputs.prior 解析與驗證（1B-2 §1.1）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.tw_equity.inputs import PriorYearInputs, load_inputs


def _setup(tmp_path: Path, prior=..., prior_year=2024, prior_pdf=True) -> None:
    (tmp_path / "tw_report").mkdir(exist_ok=True)
    (tmp_path / "tw_report" / "cur.pdf").write_bytes(b"%PDF-1.4 fake")
    if prior_pdf:
        (tmp_path / "tw_report" / "prior.pdf").write_bytes(b"%PDF-1.4 fake")
    data = {
        "ticker": "3653", "company_name": "健策", "fiscal_year": 2025,
        "annual_report_path": "tw_report/cur.pdf",
    }
    if prior is ...:
        prior = {
            "fiscal_year": prior_year,
            "annual_report_path": "tw_report/prior.pdf",
            "consolidated_fs_path": None, "parent_fs_path": None,
        }
    if prior is not ...:
        data["prior"] = prior
    d = tmp_path / "tw_equity_inputs"
    d.mkdir(exist_ok=True)
    (d / "3653.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_no_prior_key_is_none(tmp_path):
    _setup(tmp_path, prior=None)
    # prior=None 會寫入 null；另測完全無鍵
    p = tmp_path / "tw_equity_inputs" / "3653.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d.pop("prior")
    p.write_text(json.dumps(d), encoding="utf-8")
    assert load_inputs("3653", base_dir=tmp_path).prior is None


def test_prior_null_is_none(tmp_path):
    _setup(tmp_path, prior=None)
    assert load_inputs("3653", base_dir=tmp_path).prior is None


def test_full_prior(tmp_path):
    _setup(tmp_path)
    prior = load_inputs("3653", base_dir=tmp_path).prior
    assert isinstance(prior, PriorYearInputs)
    assert prior.fiscal_year == 2024
    assert prior.roc_year == 113
    assert prior.annual_report_path == tmp_path / "tw_report" / "prior.pdf"
    assert prior.consolidated_fs_path is None
    assert prior.parent_fs_path is None


def test_prior_year_not_consecutive(tmp_path):
    _setup(tmp_path, prior_year=2023)
    with pytest.raises(ValueError) as ei:
        load_inputs("3653", base_dir=tmp_path)
    assert "2025" in str(ei.value) and "2023" in str(ei.value)


def test_prior_pdf_missing(tmp_path):
    _setup(tmp_path, prior_pdf=False)
    with pytest.raises(FileNotFoundError):
        load_inputs("3653", base_dir=tmp_path)
