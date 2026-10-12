"""make_mistral_fixture.py — 以真實 Mistral OCR 對健策 2024 年報 p51、p79 取回應，存為 mistral_3653_2024_p51_p79.json。

執行方式（付費外部 API；使用者 2026-10-08 授權單次，失敗不重試）：
    ./.venv/bin/python tests/fixtures/tw_equity/make_mistral_fixture.py

輸出：tests/fixtures/tw_equity/mistral_3653_2024_p51_p79.json（進版控；測試實際載入的 single source）
形狀：{"_meta": {...}, "pages": {"51": <markdown>, "79": <markdown>}}
來源：tw_report/3653_2024年報.pdf（不進版控）。寫檔前檢查不含 key 值與 endpoint 網域，含則中止。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

from runtime.tw_equity.ocr_adapters import _load_azure_config  # noqa: E402
from runtime.tw_equity.ocr import MistralPageOcr  # noqa: E402

_PDF_PATH = _REPO_ROOT / "tw_report" / "3653_2024年報.pdf"
_OUT_PATH = Path(__file__).resolve().parent / "mistral_3653_2024_p51_p79.json"
_PAGES = [51, 79]


def produce(out_path: Path = _OUT_PATH) -> None:
    cfg = _load_azure_config()
    mds = MistralPageOcr().fetch(_PDF_PATH, _PAGES)
    doc = {
        "_meta": {"source": "真實 Mistral OCR，tw_report/3653_2024年報.pdf pages=51,79",
                  "synthetic": False},
        "pages": {str(n): md for n, md in mds.items()},
    }
    text = json.dumps(doc, ensure_ascii=False, indent=1)
    host = cfg["mistral_ocr_endpoint"].split("//")[-1].split("/")[0]
    for secret in (cfg["mistral_ocr_key"], host):
        assert secret and secret not in text, "fixture 含敏感字串，中止"
    out_path.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    produce()
