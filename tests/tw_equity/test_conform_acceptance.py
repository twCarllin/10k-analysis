"""70 家驗收工具與 OCR 掃描頁判定（run 2026-10-10-tw-equity-70-conform，Task 2：item 2.3）。

契約 row（task/2026-10-10-tw-equity-70-conform.md，2.3 DoD）：
  ① `ocr_scanned=False` 時判定與修改前相同
  ② True 時 image_cover≥0.9 且字數≥50 的頁送 OCR（mock OCR）
  ⑤ 新增 70 家驗收（工具＋測試；例外清單只含 Spec §5 Q3 兩筆）；清單依 group 產生（工業 22 項、金控／銀行 18 項）
  ＋ Spec §1 驗收方式：OCR 只讀快取，快取未命中改不做 OCR 載入
OCR 與 PDF 載入是系統邊界：OCR 以假函式注入（pdf_doc 的公開參數），PDF 檔案載入以 monkeypatch 取代。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.tw_equity import fs_acceptance, pdf_doc  # noqa: E402
from runtime.tw_equity.pdf_doc import Page, PdfDoc  # noqa: E402
from runtime.tw_equity.statements import CrossCheck  # noqa: E402

# ── 2.3 DoD ①②：apply_ocr_policy／load_pdf 的 ocr_scanned ──────────────────────

_JUNK = "垃" * 120  # 掃描頁的低品質文字層：≥50 字


def _doc() -> PdfDoc:
    return PdfDoc(path=Path("x.pdf"), pages=[
        Page(number=1, text="正常文字頁" * 30, tables=[], lines=["正常"], image_cover=0.0),
        Page(number=2, text="", tables=[], lines=[], image_cover=1.0),                 # 純圖片頁（舊規則即送）
        Page(number=3, text=_JUNK, tables=[], lines=[_JUNK], image_cover=1.0),          # 掃描頁＋垃圾文字層
        Page(number=4, text=_JUNK, tables=[], lines=[_JUNK], image_cover=0.5),          # 圖片覆蓋不足
        Page(number=5, text=_JUNK, tables=[], lines=[_JUNK], image_cover=0.9),          # 邊界：剛好 0.9
    ])


class _FakeOcr:
    def __init__(self):
        self.calls: list[list[int]] = []

    def __call__(self, path, pages):
        self.calls.append(list(pages))
        return {n: Page(number=n, text=f"OCR{n}", tables=[], lines=[f"OCR{n}"]) for n in pages}


def test_default_policy_only_sends_low_text_image_pages() -> None:
    """DoD ①：預設（ocr_scanned=False）只有字數 <50 的圖片頁送 OCR，掃描垃圾頁不送——與修改前相同。"""
    ocr = _FakeOcr()
    out = pdf_doc.apply_ocr_policy(_doc(), ocr)
    assert ocr.calls == [[2]]
    assert out.image_pages == [2] and out.ocr_pages == [2]
    assert out.pages[2].text == _JUNK  # 第 3 頁原樣保留
    ocr2 = _FakeOcr()
    out2 = pdf_doc.apply_ocr_policy(_doc(), ocr2, ocr_scanned=False)
    assert ocr2.calls == [[2]] and out2.image_pages == out.image_pages


def test_ocr_scanned_sends_all_pages_with_image_cover_ge_0_9() -> None:
    """DoD ②：ocr_scanned=True → image_cover≥0.9 的頁不管字數都送 OCR；覆蓋率 0.5 的頁與正常頁不送。"""
    ocr = _FakeOcr()
    out = pdf_doc.apply_ocr_policy(_doc(), ocr, ocr_scanned=True)
    assert ocr.calls == [[2, 3, 5]]
    assert out.ocr_pages == [2, 3, 5] and out.image_pages == [2, 3, 5]
    assert out.pages[2].text == "OCR3" and out.pages[0].text.startswith("正常文字頁") and out.pages[3].text == _JUNK


def test_ocr_scanned_without_ocr_fn_leaves_pages_as_is() -> None:
    out = pdf_doc.apply_ocr_policy(_doc(), None, ocr_scanned=True)
    assert out.ocr_pages == [] and out.pages[2].text == _JUNK


class _FakePdf:
    """pdfplumber／fitz 的最小替身（系統邊界）：每頁 extract_text／extract_tables 與 get_text('words')。"""

    class _P:
        def __init__(self, text):
            self._t = text

        def extract_text(self):
            return self._t

        def extract_tables(self):
            return []

    def __init__(self, texts):
        self.pages = [self._P(t) for t in texts]


def test_load_pdf_cache_name_has_policy_suffix_and_old_cache_untouched(tmp_path, monkeypatch) -> None:
    """快取檔名加政策後綴：ocr_scanned=True 寫 .ocr-scan.json，不動舊 .ocr.json；兩者互不命中。"""
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-fake")
    stem = pdf_doc._sha256_prefix(pdf)
    cache = tmp_path / "cache"
    cache.mkdir()
    legacy = cache / f"{stem}.ocr.json"
    legacy.write_text(json.dumps(pdf_doc.to_json(_doc())), encoding="utf-8")
    before = legacy.read_bytes()
    monkeypatch.setattr(pdf_doc, "_build_from_pdfplumber", lambda path, lo=None: _doc())
    monkeypatch.setitem(sys.modules, "pdfplumber", object())
    ocr = _FakeOcr()
    got = pdf_doc.load_pdf(pdf, cache_dir=cache, ocr=ocr, ocr_scanned=True)  # 舊快取有多出的掃描頁 → 不沿用，重打 OCR
    assert ocr.calls == [[2, 3, 5]] and got.ocr_pages == [2, 3, 5]
    assert (cache / f"{stem}.ocr-scan.json").exists() and legacy.read_bytes() == before
    ocr2 = _FakeOcr()
    again = pdf_doc.load_pdf(pdf, cache_dir=cache, ocr=ocr2, ocr_scanned=True)  # 第二次讀新快取
    assert ocr2.calls == [] and again.ocr_pages == [2, 3, 5]
    ocr3 = _FakeOcr()
    old = pdf_doc.load_pdf(pdf, cache_dir=cache, ocr=ocr3)  # 預設政策仍讀舊快取
    assert ocr3.calls == [] and old.ocr_pages == [] and old.pages[2].text == _JUNK  # 舊快取（fixture 未經 OCR）內容原樣回傳


def test_legacy_cache_reused_when_policy_would_add_no_pages(tmp_path, monkeypatch) -> None:
    """舊快取已涵蓋所有掃描頁（無多出頁）→ ocr_scanned=True 判定相同、沿用舊快取、不重打 OCR。"""
    doc = PdfDoc(path=Path("x.pdf"), pages=[Page(number=1, text="OCR1", tables=[], lines=["OCR1"], image_cover=1.0)],
                 ocr_pages=[1], image_pages=[1])
    pdf = tmp_path / "b.pdf"
    pdf.write_bytes(b"%PDF-fake2")
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / f"{pdf_doc._sha256_prefix(pdf)}.ocr.json").write_text(json.dumps(pdf_doc.to_json(doc)), encoding="utf-8")
    ocr = _FakeOcr()
    got = pdf_doc.load_pdf(pdf, cache_dir=cache, ocr=ocr, ocr_scanned=True)
    assert ocr.calls == [] and got.ocr_pages == [1] and got.pages[0].text == "OCR1"


# ── 2.3 DoD ⑤：驗收清單、例外判定 ──────────────────────────────────────────

def _write_inputs(base: Path, ticker: str, group: str | None) -> None:
    (base / "tw_report").mkdir(exist_ok=True)
    for n in (f"{ticker}_ar.pdf", f"{ticker}_fs.pdf"):
        (base / "tw_report" / n).write_bytes(b"%PDF")
    d = {"ticker": ticker, "company_name": f"公司{ticker}", "fiscal_year": 2025,
         "annual_report_path": f"tw_report/{ticker}_ar.pdf", "consolidated_fs_path": f"tw_report/{ticker}_fs.pdf"}
    if group is not None:
        d["group"] = group
    (base / "tw_equity_inputs").mkdir(exist_ok=True)
    (base / "tw_equity_inputs" / f"{ticker}.json").write_text(json.dumps(d), encoding="utf-8")


def test_acceptance_tickers_follow_inputs_group(tmp_path) -> None:
    for t, g in (("2330", None), ("2801", "bank"), ("2880", "fh"), ("1301", "petrochemical")):
        _write_inputs(tmp_path, t, g)
    assert fs_acceptance.acceptance_tickers(tmp_path) == [
        ("1301", "petrochemical"), ("2330", None), ("2801", "bank"), ("2880", "fh")]


def _checks(n: int, bad: dict[str, bool | None] | None = None) -> list[CrossCheck]:
    bad = bad or {}
    out = []
    for i in range(n):
        name, period = f"chk{i // 2}", ("current", "prior")[i % 2]
        out.append(CrossCheck(name=name, period=period, lhs=1.0, rhs=1.0,
                              passed=bad.get(f"{name}/{period}", True)))
    return out


def test_expected_check_counts_by_group() -> None:
    ok = fs_acceptance.evaluate_checks
    assert ok("1301", "petrochemical", _checks(22))["conform"] is True
    assert ok("1301", None, _checks(22))["conform"] is True
    assert ok("1301", None, _checks(18))["conform"] is False  # 工業須 22 項
    for g in ("fh", "bank"):
        assert ok("2880", g, _checks(18))["conform"] is True
        assert ok("2880", g, _checks(22))["conform"] is False  # 金控／銀行須 18 項


def test_exception_list_is_exactly_the_two_q3_entries() -> None:
    assert fs_acceptance.ACCEPTANCE_EXCEPTIONS == {("2449", "is_net_income/prior"), ("2890", "is_net_income/current")}


def test_exception_applies_only_to_that_ticker_and_check_key() -> None:
    ev = fs_acceptance.evaluate_checks
    r = ev("2449", None, _checks(22, {"chk0/prior": False}))
    assert r["conform"] is False  # 鍵不同（chk0）不算例外
    cs = _checks(22)
    cs[0] = CrossCheck(name="is_net_income", period="prior", lhs=1.0, rhs=2.0, passed=False)
    r = ev("2449", None, cs)
    assert r["conform"] is True and r["excepted"] == ["is_net_income/prior"] and r["not_passed"] == []
    assert ev("2330", None, cs)["conform"] is False                  # 他家同鍵不豁免
    cs2 = [CrossCheck(name="is_net_income", period="current", lhs=1.0, rhs=2.0, passed=False)] + _checks(21)
    assert ev("2449", None, cs2)["conform"] is False                  # 同家不同 period 不豁免


def test_exception_does_not_excuse_other_failures_or_none() -> None:
    ev = fs_acceptance.evaluate_checks
    cs = _checks(18, {"chk1/current": None})
    cs[0] = CrossCheck(name="is_net_income", period="current", lhs=1.0, rhs=2.0, passed=False)
    r = ev("2890", "fh", cs)
    assert r["excepted"] == ["is_net_income/current"] and r["not_passed"] == ["chk1/current"] and r["conform"] is False


# ── 快取未命中：退回不做 OCR 載入 ─────────────────────────────────────────

def _fs_doc() -> PdfDoc:
    return PdfDoc(path=Path("x.pdf"), pages=[Page(number=1, text="", tables=[], lines=[])])


def test_cache_miss_falls_back_to_plain_load_without_api(tmp_path, monkeypatch) -> None:
    _write_inputs(tmp_path, "9999", None)
    calls: list[dict] = []

    def fake_load(path, **kw):
        calls.append(kw)
        if "ocr" in kw:
            kw["ocr"](path, [1])  # 快取未命中 → 只讀快取的 OCR 函式被呼叫並拋出
        return _fs_doc()

    monkeypatch.setattr(fs_acceptance.pdf_doc, "load_pdf", fake_load)
    rec = fs_acceptance.check_company("9999", None, tmp_path)
    assert len(calls) == 2
    assert calls[0]["ocr"] is fs_acceptance._cache_only_ocr and calls[0]["ocr_scanned"] is True
    assert "ocr" not in calls[1]                       # 退回：不帶 OCR（不打 API）
    assert rec["error"] == "no_statements"             # 退回後確實走到抽取（合成頁無三表）
    with pytest.raises(fs_acceptance.OcrCacheMiss):
        fs_acceptance._cache_only_ocr(Path("x.pdf"), [1])


def test_cache_hit_does_not_fall_back(tmp_path, monkeypatch) -> None:
    _write_inputs(tmp_path, "9998", "bank")
    calls: list[dict] = []

    def fake_load(path, **kw):
        calls.append(kw)
        return _fs_doc()

    monkeypatch.setattr(fs_acceptance.pdf_doc, "load_pdf", fake_load)
    rec = fs_acceptance.check_company("9998", "bank", tmp_path)
    assert len(calls) == 1 and calls[0]["ocr"] is fs_acceptance._cache_only_ocr
    assert rec["expected"] == 18 and rec["ticker"] == "9998"


def test_main_all70_prints_summary_line(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(fs_acceptance, "acceptance_tickers", lambda base: [("1111", None), ("2801", "bank")])
    monkeypatch.setattr(fs_acceptance, "check_company", lambda t, g, base: (
        {"ticker": t, "group": g, "expected": 22, "total": 22, "passed": 22, "excepted": [], "not_passed": [],
         "conform": True} if t == "1111" else {"ticker": t, "group": g, "expected": 18, "error": "no_statements"}))
    out = tmp_path / "r.json"
    assert fs_acceptance.main(["--all70", "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert "1111 [None]: OK 22/22" in text and "2801 [bank]: ERROR no_statements" in text
    assert text.strip().splitlines()[-1] == "SUMMARY conform=1/2 known_limitations=0 exceptions=0"
    assert len(json.loads(out.read_text(encoding="utf-8"))) == 2
