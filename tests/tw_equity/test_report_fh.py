"""test_report_fh.py — run 2026-10-09-tw-equity-fh-schema item 5.4：金控附錄 E（Spec §8.3）。

契約表：
  E1: fh bundle → 含 npl_ratio 名稱「逾放比」、group_car 行含期間與「stale」、「不可得」節列出 RBC
  E2: ifrs17_break True → 含 IFRS 17 說明句
  E3: 工業 bundle → 附錄 E 與改動前快照逐字相同（sha256）
  E4: [邊界] fh_notes 為 None → 不拋例外、附註指標行標「不可得」
  E5: [組合] fh × TTM parent_only → TTM 小節只列歸母淨利一列
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.tw_equity.inputs import TwEquityInputs  # noqa: E402
from runtime.tw_equity.metrics import compute_metrics  # noqa: E402
from runtime.tw_equity.report import save_tw_equity_report  # noqa: E402
from runtime.tw_equity.tables import TablesBundle  # noqa: E402
from tests.tw_equity.test_fh_batch_integration import build_fh_bundle  # noqa: E402
from tests.tw_equity.test_report_metrics import _bundle as _ind_bundle  # noqa: E402
from tests.tw_equity.test_report_metrics import _ledger as _ind_ledger  # noqa: E402

_KL = {k: (None, None) for k in ["營業收入", "營業成本", "營業毛利", "營業費用", "營業利益", "本期淨利"]}
# 改動前（本 item 前）工業附錄 E 的 sha256：由 test_report_metrics 的 _bundle(compute_metrics(_ledger())) 渲染
_IND_APPENDIX_E_SHA = "28752b364e783490e20f071620e0a324c42d276e0ccbdd7a13a01057c3ac186d"  # 2026-10-11（cf-bridge Spec §2.1：cfo／cfi／cff 組成項依區段、加合成項；此帳本 cfo 區段無明細列 → cfo bridge 只剩合成項 other_operating_cf＝300/100/Δ200，殘差 0；舊 SHA d000d63a…）：有效稅率公式字串、淨利 bridge 新組成項（spec 2026-10-11-tw-equity-sign-fix §2 B、§6 A3）；淨利 bridge 再加 ecl_operating、discontinued_ops 與兩個合成項（spec 2026-10-11-tw-equity-bridge-residual §2.1）


def _fh_bundle(b: SimpleNamespace, **override) -> TablesBundle:
    kw = dict(statements=b.statements, metrics=b.metrics, fy_income=b.fy_income, fh_notes=b.fh_notes)
    kw.update(override)
    return TablesBundle(None, None, None, None, None, None, None, None, None, None,
                        dict(_KL), dict(_KL), None, [], {}, **kw)


def _appendix_e(tmp_path, bundle: TablesBundle, ticker="2881") -> str:
    inputs = TwEquityInputs(ticker=ticker, company_name="金控", fiscal_year=2025,
                            annual_report_path=tmp_path / "ar.pdf", consolidated_fs_path=None, parent_fs_path=None)
    md = save_tw_equity_report(inputs=inputs, bundle=bundle, anchors_summary={}, skill_results={},
                               eval_results={}, skipped_tasks=[], out_dir=tmp_path)
    text = md.read_text(encoding="utf-8")
    return text[text.index("## 附錄 E"):]


def test_fh_appendix_e_metrics_source_unavailable_and_ifrs17(tmp_path):  # E1／E2
    sec = _appendix_e(tmp_path, _fh_bundle(build_fh_bundle("2881")))
    assert "逾放比（npl_ratio）" in sec
    car = next(x for x in sec.splitlines() if "（group_car）" in x)
    assert "114-06-30" in car and "stale" in car
    assert "### 不可得項目" in sec and "保險 RBC" in sec[sec.index("### 不可得項目"):]
    assert "IFRS 17 斷層：是" in sec and "FY 為 IFRS 4、H1 為 IFRS 17" in sec
    assert "淨利變動（net_income）" in sec


def test_fh_notes_none_does_not_raise_and_marks_unavailable(tmp_path):  # E4
    b = build_fh_bundle("2881")
    metrics = compute_metrics(b.statements, b.fy_income, group="fh", notes=None)
    sec = _appendix_e(tmp_path, _fh_bundle(b, metrics=metrics, fh_notes=None))
    for key in ("group_car", "npl_ratio", "coverage_ratio"):
        row = next(x for x in sec.splitlines() if f"（{key}）" in x)
        assert "不可得" in row
    assert "附註未取得" in sec


def test_fh_parent_only_ttm_lists_only_parent_net_income(tmp_path):  # E5
    sec = _appendix_e(tmp_path, _fh_bundle(build_fh_bundle("2882")))
    comp = sec[sec.index("#### TTM 損益組成"):]
    comp = comp[:comp.index("####", 5)] if "####" in comp[5:] else comp
    data_rows = [x for x in comp.splitlines() if x.startswith("| ") and not x.startswith("| 科目")]
    assert len(data_rows) == 1 and data_rows[0].startswith("| net_income_parent")
    assert "歸母" in sec[sec.index("### TTM vs FY"):]


def test_industrial_appendix_e_unchanged(tmp_path):  # E3
    sec = _appendix_e(tmp_path, _ind_bundle(compute_metrics(_ind_ledger())), ticker="3653")
    assert hashlib.sha256(sec.encode()).hexdigest() == _IND_APPENDIX_E_SHA
