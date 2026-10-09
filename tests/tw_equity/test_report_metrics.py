"""報告附錄 E（run 2026-10-09-tw-equity-metrics-t1 item 2.2）。"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "runtime"))

from runtime.tw_equity.inputs import TwEquityInputs
from runtime.tw_equity.metrics import compute_metrics
from runtime.tw_equity.report import save_tw_equity_report
from runtime.tw_equity.statements import StatementLedger, StatementRow
from runtime.tw_equity.tables import TablesBundle

_KL = {k: (None, None) for k in ["營業收入", "營業成本", "營業毛利", "營業費用", "營業利益", "本期淨利"]}


def _bundle(metrics):
    return TablesBundle(None, None, None, None, None, None, None, None, None, None,
                        dict(_KL), dict(_KL), None, [], {}, metrics=metrics)


def _ledger():
    rows = [StatementRow("cf", None, k, k, None, c, p, None, None, 1, i) for i, (k, (c, p)) in
            enumerate({"cfo": (300, 100), "capex": (-50, -20), "revenue": (1000, 800)}.items())]
    return StatementLedger("仟元", "114", "113", rows, [], [])


def _run(tmp_path, bundle):
    inputs = TwEquityInputs(ticker="3653", company_name="健策", fiscal_year=2025,
                            annual_report_path=tmp_path / "ar.pdf", consolidated_fs_path=None, parent_fs_path=None)
    md = save_tw_equity_report(inputs=inputs, bundle=bundle, anchors_summary={}, skill_results={},
                               eval_results={}, skipped_tasks=[], out_dir=tmp_path)
    raw = json.loads(next(tmp_path.glob("*_raw.json")).read_text(encoding="utf-8"))
    return md.read_text(encoding="utf-8"), raw


def test_appendix_e_with_metrics(tmp_path):
    text, raw = _run(tmp_path, _bundle(compute_metrics(_ledger())))
    sec = text[text.index("## 附錄 E"):]
    assert "自由現金流（fcf）" in sec and "cfo + capex" in sec
    table = sec[sec.index("### 指標"):sec.index("### 變動歸因")]
    assert len([l for l in table.splitlines() if l.startswith("| ") and "（" in l]) == 30
    assert len(re.findall(r"^#### ", sec, flags=re.M)) == 8
    assert "| 殘差 |" in sec
    assert "| 毛利率（gross_margin） | gross_profit / revenue * 100 | — | — | % |" in sec  # None → —
    assert raw["bundle"]["metrics"]["index"]["fcf"]["current"] == 250


def test_appendix_e_without_metrics(tmp_path):
    text, raw = _run(tmp_path, _bundle(None))
    assert "未計算指標" in text[text.index("## 附錄 E"):]
    assert raw["bundle"]["metrics"] is None
    assert text.index("## 附錄 D") < text.index("## 附錄 E")


# ── item 3.3：附錄 E 期間行與 TTM vs FY 小節。契約 row：
#   R1: 有 fy_income 且 H1 → 含「### TTM vs FY」、組成表 4 欄（FY、H1 本期、H1 上期、TTM）、2 個 bridge 標題
#   R2: ttm unavailable → 該小節只有一行且含 reason
#   R3: ttm is None（FY 帳本）→ 不含「TTM vs FY」
#   R4: 期間行顯示 basis、期間標籤、天數、assurance
# fixture：合成帳本／FyIncome 沿用 test_metrics_ttm_values.py（單一出處）
from tests.tw_equity.test_metrics_ttm_values import _fy as _ttm_fy, _ledger as _ttm_ledger  # noqa: E402


def _ttm_section(text):
    sec = text[text.index("## 附錄 E"):]
    return sec[sec.index("### TTM vs FY"):]


def test_appendix_e_ttm_ok(tmp_path):
    led = _ttm_ledger()
    led.assurance = "reviewed"
    text, raw = _run(tmp_path, _bundle(compute_metrics(led, _ttm_fy())))
    sec = text[text.index("## 附錄 E"):]
    assert "基準 H1" in sec and "115-01-01~115-06-30" in sec and "181／181" in sec and "reviewed" in sec  # R4
    t = _ttm_section(text)
    assert "| 科目 | FY | H1 本期 | H1 上期 | TTM |" in t
    assert "| revenue | 1,000 | 600 | 500 | 1,100 |" in t
    assert len(re.findall(r"^#### TTM .*（(?:operating_income|net_income)）：", t, flags=re.M)) == 2
    assert raw["bundle"]["metrics"]["ttm_vs_fy"]["status"] == "ok"


def test_appendix_e_ttm_unavailable_one_line(tmp_path):
    text, _ = _run(tmp_path, _bundle(compute_metrics(_ttm_ledger(), _ttm_fy(usable=False))))
    t = _ttm_section(text)
    body = [l for l in t.splitlines()[1:] if l.strip()]
    assert len(body) == 1 and "fy_income_unusable" in body[0]


def test_appendix_e_no_ttm_section_for_fy_ledger(tmp_path):
    text, _ = _run(tmp_path, _bundle(compute_metrics(_ttm_ledger(basis="FY"), _ttm_fy())))
    assert "TTM vs FY" not in text


# ── run 2026-10-09-tw-equity-fy-income-guard item 1.1：FY 損益表解析失敗警示。契約 row：
#   G3: bundle.fy_income_error 非 None → 附錄 E 的 TTM 小節含「⚠️ FY 損益表解析失敗：<錯誤>」、raw.json 記 fy_income_error
#   G4: [邊界] fy_income_error None → 附錄 E 無警示行


def test_appendix_e_shows_fy_income_error(tmp_path):
    b = _bundle(compute_metrics(_ttm_ledger(), None))
    b.fy_income_error = "ValueError: boom"
    text, raw = _run(tmp_path, b)
    t = _ttm_section(text)
    assert "⚠️ FY 損益表解析失敗：ValueError: boom" in t
    assert "fy_income_missing" in t
    assert raw["bundle"]["fy_income_error"] == "ValueError: boom"


def test_appendix_e_no_warning_without_error(tmp_path):
    text, raw = _run(tmp_path, _bundle(compute_metrics(_ttm_ledger(), None)))
    assert "FY 損益表解析失敗" not in text
    assert raw["bundle"]["fy_income_error"] is None
