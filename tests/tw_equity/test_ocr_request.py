"""DiPageOcr.fetch 請求／輪詢／錯誤處理（全以注入假 HTTP，不發真實請求）。"""
import pytest

from runtime.tw_credit.adapters import AdapterError
from runtime.tw_equity import ocr as ocr_mod
from runtime.tw_equity.ocr import DiPageOcr

ENDPOINT = "https://fake-di.example.test"
KEY = "SECRET-KEY-123"
RESULT = {"pages": [{"pageNumber": 51, "lines": []}], "tables": []}


class Resp:
    def __init__(self, status, body=None, headers=None, reason=""):
        self.status_code = status
        self._body = body or {}
        self.headers = headers or {}
        self.reason = reason

    def json(self):
        return self._body


@pytest.fixture
def pdf(tmp_path):
    p = tmp_path / "a.pdf"
    p.write_bytes(b"%PDF-fake")
    return p


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    monkeypatch.setattr(ocr_mod, "_load_azure_config",
                        lambda: {"di_endpoint": ENDPOINT, "di_key": KEY})


def test_200_returns_analyze_result(pdf):
    calls = []

    def post(url, **kw):
        calls.append((url, kw))
        return Resp(200, {"status": "succeeded", "analyzeResult": RESULT})

    out = DiPageOcr(_http_post=post, _http_get=None, _sleep=lambda s: None).fetch(pdf, [51, 79])
    assert out == RESULT
    url, kw = calls[0]
    assert "pages=51,79" in url
    assert KEY not in url
    assert "Ocp-Apim-Subscription-Key" in kw["headers"]


def test_202_polls_then_succeeds(pdf):
    sleeps = []
    gets = [Resp(200, {"status": "running"}),
            Resp(200, {"status": "succeeded", "analyzeResult": RESULT})]

    def post(url, **kw):
        return Resp(202, headers={"Operation-Location": "https://op.example.test/1"})

    def get(url, **kw):
        assert "Ocp-Apim-Subscription-Key" in kw["headers"]
        return gets.pop(0)

    out = DiPageOcr(_http_post=post, _http_get=get, _sleep=sleeps.append).fetch(pdf, [51])
    assert out == RESULT
    assert sleeps == [2, 2]


def test_4xx_raises_without_secrets(pdf):
    d = DiPageOcr(_http_post=lambda url, **kw: Resp(401, reason="Unauthorized"),
                  _sleep=lambda s: None)
    with pytest.raises(AdapterError) as ei:
        d.fetch(pdf, [51])
    assert ENDPOINT not in str(ei.value)
    assert KEY not in str(ei.value)


def test_poll_timeout_raises(pdf):
    total = []
    d = DiPageOcr(
        _http_post=lambda url, **kw: Resp(202, headers={"Operation-Location": "https://op.example.test/1"}),
        _http_get=lambda url, **kw: Resp(200, {"status": "running"}),
        _sleep=total.append,
    )
    with pytest.raises(AdapterError):
        d.fetch(pdf, [51])
    assert sum(total) >= 180


@pytest.mark.parametrize("missing", ["di_endpoint", "di_key"])
def test_missing_config_raises_at_construction(monkeypatch, missing):
    c = {"di_endpoint": ENDPOINT, "di_key": KEY}
    c.pop(missing)
    monkeypatch.setattr(ocr_mod, "_load_azure_config", lambda: c)
    with pytest.raises(AdapterError, match="Azure DI 設定缺漏"):
        DiPageOcr()
