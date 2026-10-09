"""batch_summary.py 金控節渲染測試（item 5.3；Spec §8.2）。"""

from __future__ import annotations

import hashlib
import json

from runtime.tw_equity.batch_summary import build_summary, render_html, render_md, write_summary
from tests.tw_equity.test_batch_summary_fh import fh_rec, ind_rec

# 無 fh 時 md／html 的改動前快照（sha256；以 5.2／5.3 前的 batch_summary 對下列輸入產生）
_IND = [ind_rec("1111"), ind_rec("2222")]
_MD_SHA = "cce1517b381e7a4538851c9b62a2359315e413ca1d35c76fe9f7063b78af6667"
_HTML_SHA = "b39eba0658beb82c1ddde226a7c366b832171687cdc045a8dd1ccb290bc14442"


def _sha(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def test_md_fh_section():
    md = render_md(build_summary([ind_rec(), fh_rec("2881", ifrs17=True), fh_rec("2887", car=None)]))
    assert "## 金控" in md
    assert "未年化" in md and "IFRS 4" in md
    row = next(x for x in md.splitlines() if x.startswith("| 2881 "))
    assert "139.13（114-06-30）" in row and row.endswith("| 斷層 |")
    assert "2881 金控2881：FY 為 IFRS 4、H1 為 IFRS 17" in md
    assert "2887 金控2887：FY 為 IFRS 4" not in md


def test_md_none_cell_is_unavailable_and_mark_stays():
    md = render_md(build_summary([fh_rec("2887", car=None, ifrs17=True)]))
    row = next(x for x in md.splitlines() if x.startswith("| 2887 "))
    assert "不可得" in row and row.endswith("| 斷層 |")
    assert "None" not in row and "nan" not in row


def test_md_parent_only_label():
    md = render_md(build_summary([fh_rec(scope="parent_only")]))
    assert "150（歸母）" in md


def test_html_fh_section():
    html = render_html(build_summary([ind_rec(), fh_rec(ifrs17=True)]))
    assert 'id="fh-section"' in html and 'id="fh-body"' in html and "未年化" in html
    assert "FY 為 IFRS 4、H1 為 IFRS 17" in html
    assert "<script src=" not in html and "<link" not in html and "__DATA__" not in html


def test_no_fh_output_unchanged_from_snapshot():
    s = build_summary(_IND)
    assert _sha(render_md(s)) == _MD_SHA
    assert _sha(render_html(s)) == _HTML_SHA
    assert "金控" not in render_md(s) and "fh-section" not in render_html(s)


def test_write_summary_file_set_unchanged(tmp_path):
    write_summary(build_summary([ind_rec(), fh_rec()]), tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["summary.html", "summary.json", "summary.md"]


def test_md_fh_ratio_columns_two_decimals():
    rec = fh_rec()
    rec["metrics"]["npl_ratio"] = {"current": 0.11}
    rec2 = fh_rec("2882")
    rec2["metrics"]["npl_ratio"] = {"current": 0.14}
    md = render_md(build_summary([rec, rec2]))
    assert "0.11" in next(x for x in md.splitlines() if x.startswith("| 2881 "))
    assert "0.14" in next(x for x in md.splitlines() if x.startswith("| 2882 "))


def _embedded(html: str) -> dict:
    start = html.index("const S = ") + len("const S = ")
    return json.JSONDecoder().raw_decode(html[start:])[0]


def test_html_group_car_none_with_ifrs17_flag_in_embedded_data():
    on = _embedded(render_html(build_summary([fh_rec("2887", car=None, ifrs17=True)])))["fh_ranking"][0]
    off = _embedded(render_html(build_summary([fh_rec("2887", car=None, ifrs17=False)])))["fh_ranking"][0]
    assert on["values"]["group_car"] is None and off["values"]["group_car"] is None
    assert on["ifrs17_break"] is True and off["ifrs17_break"] is False
