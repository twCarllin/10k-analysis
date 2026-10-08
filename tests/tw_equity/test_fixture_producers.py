"""test_fixture_producers.py — fs／ar fixture producer 產物契約（item 1.2）。

契約 row：
  R1: fs JSON 頁碼集合＝17 頁、每頁 lines 非空
  R2: ar JSON 頁碼集合＝1A 既有頁∪{8,57,58,59,65}、每頁 lines 非空
  R3: from_json 載回兩份 → PdfDoc、page.number 對應原頁碼
  R4: [邊界] 來源 PDF 不存在 → 明確 raise
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from runtime.tw_equity import pdf_doc as _pdf_doc  # noqa: E402
from tests.fixtures.tw_equity import make_fs_fixture  # noqa: E402

_FIX = _REPO_ROOT / "tests" / "fixtures" / "tw_equity"
_FS_PAGES = {2, 3, 5, 6, 10, 11, 12, 14, 22, 29, 31, 46, 47, 51, 55, 64, 67}
_AR_1A_PAGES = {3, 4, 5, 6, 65, 66, 67, 76, 81, 82, 92, 93, 94, 95, 96, 97, 98, 99}
_AR_PAGES = _AR_1A_PAGES | {8, 57, 58, 59, 65}


def _load(name: str) -> _pdf_doc.PdfDoc:
    doc = _pdf_doc.from_json(json.loads((_FIX / name).read_text(encoding="utf-8")))
    assert isinstance(doc, _pdf_doc.PdfDoc)
    return doc


@pytest.mark.parametrize(
    "name,expected",
    [("fs_3653_pages.json", _FS_PAGES), ("ar_3653_pages.json", _AR_PAGES)],
)
def test_fixture_pages_and_lines(name: str, expected: set[int]) -> None:
    doc = _load(name)
    assert {p.number for p in doc.pages} == expected
    assert all(p.lines for p in doc.pages)


def test_fs_producer_missing_pdf_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        make_fs_fixture.produce(
            pdf_path=tmp_path / "nope.pdf", out_path=tmp_path / "out.json"
        )
    assert not (tmp_path / "out.json").exists()
