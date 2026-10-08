"""test_ar_fixture.py — 驗證 make_ar_fixture.py 的契約行為。

契約 row（item 1.3）：
  R1: from_json 載回 → PdfDoc，page.number 與原頁碼一致
  R2: 執行 producer → 寫出 JSON，含所選各頁
  R3: [邊界] 來源 PDF 不存在 → 明確 raise（非靜默產空檔）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from runtime.tw_equity import pdf_doc as _pdf_doc  # noqa: E402
from tests.fixtures.tw_equity.make_ar_fixture import (  # noqa: E402
    _SELECTED_PAGES,
    extract_pages,
    produce,
)

_FIXTURE_JSON = _REPO_ROOT / "tests" / "fixtures" / "tw_equity" / "ar_3653_pages.json"


class TestFromJsonRoundtrip:
    """R1：from_json 載回、頁碼對應原頁碼。"""

    def test_loads_as_pdfdoc(self) -> None:
        data = json.loads(_FIXTURE_JSON.read_text(encoding="utf-8"))
        doc = _pdf_doc.from_json(data)
        assert isinstance(doc, _pdf_doc.PdfDoc)

    def test_page_numbers_match_selected(self) -> None:
        data = json.loads(_FIXTURE_JSON.read_text(encoding="utf-8"))
        doc = _pdf_doc.from_json(data)
        assert doc is not None
        loaded_numbers = [p.number for p in doc.pages]
        assert loaded_numbers == sorted(_SELECTED_PAGES)


class TestProducerOutput:
    """R2：produce() 寫出 JSON，含所選各頁；page.number 須等於所要求的頁碼。"""

    def test_produce_writes_json_with_correct_page_numbers(self, tmp_path: Path) -> None:
        out = tmp_path / "out.json"
        pdf_path = _REPO_ROOT / "tw_report" / "2025_3653_健策年報.pdf"
        if not pdf_path.exists():
            pytest.skip("來源 PDF 不在 CI 環境")
        produce(pdf_path=pdf_path, out_path=out, page_numbers=[3, 4])
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        doc = _pdf_doc.from_json(data)
        assert doc is not None
        # page.number 必須精確等於所要求的頁碼（off-by-one 會讓此斷言失敗）
        assert [p.number for p in doc.pages] == [3, 4]


class TestMissingPdf:
    """R3：來源 PDF 不存在 → FileNotFoundError。"""

    def test_raises_file_not_found(self, tmp_path: Path) -> None:
        ghost = tmp_path / "nonexistent.pdf"
        with pytest.raises(FileNotFoundError):
            extract_pages(ghost, [1])
