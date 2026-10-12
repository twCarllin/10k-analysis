"""
ocr_adapters.py — tw-equity OCR 共用 adapter（Mistral OCR、Azure DI 共用的設定讀取、例外與 HTTP helper）。

自已移除的徵信模組 adapters 原樣搬出（run 2026-10-12-remove-tw-credit）；
key 走 header、不出現在 URL；錯誤一律 raise AdapterError，訊息不含 endpoint/key。
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Callable

import requests

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = BASE_DIR / "config.json"

# DI API 版本
_DI_API_VERSION = "2024-11-30"


def _load_azure_config() -> dict:
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return cfg.get("azure", {})


class AdapterError(Exception):
    """
    Adapter 呼叫失敗（HTTP 錯誤/逾時/金鑰無效）。
    reason 不含 endpoint/key 片段。
    """
    pass


def _default_http_post(url: str, *, headers: dict, json_body: dict | None = None,
                        data: bytes | None = None, content_type: str | None = None,
                        timeout: int = 30) -> requests.Response:
    """預設 HTTP POST，封裝 requests，供 mock 替換。"""
    h = dict(headers)
    if content_type:
        h["Content-Type"] = content_type
    if json_body is not None:
        return requests.post(url, headers=h, json=json_body, timeout=timeout)
    return requests.post(url, headers=h, data=data, timeout=timeout)


def _default_http_get(url: str, *, headers: dict, timeout: int = 30) -> requests.Response:
    """預設 HTTP GET，封裝 requests，供 mock 替換。"""
    return requests.get(url, headers=headers, timeout=timeout)


class MistralOCRAdapter:
    """
    Mistral OCR fallback adapter。
    DI 判定為掃描頁時使用，**顯性**標記在 stage log 中。

    注入點：_http_post 供測試替換。
    """

    def __init__(self, *, _http_post: Callable | None = None) -> None:
        cfg = _load_azure_config()
        self._endpoint: str = cfg.get("mistral_ocr_endpoint", "").rstrip("/")
        self._key: str = cfg.get("mistral_ocr_key", "")
        self._model: str = cfg.get("mistral_ocr_model", "mistral-ocr-4-0")
        self._http_post = _http_post or _default_http_post

    def _headers(self) -> dict:
        # key 走 Authorization header，不出現在 URL
        return {
            "Authorization": f"Bearer {self._key}",
        }

    def extract_text(self, pdf_path: str) -> str:
        """
        對掃描 PDF 跑 Mistral OCR，回傳抽取的全文字串（頁以 \\n\\n 連接）。

        委派 extract_pages()；行為與歷史版本一致。
        """
        return "\n\n".join(self.extract_pages(pdf_path)).strip()

    def extract_pages(self, pdf_path: str) -> list[str]:
        """
        對掃描 PDF 跑 Mistral OCR，回傳逐頁 markdown list（保留頁界，順序同原 PDF）。
        顯性標記：logger.warning 告知 OCR fallback 被觸發。

        Returns:
            逐頁 OCR 文字 list（含空頁的空字串，由呼叫端決定過濾）。
        Raises:
            AdapterError: HTTP 錯誤/逾時（不靜默降級）。
        """
        logger.warning(
            "[OCR-FALLBACK] 偵測到掃描頁，觸發 Mistral OCR fallback（model=%s）",
            self._model,
        )

        pdf_bytes = Path(pdf_path).read_bytes()
        b64 = base64.b64encode(pdf_bytes).decode("ascii")

        # config 的 mistral_ocr_endpoint 已是完整路徑（Azure 託管路由
        # /providers/mistral/azure/ocr），直接使用；拼 /v1/ocr 會 404
        url = self._endpoint
        body = {
            "model": self._model,
            "document": {
                "type": "document_url",
                "document_url": f"data:application/pdf;base64,{b64}",
            },
        }

        try:
            resp = self._http_post(
                url,
                headers=self._headers(),
                json_body=body,
                content_type="application/json",
                timeout=120,
            )
        except requests.exceptions.Timeout:
            raise AdapterError("Mistral OCR 請求逾時（timeout）")
        except requests.exceptions.RequestException as exc:
            raise AdapterError(f"Mistral OCR 網路錯誤：{type(exc).__name__}")

        if resp.status_code != 200:
            raise AdapterError(
                f"Mistral OCR 回傳 HTTP {resp.status_code}（{resp.reason}）"
            )

        data = resp.json()
        # Mistral OCR 回傳格式：{"pages": [{"markdown": "..."}]}
        pages = data.get("pages", [])
        page_texts = [p.get("markdown", "") for p in pages]

        logger.info(
            "[OCR-FALLBACK] Mistral OCR 完成，%d 頁、共 %d 字元",
            len(page_texts), sum(len(t) for t in page_texts),
        )
        return page_texts
