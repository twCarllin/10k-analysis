"""test_inputs.py — TwEquityInputs dataclass 與 load_inputs 單元測試。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.tw_equity.inputs import TwEquityInputs, load_inputs


# ── fixture helpers ──────────────────────────────────────────────────────────

def _write_json(directory: Path, ticker: str, data: dict) -> None:
    inputs_dir = directory / "tw_equity_inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    (inputs_dir / f"{ticker}.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


def _make_pdf(directory: Path, rel_path: str) -> Path:
    """在 directory 下建立假 PDF 檔案，回傳相對路徑字串對應的絕對路徑。"""
    p = directory / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"%PDF-1.4 fake")
    return p


# ── 成功路徑 ─────────────────────────────────────────────────────────────────

class TestLoadInputsSuccess:
    def test_returns_tw_equity_inputs(self, tmp_path):
        """合法 json（3653）→ 回傳 TwEquityInputs 實例。"""
        _make_pdf(tmp_path, "tw_report/2025_3653.pdf")
        _write_json(tmp_path, "3653", {
            "ticker": "3653",
            "company_name": "健策精密工業股份有限公司",
            "fiscal_year": 2025,
            "annual_report_path": "tw_report/2025_3653.pdf",
        })
        result = load_inputs("3653", base_dir=tmp_path)
        assert isinstance(result, TwEquityInputs)

    def test_required_fields_correct(self, tmp_path):
        """必填欄位值正確對應。"""
        _make_pdf(tmp_path, "tw_report/2025_3653.pdf")
        _write_json(tmp_path, "3653", {
            "ticker": "3653",
            "company_name": "健策精密工業股份有限公司",
            "fiscal_year": 2025,
            "annual_report_path": "tw_report/2025_3653.pdf",
        })
        result = load_inputs("3653", base_dir=tmp_path)
        assert result.ticker == "3653"
        assert result.company_name == "健策精密工業股份有限公司"
        assert result.fiscal_year == 2025
        assert result.annual_report_path.name == "2025_3653.pdf"

    def test_roc_year_equals_fiscal_year_minus_1911(self, tmp_path):
        """roc_year == fiscal_year - 1911（2025 → 114）。"""
        _make_pdf(tmp_path, "tw_report/2025_3653.pdf")
        _write_json(tmp_path, "3653", {
            "ticker": "3653",
            "company_name": "健策精密工業股份有限公司",
            "fiscal_year": 2025,
            "annual_report_path": "tw_report/2025_3653.pdf",
        })
        result = load_inputs("3653", base_dir=tmp_path)
        assert result.roc_year == 114

    def test_consolidated_fs_path_null_becomes_none(self, tmp_path):
        """consolidated_fs_path 為 null → 欄值 None。"""
        _make_pdf(tmp_path, "tw_report/2025_3653.pdf")
        _write_json(tmp_path, "3653", {
            "ticker": "3653",
            "company_name": "健策精密工業股份有限公司",
            "fiscal_year": 2025,
            "annual_report_path": "tw_report/2025_3653.pdf",
            "consolidated_fs_path": None,
        })
        result = load_inputs("3653", base_dir=tmp_path)
        assert result.consolidated_fs_path is None

    def test_consolidated_fs_path_missing_key_becomes_none(self, tmp_path):
        """consolidated_fs_path 缺 key → 欄值 None（視同 null）。"""
        _make_pdf(tmp_path, "tw_report/2025_3653.pdf")
        _write_json(tmp_path, "3653", {
            "ticker": "3653",
            "company_name": "健策精密工業股份有限公司",
            "fiscal_year": 2025,
            "annual_report_path": "tw_report/2025_3653.pdf",
        })
        result = load_inputs("3653", base_dir=tmp_path)
        assert result.consolidated_fs_path is None
        assert result.parent_fs_path is None


# ── 缺必填欄 ─────────────────────────────────────────────────────────────────

class TestMissingRequiredFields:
    def test_missing_annual_report_path_raises_value_error_with_field_name(self, tmp_path):
        """缺 annual_report_path → ValueError 含欄名。"""
        _write_json(tmp_path, "3653", {
            "ticker": "3653",
            "company_name": "健策精密工業股份有限公司",
            "fiscal_year": 2025,
        })
        with pytest.raises(ValueError) as exc_info:
            load_inputs("3653", base_dir=tmp_path)
        assert "annual_report_path" in str(exc_info.value)

    def test_missing_company_name_raises_value_error_with_field_name(self, tmp_path):
        """缺 company_name → ValueError 含欄名。"""
        _write_json(tmp_path, "3653", {
            "ticker": "3653",
            "fiscal_year": 2025,
            "annual_report_path": "tw_report/x.pdf",
        })
        with pytest.raises(ValueError) as exc_info:
            load_inputs("3653", base_dir=tmp_path)
        assert "company_name" in str(exc_info.value)

    def test_missing_ticker_raises_value_error_with_field_name(self, tmp_path):
        """缺 ticker → ValueError 含欄名。"""
        _write_json(tmp_path, "3653", {
            "company_name": "健策精密工業股份有限公司",
            "fiscal_year": 2025,
            "annual_report_path": "tw_report/x.pdf",
        })
        with pytest.raises(ValueError) as exc_info:
            load_inputs("3653", base_dir=tmp_path)
        assert "ticker" in str(exc_info.value)


# ── 型別錯誤 ─────────────────────────────────────────────────────────────────

class TestWrongTypes:
    def test_fiscal_year_as_string_raises_value_error_with_field_name(self, tmp_path):
        """fiscal_year 非 int（字串）→ ValueError 含欄名。"""
        _write_json(tmp_path, "3653", {
            "ticker": "3653",
            "company_name": "健策精密工業股份有限公司",
            "fiscal_year": "2025",
            "annual_report_path": "tw_report/x.pdf",
        })
        with pytest.raises(ValueError) as exc_info:
            load_inputs("3653", base_dir=tmp_path)
        assert "fiscal_year" in str(exc_info.value)


# ── 缺檔 ─────────────────────────────────────────────────────────────────────

class TestFileMissing:
    def test_input_json_not_found_raises_file_not_found_error(self, tmp_path):
        """JSON 輸入檔不存在 → FileNotFoundError（非 ValueError）。"""
        with pytest.raises(FileNotFoundError):
            load_inputs("9999", base_dir=tmp_path)

    def test_annual_report_pdf_not_found_raises_file_not_found_error(self, tmp_path):
        """annual_report_path 存在但檔不存在 → FileNotFoundError。"""
        _write_json(tmp_path, "3653", {
            "ticker": "3653",
            "company_name": "健策精密工業股份有限公司",
            "fiscal_year": 2025,
            "annual_report_path": "tw_report/nonexistent.pdf",
        })
        with pytest.raises(FileNotFoundError):
            load_inputs("3653", base_dir=tmp_path)

    def test_optional_path_not_found_raises_file_not_found_error(self, tmp_path):
        """consolidated_fs_path 給了路徑但檔不存在 → FileNotFoundError。"""
        _make_pdf(tmp_path, "tw_report/annual.pdf")
        _write_json(tmp_path, "3653", {
            "ticker": "3653",
            "company_name": "健策精密工業股份有限公司",
            "fiscal_year": 2025,
            "annual_report_path": "tw_report/annual.pdf",
            "consolidated_fs_path": "tw_report/nonexistent_consolidated.pdf",
        })
        with pytest.raises(FileNotFoundError):
            load_inputs("3653", base_dir=tmp_path)
