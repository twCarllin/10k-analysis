"""Public collection contracts, using only the HTTP system boundary."""

import json
from types import SimpleNamespace
from unittest.mock import patch
import fitz
import requests
from runtime.industry_collection.collect import collect
from runtime.industry_collection.inventory import inventory, plan
from runtime.industry_collection.model import document
from runtime.industry_collection.transport import Transport
from runtime.industry_collection.__main__ import main


def pdf(text="first"):
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 72), text)
        return doc.tobytes()


class HTTP:
    def __init__(self, contents):
        self.contents = iter(contents)
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        value = next(self.contents)
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(content=value)


def source(ticker="2360"):
    row = document(ticker, "financial_report", "2025Q2")
    row.update(url="https://doc.twse.com.tw/example.pdf", format="pdf")
    return row


def test_versions_resume_corrupt_and_metadata(tmp_path):
    first = collect([source()], tmp_path, HTTP([pdf()]))[0]
    assert first["status"] == "downloaded"
    assert first["period"] == "2025Q2"
    assert first["url"].startswith("https://")
    assert first["sha256"] and first["fetched_at"].endswith("+00:00")
    assert first["announced_at"] is None
    no_network = HTTP([])
    cached = collect([source()], tmp_path, no_network)[0]
    assert cached["status"] == "cached" and no_network.calls == 0
    revised = source()
    revised["source_filename"] = "202502_2360_AI4.pdf"
    second_bytes = pdf("changed")
    second = collect([revised], tmp_path, HTTP([second_bytes]), refresh=True)[0]
    assert second["revision_of"] == first["sha256"]
    assert second["local_path"] != first["local_path"]
    assert len(list((tmp_path / "raw").glob("*.pdf"))) == 2
    from pathlib import Path

    Path(second["local_path"]).write_bytes(b"corrupt")
    assert collect([revised], tmp_path, HTTP([]))[0]["status"] == "failed"
    recovered = collect([revised], tmp_path, HTTP([second_bytes]), refresh=True)[0]
    assert recovered["status"] == "downloaded"
    assert Path(recovered["restored_from_quarantine"]).read_bytes() == b"corrupt"
    assert collect([revised], tmp_path, HTTP([]))[0]["sha256"] == recovered["sha256"]


def test_error_html_is_failed_and_other_company_continues(tmp_path):
    result = collect(
        [source(), source("2404")],
        tmp_path,
        HTTP([b"<html>Access Denied</html>", pdf()]),
    )
    assert result[0]["status"] == "failed"
    assert result[1]["status"] == "downloaded"
    assert len(json.loads((tmp_path / "index.json").read_text())) == 2
    public_html = source("6139")
    public_html.update(format="html", url="https://www.chromaate.com/product")
    challenge_html = source("6223")
    challenge_html.update(format="html", url="https://www.chromaate.com/challenge")
    product = (
        "<html><title>Chroma SoC測試系統</title><h1>SoC測試系統規格</h1>"
        + "Product specifications " * 100
        + "<script src='https://www.google.com/recaptcha/api.js'></script></html>"
    ).encode()
    challenge = (
        "<html><title>Security check</title><h1>Verify you are human</h1>"
        + " " * 1100
        + "</html>"
    ).encode()
    html_result = collect(
        [public_html, challenge_html], tmp_path, HTTP([product, challenge])
    )
    assert html_result[0]["status"] == "downloaded"
    assert html_result[1]["status"] == "failed"


def test_timeout_and_rate_limit_have_bounded_retries(caplog):
    for error in (requests.Timeout("timeout"), requests.HTTPError("HTTP 429")):
        caplog.clear()
        with patch("requests.Session.get", side_effect=error) as get:
            transport = Transport(attempts=2, interval=0)
            result = collect([source()], __import__("tempfile").mkdtemp(), transport)
            assert result[0]["status"] == "failed"
            assert get.call_count == 2
            retries = [
                record for record in caplog.records if record.levelname == "WARNING"
            ]
            failures = [
                record for record in caplog.records if record.levelname == "ERROR"
            ]
            assert len(retries) == len(failures) == 1
            assert retries[0].event == "request_retry" and retries[0].attempt == 1
            assert failures[0].event == "document_failed" and failures[0].attempt == 2
            assert failures[0].url == source()["url"]


def test_inventory_targets_and_cli_json(tmp_path, capsys):
    known = document(
        2360,
        "financial_report",
        "2025Q4",
        url="https://doc.twse.com.tw/",
        unit="TWD thousand",
        market="sii",
        status="existing",
    )
    assert known["ticker"] == "2360" and known["doc_type"] == "financial_report"
    assert known["period"] == "2025Q4" and known["basis"] == "consolidated"
    assert known["url"] == "https://doc.twse.com.tw/"
    assert known["unit"] == "TWD thousand" and known["market"] == "sii"
    assert known["status"] == "existing" and known["announced_at"] is None
    (tmp_path / "2360_2025年報.pdf").write_bytes(pdf())
    existing = inventory(tmp_path, ["2360"])
    assert existing[0]["sha256"] and existing[0]["status"] == "existing"
    planned = plan(["2360"], existing)
    assert sum(row["doc_type"] == "monthly_revenue" for row in planned) == 36
    assert all(row["status"] in ("missing", "existing") for row in planned)
    main(["inventory", "--tickers", "2360", "--local-root", str(tmp_path)])
    output = capsys.readouterr()
    assert json.loads(output.out)[0]["ticker"] == "2360"
    log = json.loads(output.err)
    assert set(log) == {"timestamp", "level", "logger", "event", "message"}
    assert log["timestamp"].endswith("+00:00")


def test_refresh_a_b_a_updates_current_without_duplicate_raw(tmp_path):
    a, b = pdf("A"), pdf("B")
    first = collect([source()], tmp_path, HTTP([a]))[0]
    collect([source()], tmp_path, HTTP([b]), refresh=True)
    returned = collect([source()], tmp_path, HTTP([a]), refresh=True)[0]
    cached = collect([source()], tmp_path, HTTP([]))[0]
    assert returned["sha256"] == cached["sha256"] == first["sha256"]
    assert cached["status"] == "cached"
    assert len(list((tmp_path / "raw").glob("*.pdf"))) == 2
    assert len(json.loads((tmp_path / "index.json").read_text())) == 2
    assert len((tmp_path / "downloads.jsonl").read_text().splitlines()) == 3


def test_official_directory_matches_company_period_type_and_rejection(tmp_path):
    from runtime.industry_collection.sources import discover

    def reply(url, **kwargs):
        response = requests.Response()
        response.status_code = 200
        response.url = url
        response.encoding = "utf-8"
        params = kwargs.get("params", {})
        if "openapi" in url:
            response._content = b"[]"
        elif (
            params.get("year") == "114"
            and params.get("seamon") == "2"
            and params.get("dtype") == "AI1"
        ):
            html = " " * 1100 + "".join(
                f'readfile2("{kind}","{ticker}","{filename}")'
                for kind, ticker, filename in (
                    ("A", "2360", "202502_2360_AI1.pdf"),
                    ("A", "2404", "202502_2404_AI1.pdf"),
                    ("A", "2360", "202501_2360_AI1.pdf"),
                    ("A", "2360", "202502_2360_AI2.pdf"),
                )
            )
            response._content = html.encode()
        else:
            response._content = b"<html>request rejected</html>"
        return response

    with patch("requests.Session.get", side_effect=reply):
        rows = discover(["2360"], tmp_path, Transport(interval=0))
    downloaded = [row for row in rows if row.get("source_filename")]
    assert [row["source_filename"] for row in downloaded] == ["202502_2360_AI1.pdf"]
    rejected = next(
        row
        for row in rows
        if row["period"] == "2024Q3" and row["doc_type"] == "financial_report"
    )
    assert rejected["status"] == "missing"
    assert "rejection" in rejected["reason"]


def test_historical_monthly_queries_shared_and_period_checked(tmp_path):
    from runtime.industry_collection.sources import discover_monthly

    calls = []

    def reply(url, **kwargs):
        calls.append(url)
        response = requests.Response()
        response.status_code = 200
        response.url = url
        year, month = url.rsplit("/", 1)[-1].split("_")[1:3]
        ticker = "2360" if "/sii/" in url else "2404"
        if year == "112" and month == "10":
            year = "111"  # A stale page must not satisfy the requested period.
        response._content = (
            f"<html>{year}年{month}月<table><tr><td>{ticker}</td><td>Company</td><td>123</td></tr><tr><td>9999</td><td>Other</td></tr></table>"
            + " " * 1100
            + "</html>"
        ).encode("big5")
        return response

    with patch("requests.Session.get", side_effect=reply):
        rows = discover_monthly(["2360", "2404"], tmp_path, Transport(interval=0))
    assert len(calls) == len(set(calls)) == 72
    assert len(rows) == 72
    assert all(row["status"] == "missing" for row in rows if row["period"] == "2023-10")
    matches = [row for row in rows if row["period"] == "2023-11"]
    assert {(row["ticker"], row["market"]) for row in matches} == {
        ("2360", "sii"),
        ("2404", "otc"),
    }
    assert all(row["revenue_cells"][0] == row["ticker"] for row in matches)


def test_validate_cli_respects_selected_tickers(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    local = tmp_path / "tw_report"
    local.mkdir()
    (local / "2404_2025年報.pdf").write_bytes(pdf())
    main(["validate", "--tickers", "2360", "--root", str(tmp_path / "collection")])
    result = json.loads(capsys.readouterr().out)
    assert result["documents"] == []
