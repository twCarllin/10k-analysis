"""Azure DI 逐頁 OCR adapter（Spec 1B-2 §2.3）。

key 只走 header；錯誤訊息不含 endpoint／key。
"""
from __future__ import annotations

import base64
import os
import re
import tempfile
import time
from pathlib import Path

import fitz

from runtime.tw_credit.adapters import (
    AdapterError,
    MistralOCRAdapter,
    _DI_API_VERSION,
    _default_http_get,
    _default_http_post,
    _load_azure_config,
)
from runtime.tw_equity.pdf_doc import Page

_POLL_INTERVAL = 2
_POLL_MAX_WAIT = 180


class DiPageOcr:
    def __init__(self, *, _http_post=None, _http_get=None, _sleep=time.sleep) -> None:
        cfg = _load_azure_config()
        endpoint = (cfg.get("di_endpoint") or "").rstrip("/")
        key = cfg.get("di_key") or ""
        if not endpoint or not key:
            raise AdapterError("Azure DI 設定缺漏")
        self._endpoint = endpoint
        self._key = key
        self._http_post = _http_post or _default_http_post
        self._http_get = _http_get or _default_http_get
        self._sleep = _sleep

    def _headers(self) -> dict:
        return {"Ocp-Apim-Subscription-Key": self._key}

    def fetch(self, path: Path, pages: list[int]) -> dict:
        """送 DI，回傳原始 analyzeResult dict。"""
        b64 = base64.b64encode(Path(path).read_bytes()).decode("ascii")
        page_list = ",".join(str(p) for p in pages)
        url = (
            f"{self._endpoint}/documentintelligence/documentModels/"
            f"prebuilt-layout:analyze?api-version={_DI_API_VERSION}&pages={page_list}"
        )
        try:
            resp = self._http_post(
                url,
                headers=self._headers(),
                json_body={"base64Source": b64},
                content_type="application/json",
                timeout=60,
            )
        except Exception as exc:
            raise AdapterError(f"Azure DI 請求失敗：{type(exc).__name__}")

        if resp.status_code == 200:
            return resp.json().get("analyzeResult", resp.json())
        if resp.status_code == 202:
            op_url = resp.headers.get("Operation-Location", "")
            if not op_url:
                raise AdapterError("Azure DI 202 回應缺少 Operation-Location header")
            return self._poll(op_url)
        raise AdapterError(f"Azure DI 回傳 HTTP {resp.status_code}")

    def _poll(self, op_url: str) -> dict:
        waited = 0
        while waited < _POLL_MAX_WAIT:
            self._sleep(_POLL_INTERVAL)
            waited += _POLL_INTERVAL
            try:
                resp = self._http_get(op_url, headers=self._headers(), timeout=30)
            except Exception as exc:
                raise AdapterError(f"Azure DI 輪詢失敗：{type(exc).__name__}")
            if resp.status_code != 200:
                raise AdapterError(f"Azure DI 輪詢回傳 HTTP {resp.status_code}")
            body = resp.json()
            status = body.get("status", "")
            if status == "succeeded":
                return body.get("analyzeResult", {})
            if status == "failed":
                raise AdapterError("Azure DI 分析回傳 failed status")
        raise AdapterError(f"Azure DI 輪詢超過 {_POLL_MAX_WAIT} 秒仍未完成")

    def __call__(self, path: Path, pages: list[int]) -> dict[int, Page]:
        return _convert(self.fetch(path, pages))


def _convert(result: dict) -> dict[int, Page]:
    tables_by_page: dict[int, list] = {}
    for t in result.get("tables", []):
        regions = t.get("boundingRegions") or []
        if not regions:
            continue
        grid = [[None] * t["columnCount"] for _ in range(t["rowCount"])]
        for c in t.get("cells", []):
            grid[c["rowIndex"]][c["columnIndex"]] = c.get("content", "")
        tables_by_page.setdefault(regions[0]["pageNumber"], []).append(grid)

    out: dict[int, Page] = {}
    for p in result.get("pages", []):
        n = p["pageNumber"]
        lines = [s for s in ((ln.get("content") or "").strip() for ln in p.get("lines", [])) if s]
        out[n] = Page(number=n, text="\n".join(lines), tables=tables_by_page.get(n, []), lines=lines)
    return out


class MistralPageOcr:
    def __init__(self, *, _adapter=None) -> None:
        self._adapter = _adapter or MistralOCRAdapter()

    def fetch(self, path: Path, pages: list[int]) -> dict[int, str]:
        """抽指定頁成暫存 PDF → Mistral OCR → 頁碼 → 原始 markdown。"""
        src = fitz.open(str(path))
        dst = fitz.open()
        try:
            for n in pages:
                dst.insert_pdf(src, from_page=n - 1, to_page=n - 1)
            fd, tmp = tempfile.mkstemp(suffix=".pdf")
            os.close(fd)
            try:
                dst.save(tmp)
                mds = self._adapter.extract_pages(tmp)
            finally:
                os.unlink(tmp)
        finally:
            dst.close()
            src.close()
        if len(mds) != len(pages):
            raise AdapterError(f"Mistral OCR 回傳頁數 {len(mds)} 與請求頁數 {len(pages)} 不符")
        return dict(zip(pages, mds))

    def __call__(self, path: Path, pages: list[int]) -> dict[int, Page]:
        return {n: markdown_to_page(n, md) for n, md in self.fetch(path, pages).items()}


_SEP_RE = re.compile(r"^\|?\s*:?-{3,}")


def _strip_marks(line: str) -> str:
    line = re.sub(r"^(?:(?:#{1,6}|>|[-*])\s+)+", "", line.strip())
    return line.replace("**", "").strip()


def markdown_to_page(number: int, markdown: str) -> Page:
    lines: list[str] = []
    tables: list[list[list[str | None]]] = []
    block: list[list[str | None]] | None = None
    for raw in (markdown or "").splitlines():
        s = raw.strip()
        if s.startswith("|"):
            if block is None:
                block = []
                tables.append(block)
            if _SEP_RE.match(s):
                continue
            body = s[1:]
            if body.endswith("|"):
                body = body[:-1]
            cells = [c.strip().replace("**", "").strip() or None for c in body.split("|")]
            block.append(cells)
            joined = " ".join(c for c in cells if c)
            if joined:
                lines.append(joined)
            continue
        block = None
        if s.startswith("!["):
            continue
        t = _strip_marks(s)
        if t:
            lines.append(t)
    return Page(number=number, text="\n".join(lines), tables=tables, lines=lines)
