"""test_doc_anchor.py — doc_anchor 模組單元測試。

測試範圍：
- 真實 3653 fixture（ar_3653_pages.json）：required key 全找到、
  ar_mdna 起頁 92、ar_special 起頁 99、ar_production_sales → None。
- 目錄頁合成案例：TOC 頁不被當起頁，真正起頁在後。
- required key 全缺 → AnchorError，訊息含缺失的 key 名稱。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.tw_equity.pdf_doc import Page, PdfDoc, from_json
from runtime.tw_equity.doc_anchor import (
    ANNUAL_REPORT_ANCHORS,
    FS_ANCHORS,
    PARENT_FS_ANCHORS,
    AnchorError,
    PageRange,
    find_annual_report_sections,
    find_sections,
)

# ── fixture 路徑 ─────────────────────────────────────────────────────────────

_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "tw_equity"
_AR_3653_JSON = _FIXTURE_DIR / "ar_3653_pages.json"

_AR_ORDER = list(ANNUAL_REPORT_ANCHORS)
_FS_ORDER = list(FS_ANCHORS)
_PS_ORDER = list(PARENT_FS_ANCHORS)

_AR_REQUIRED = {
    "ar_letter", "ar_business", "ar_market", "ar_customers",
    "ar_mdna", "ar_fin_position", "ar_fin_performance",
}
_FS_REQUIRED = {"fs_bs", "fs_is", "fs_note_expense_nature"}
_PS_REQUIRED = {"ps_is", "ps_cogs_detail"}


def _load_3653() -> PdfDoc:
    data = json.loads(_AR_3653_JSON.read_text(encoding="utf-8"))
    doc = from_json(data)
    assert doc is not None, "fixture 格式不符（版本不相容）"
    return doc


def _make_doc(pages: list[Page]) -> PdfDoc:
    """由 Page list 建立 PdfDoc（用於合成測試）。"""
    return PdfDoc(path=Path("synthetic.pdf"), pages=pages)


# ── 真實 3653 fixture 測試 ───────────────────────────────────────────────────


class TestFindSections3653:
    """使用真實健策 3653 年報 fixture 的整合測試。"""

    @pytest.fixture(scope="class")
    def sections(self):
        doc = _load_3653()
        return find_sections(
            doc,
            ANNUAL_REPORT_ANCHORS,
            required=_AR_REQUIRED,
            order=_AR_ORDER,
        )

    def test_required_keys_all_found(self, sections):
        """required key 全部找到，不為 None。"""
        for key in _AR_REQUIRED:
            assert sections[key] is not None, f"required key 未找到：{key}"

    def test_ar_mdna_start_page_92(self, sections):
        """ar_mdna 起頁 = 92（契約表 §2.3 實測）。"""
        assert sections["ar_mdna"].start == 92

    def test_ar_special_start_page_99(self, sections):
        """ar_special 起頁 = 99（契約表 §2.3 實測）。"""
        assert sections["ar_special"].start == 99

    def test_ar_production_sales_is_none(self, sections):
        """ar_production_sales 找不到 → None（年報無生產量值表）。"""
        assert sections["ar_production_sales"] is None

    def test_page_range_is_dataclass(self, sections):
        """找到的 key 值為 PageRange dataclass（有 start / end）。"""
        pr = sections["ar_mdna"]
        assert isinstance(pr, PageRange)
        assert isinstance(pr.start, int)
        assert isinstance(pr.end, int)

    def test_end_ge_start(self, sections):
        """所有找到的 section，end >= start。"""
        for key, pr in sections.items():
            if pr is not None:  # testlint: allow — required key 全找到已由 test_required_keys_all_found 斷言，迴圈非空轉
                assert pr.end >= pr.start, f"{key}: end({pr.end}) < start({pr.start})"

    def test_p3_p4_not_start_pages(self, sections):
        """p3/p4 不被當起頁（目錄頁排除）。"""
        for key, pr in sections.items():
            if pr is not None:  # testlint: allow — 同上
                assert pr.start > 4, (
                    f"key={key} 起頁 {pr.start} ≤ 4，目錄頁未正確排除"
                )


# ── 目錄頁合成案例 ────────────────────────────────────────────────────────────


class TestTocExclusion:
    """合成文件：目錄頁命中多 key → 不被當起頁，真正起頁在後。"""

    def _make_toc_doc(self) -> PdfDoc:
        """
        p1：full text 含 ar_letter、ar_business、ar_market（≥3 key）→ TOC 頁。
              first 300 chars 也含 ar_letter 關鍵字。
        p2：first 300 chars 只含 ar_letter 關鍵字 → 真正起頁。
        """
        p1_text = (
            "目錄\n"
            "致股東報告書 1\n"
            "一、業務內容 5\n"
            "二、市場及產銷概況 20\n"
        )
        p2_text = "致股東報告書\n各位股東女士、先生，感謝支持。"
        pages = [
            Page(number=1, text=p1_text, tables=[]),
            Page(number=2, text=p2_text, tables=[]),
        ]
        return _make_doc(pages)

    def test_toc_page_not_chosen_as_start(self):
        """TOC 頁（p1）命中多 key → ar_letter 起頁為 p2，不為 p1。"""
        doc = self._make_toc_doc()
        anchors = {
            "ar_letter":  ["致股東報告書"],
            "ar_business": ["一、業務內容"],
            "ar_market":   ["二、市場及產銷概況"],
        }
        result = find_sections(
            doc,
            anchors,
            required={"ar_letter"},
            order=["ar_letter", "ar_business", "ar_market"],
        )
        assert result["ar_letter"] is not None
        assert result["ar_letter"].start == 2  # 非目錄頁

    def test_keyword_on_toc_page_continues_to_real_start(self):
        """關鍵字命中於目錄頁 → 演算法繼續往後找真正起頁（契約表組合測試）。"""
        doc = self._make_toc_doc()
        anchors = {
            "ar_letter":  ["致股東報告書"],
            "ar_business": ["一、業務內容"],
            "ar_market":   ["二、市場及產銷概況"],
        }
        result = find_sections(
            doc,
            anchors,
            required={"ar_letter"},
            order=["ar_letter", "ar_business", "ar_market"],
        )
        # ar_letter 在 p1（TOC）與 p2 都有關鍵字，應選 p2
        assert result["ar_letter"].start > 1


# ── AnchorError ────────────────────────────────────────────────────────────────


class TestAnchorError:
    """required key 找不到 → AnchorError，訊息列出缺少的 key。"""

    def test_required_key_missing_raises_anchor_error(self):
        """doc 無任何關鍵字 → AnchorError（required key 全缺）。"""
        doc = _make_doc([
            Page(number=1, text="這頁沒有任何錨點關鍵字。", tables=[]),
        ])
        anchors = {"ar_letter": ["致股東報告書"], "ar_business": ["一、業務內容"]}
        with pytest.raises(AnchorError):
            find_sections(
                doc,
                anchors,
                required={"ar_letter"},
                order=["ar_letter", "ar_business"],
            )

    def test_anchor_error_message_contains_missing_key(self):
        """AnchorError 訊息含缺失的 key 名稱（契約表邊界測試）。"""
        doc = _make_doc([
            Page(number=1, text="無關鍵字頁面", tables=[]),
        ])
        anchors = {
            "ar_letter": ["致股東報告書"],
            "ar_business": ["一、業務內容"],
        }
        with pytest.raises(AnchorError) as exc_info:
            find_sections(
                doc,
                anchors,
                required={"ar_letter", "ar_business"},
                order=["ar_letter", "ar_business"],
            )
        msg = str(exc_info.value)
        assert "ar_letter" in msg or "ar_business" in msg

    def test_non_required_key_missing_returns_none(self):
        """非 required 的 key 找不到 → 值為 None，不 raise。"""
        doc = _make_doc([
            Page(number=1, text="致股東報告書\n正文內容。", tables=[]),
        ])
        anchors = {
            "ar_letter":  ["致股東報告書"],
            "ar_special": ["特別記載事項"],
        }
        result = find_sections(
            doc,
            anchors,
            required={"ar_letter"},
            order=["ar_letter", "ar_special"],
        )
        assert result["ar_letter"] is not None
        assert result["ar_special"] is None


# ── 錨點字典存在性 ─────────────────────────────────────────────────────────────


class TestAnchorDicts:
    """確認三個錨點字典匯出且包含必要 key。"""

    def test_annual_report_anchors_has_required_keys(self):
        """ANNUAL_REPORT_ANCHORS 包含所有 required key。"""
        for key in _AR_REQUIRED:
            assert key in ANNUAL_REPORT_ANCHORS, f"missing key: {key}"

    def test_annual_report_anchors_has_ar_production_sales(self):
        """ANNUAL_REPORT_ANCHORS 包含選配 key ar_production_sales。"""
        assert "ar_production_sales" in ANNUAL_REPORT_ANCHORS

    def test_fs_anchors_has_required_keys(self):
        """FS_ANCHORS 包含所有 required key。"""
        for key in _FS_REQUIRED:
            assert key in FS_ANCHORS, f"missing key: {key}"

    def test_parent_fs_anchors_has_required_keys(self):
        """PARENT_FS_ANCHORS 包含所有 required key。"""
        for key in _PS_REQUIRED:
            assert key in PARENT_FS_ANCHORS, f"missing key: {key}"


# ── run 2026-10-08-tw-equity-rotated-pages：ar_letter 以治理章終止、ar_risk 不誤中治理頁 ──


def _page(n: int, text: str) -> Page:
    return Page(number=n, text=text, tables=[], lines=[])


class TestGovernanceTerminatesLetter:
    def test_letter_ends_before_governance(self) -> None:
        doc = _make_doc([
            _page(1, "壹、致股東報告書 各位股東..."),
            _page(2, "貳、公司治理報告 一、董事..."),
            _page(3, "一、業務內容 ..."),
        ])
        r = find_annual_report_sections(doc, required={"ar_letter"})
        assert r["ar_letter"] == PageRange(1, 1)
        assert r["ar_governance"] == PageRange(2, 2)
        assert r["ar_business"] == PageRange(3, 3)

    def test_letter_without_governance_keeps_old_behavior(self) -> None:
        doc = _make_doc([
            _page(1, "壹、致股東報告書 各位股東..."),
            _page(2, "（續）"),
            _page(3, "一、業務內容 ..."),
        ])
        r = find_annual_report_sections(doc, required={"ar_letter"})
        assert r["ar_letter"] == PageRange(1, 2)
        assert r["ar_governance"] is None

    def test_risk_start_not_before_mdna(self) -> None:
        """治理頁交叉引用「風險事項」→ ar_risk 不得錨在 ar_mdna 之前，改往後找。"""
        doc = _make_doc([
            _page(1, "壹、致股東報告書"),
            _page(2, "貳、公司治理報告 評估項目 運作情形 ... 請詳閱風險事項 ..."),
            _page(3, "伍、財務狀況及財務績效之檢討分析與風險事項 ..."),  # 只命中 2 key，不被判為目錄頁
            _page(4, "陸、特別記載事項"),
        ])
        r = find_annual_report_sections(doc, required=set())
        assert r["ar_mdna"] == PageRange(3, 3)
        assert r["ar_risk"] == PageRange(3, 3)

    def test_risk_dropped_when_only_hit_is_before_mdna(self) -> None:
        doc = _make_doc([
            _page(1, "貳、公司治理報告 ... 風險事項 ..."),
            _page(2, "伍、財務狀況及財務績效之檢討分析 ..."),
            _page(3, "陸、特別記載事項"),
        ])
        r = find_annual_report_sections(doc, required=set())
        assert r["ar_mdna"] == PageRange(2, 2)
        assert r["ar_risk"] is None
