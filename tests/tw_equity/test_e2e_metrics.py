"""dry-run 全管線含 metrics（run 2026-10-09-tw-equity-metrics-t1 item 2.3）。"""
import pytest

from tests.tw_equity.test_e2e_statements import _run  # 既有 e2e helper（ar＋fs fixture → md 文字、raw dict）


def test_dry_run_metrics_in_raw_and_appendix_e(tmp_path, monkeypatch):
    md, raw = _run(tmp_path, monkeypatch, with_fs=True)
    assert raw["bundle"]["metrics"]["index"]["fcf"]["current"] == pytest.approx(3943937, abs=1)
    assert "## 附錄 E" in md


def test_dry_run_without_fs_metrics_null(tmp_path, monkeypatch):
    md, raw = _run(tmp_path, monkeypatch, with_fs=False)
    assert raw["bundle"]["metrics"] is None
    assert "未計算指標" in md[md.index("## 附錄 E"):]
