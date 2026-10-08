"""main.py --market tw-equity 分支測試（契約：Spec §1.2、task item 4.5）。

真 import：不 patch sys.modules 假模組；in-process 測試只 patch 真實模組的
pipeline 函式屬性（邊界：避免真跑 pipeline）。
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "runtime"))

_PY = ROOT / ".venv" / "bin" / "python"


def _load_main():
    spec = importlib.util.spec_from_file_location("main_under_test", str(ROOT / "main.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def main_mod():
    return _load_main()


def _run(main_mod, argv):
    with mock.patch.object(sys, "argv", ["main.py"] + argv):
        with pytest.raises(SystemExit) as ei:
            main_mod.main()
    return ei.value.code


def test_real_import_missing_input_exits_1_without_import_error(tmp_path):
    """無 mock 真 import：走到輸入檔不存在的錯誤路徑、exit 1。"""
    proc = subprocess.run(
        [str(_PY), str(ROOT / "main.py"), "NOPE", "--market", "tw-equity", "--dry-run"],
        cwd=tmp_path, capture_output=True, text=True, timeout=120,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "ImportError" not in out and "ModuleNotFoundError" not in out
    assert "[tw-equity]" in out


def test_tw_equity_success_exit_0_and_calls_pipeline(main_mod, capsys):
    import runtime.tw_equity.tw_pipeline as real
    seen = {}

    def fake(ticker, *, dry_run=False, base_dir=None, ocr=False):
        seen["args"] = (ticker, dry_run)
        return Path("x.md")

    with mock.patch.object(real, "run_tw_equity_pipeline", fake):
        code = _run(main_mod, ["3653", "--market", "tw-equity", "--dry-run"])
    assert code == 0
    assert seen["args"] == ("3653", True)


def test_tw_equity_validation_error_exit_1(main_mod, capsys):
    import runtime.tw_equity.tw_pipeline as real

    def boom(ticker, **kw):
        raise ValueError("缺欄位")

    with mock.patch.object(real, "run_tw_equity_pipeline", boom):
        code = _run(main_mod, ["3653", "--market", "tw-equity"])
    assert code == 1
    assert "[tw-equity] 缺欄位" in capsys.readouterr().out


def test_year_positional_prints_ignore_notice(main_mod, capsys):
    import runtime.tw_equity.tw_pipeline as real
    with mock.patch.object(real, "run_tw_equity_pipeline", lambda t, **kw: Path("x.md")):
        code = _run(main_mod, ["3653", "2025", "--market", "tw-equity"])
    assert code == 0
    assert "year" in capsys.readouterr().out


def test_missing_ticker_exits_nonzero(main_mod):
    assert _run(main_mod, ["--market", "tw-equity"]) != 0


def test_market_tw_still_routes_to_credit_branch(main_mod):
    import runtime.tw_credit.tw_pipeline as credit
    import runtime.tw_equity.tw_pipeline as equity
    called = {}

    def fake_credit(ticker, **kw):
        called["credit"] = ticker
        return {"status": "completed"}

    with mock.patch.object(credit, "run_tw_pipeline", fake_credit), \
         mock.patch.object(equity, "run_tw_equity_pipeline",
                           side_effect=AssertionError("tw 不得走 tw-equity")):
        code = _run(main_mod, ["3653", "--market", "tw"])
    assert code == 0
    assert called["credit"] == "3653"


def _ocr_seen(main_mod, argv):
    import runtime.tw_equity.tw_pipeline as real
    seen = {}

    def fake(ticker, **kw):
        seen.update(kw)
        return Path("x.md")

    with mock.patch.object(real, "run_tw_equity_pipeline", fake):
        code = _run(main_mod, argv)
    assert code == 0
    return seen


def test_ocr_flag_defaults_false(main_mod):
    seen = _ocr_seen(main_mod, ["3653", "--market", "tw-equity", "--dry-run"])
    assert seen["ocr"] is False


def test_ocr_flag_passes_true(main_mod):
    seen = _ocr_seen(main_mod, ["3653", "--market", "tw-equity", "--ocr"])
    assert seen["ocr"] is True


def test_dry_run_and_ocr_both_passed(main_mod):
    seen = _ocr_seen(main_mod, ["3653", "--market", "tw-equity", "--dry-run", "--ocr"])
    assert seen["dry_run"] is True and seen["ocr"] is True


def test_ocr_flag_on_tw_credit_branch_not_passed(main_mod):
    import runtime.tw_credit.tw_pipeline as credit
    got = {}

    def fake_credit(ticker, **kw):
        got.update(kw)
        return {"status": "completed"}

    with mock.patch.object(credit, "run_tw_pipeline", fake_credit):
        code = _run(main_mod, ["3653", "--market", "tw", "--ocr"])
    assert code == 0
    assert "ocr" not in got
