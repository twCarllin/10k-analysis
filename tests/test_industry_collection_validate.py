"""Public offline validation contracts using real local PDF files."""

import hashlib
import json
from pathlib import Path

import fitz

from runtime.industry_collection.validate import validate_collection, validate


def _pdf(path, pages):
    doc = fitz.open()
    for lines in pages:
        page = doc.new_page()
        for index, line in enumerate(lines):
            page.insert_text(
                (40, 40 + index * 24), line, fontname="china-t", fontsize=11
            )
    doc.save(path)
    doc.close()
    return path


def _record(path, **values):
    return dict(
        ticker="2360",
        doc_type="financial_report",
        period="2026Q2",
        local_path=str(path),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        status="existing",
        **values,
    )


def test_source_column_period_and_cumulative_basis(tmp_path):
    path = _pdf(
        tmp_path / "financial.pdf",
        [
            [
                "合併資產負債表",
                "115年6月30日 114年12月31日 114年6月30日",
                "單位：新台幣千元",
                "1100 現金及約當現金 1,234 1,111 1,000",
                "資產總計 1,234 1,111 1,000",
            ],
            [
                "合併綜合損益表",
                "115年1月1日至6月30日 114年1月1日至6月30日",
                "單位：新台幣千元",
                "4000 營業收入 9,876 8,765",
                "5000 營業成本 4,000 3,000",
                "營業毛利 5,876 5,765",
            ],
            [
                "合併現金流量表",
                "115年1月1日至6月30日 114年1月1日至6月30日",
                "單位：新台幣千元",
                "AAAA 營業活動之淨現金流入 1,234 1,111",
            ],
            ["合併現金流量表(續)", "其他現金流量 20 10"],
        ],
    )
    report = validate_collection(
        tmp_path, ["2360"], tmp_path / "out", documents=[_record(path)]
    )
    revenue = next(
        row for row in report["financial_samples"] if row["key"] == "revenue"
    )
    assert revenue["value"] == 9876
    assert revenue["current_column"] == 0
    assert revenue["columns"] == [9876, 8765]
    assert revenue["period"] == "2026-01-01~2026-06-30"
    assert revenue["basis"] == "consolidated"
    assert revenue["period_basis"] == "H1"
    assert revenue["currency"] == "TWD"
    assert revenue["unit"] == "新台幣千元"
    assert revenue["page"] == 2
    assert "9,876" in revenue["quote"]
    assert "115年1月1日" in revenue["header_quote"]
    assert revenue["source_sha256"] == _record(path)["sha256"]
    assert revenue["source_check"] == "matched"
    assert revenue["human_check"] == "pending"
    assert any(
        row["label"] == "其他現金流量" for row in report["blocked_financial_samples"]
    )
    assert all(row["source_check"] == "matched" for row in report["financial_samples"])
    assert len(report["all_financial_samples"]) == len(
        report["financial_samples"]
    ) + len(report["blocked_financial_samples"])
    assert any("financial_samples_insufficient" in str(gap) for gap in report["gaps"])


def test_document_failure_isolation_origin_counts_and_hash(tmp_path):
    valid = _pdf(tmp_path / "valid.pdf", [["資料"]])
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not pdf")
    failed_remote = dict(
        ticker="2360",
        doc_type="financial_report",
        period="2026Q2",
        status="failed",
        url="https://example.invalid/failed",
        reason="HTTP 200 error HTML",
    )
    missing = dict(
        ticker="2360",
        doc_type="financial_report",
        period="2026Q2",
        status="missing",
        reason="official source not found",
    )
    records = [
        _record(broken),
        _record(valid, origin="downloaded"),
        failed_remote,
        missing,
    ]
    report = validate_collection(
        tmp_path, ["2360"], tmp_path / "out", documents=records
    )
    assert report["counts"] == {
        "local_existing": 1,
        "downloaded": 1,
        "failed": 1,
        "missing": 1,
    }
    assert len(report["documents"]) == 4
    assert report["documents"][0]["validation"] == "blocked"
    assert report["documents"][0]["gaps"]
    assert report["documents"][1]["gaps"] == ["statements_missing"]
    assert report["documents"][2]["gaps"] == ["HTTP 200 error HTML"]
    assert report["documents"][3]["gaps"] == ["official source not found"]
    assert [row["source_state"] for row in report["documents"]] == [
        "local_existing",
        "downloaded",
        "failed",
        "missing",
    ]
    assert report["usable_sources"] == []
    assert report["input_files"] == []
    record = _record(valid)
    record["sha256"] = "wrong"
    second = validate_collection(
        tmp_path, ["2360"], tmp_path / "hash", documents=[record]
    )
    assert second["documents"][0]["gaps"] == ["ValueError: source_hash_mismatch"]


def test_missing_data_unsupported_parser_and_collection_index(tmp_path):
    out = tmp_path / "collection"
    out.mkdir()
    raw = tmp_path / "revenue.json"
    raw.write_text("{}")
    record = _record(raw, origin="downloaded")
    record["doc_type"] = "monthly_revenue"
    (out / "index.json").write_text(json.dumps([record]))
    report = validate(out, tickers=["2360"], repo_root=tmp_path)
    assert report["documents"][0]["gaps"] == ["ValueError: unsupported_local_parser"]
    assert report["human_check"] == "pending"
    empty = validate_collection(tmp_path, ["9999"], tmp_path / "empty", documents=[])
    assert "documents_missing" in empty["gaps"]
    assert any(
        "relationship_samples_insufficient: 0/10; all sampled" == gap
        for gap in empty["gaps"]
    )
    assert (out / "validation/report.json").is_file()


def test_annual_named_and_anonymous_candidates_remain_pending(tmp_path):
    path = tmp_path / "annual.pdf"
    doc = fitz.open()
    page = doc.new_page(width=1000)
    page.insert_text((30, 40), "主要銷貨客戶", fontname="china-t", fontsize=12)
    rows = [
        ["", "113年度", "", "", "", "114年度", "", "", ""],
        [
            "排名",
            "名稱",
            "銷貨金額",
            "比率",
            "關係",
            "名稱",
            "銷貨金額",
            "比率",
            "關係",
        ],
        ["1", "Real Corp", "1,000", "50", "無", "A公司", "2,000", "50", "無"],
        ["", "合計", "1,000", "50", "", "總計", "2,000", "50", ""],
        ["", "其 他", "1,000", "50", "", "其他", "2,000", "50", ""],
        ["", "銷貨淨額", "1,000", "50", "", "進貨淨額", "2,000", "50", ""],
        ["", "-", "1,000", "50", "", "--", "2,000", "50", ""],
    ]
    for y in range(len(rows) + 1):
        page.draw_line((30, 80 + y * 35), (930, 80 + y * 35))
    for x in range(10):
        page.draw_line((30 + x * 100, 80), (30 + x * 100, 80 + len(rows) * 35))
    for y, row in enumerate(rows):
        for x, cell in enumerate(row):
            page.insert_text(
                (34 + x * 100, 103 + y * 35), cell, fontname="china-t", fontsize=9
            )
    doc.save(path)
    doc.close()
    record = _record(path)
    record.update(doc_type="annual_report", period="2025")
    report = validate_collection(
        tmp_path, ["2360"], tmp_path / "out", documents=[record]
    )
    named = report["relationship_samples"]
    anonymous = report["anonymous_candidates"]
    excluded = report["excluded_relationships"]
    assert {row["name"] for row in excluded} == {
        "合計",
        "總計",
        "其 他",
        "其他",
        "銷貨淨額",
        "進貨淨額",
        "-",
        "--",
    }
    assert {row["reason"] for row in excluded} == {
        "aggregate_or_other",
        "invalid_counterparty",
        "missing_name",
    }
    assert all(
        row["page"] == 1 and row["source_sha256"] == record["sha256"]
        for row in excluded
    )
    assert len(named) == 1
    assert named[0]["name"] == "Real Corp"
    assert named[0]["period"] == "2024-01-01~2024-12-31"
    assert named[0]["page"] == 1
    assert "Real Corp" in named[0]["quote"]
    assert named[0]["status"] == "pending"
    assert named[0]["source_sha256"] == record["sha256"]
    assert len(anonymous) == 1
    assert anonymous[0]["name"] == "A公司"
    assert anonymous[0]["anonymous"] is True
    assert anonymous[0]["status"] == "pending"
    assert any(
        "relationship_samples_insufficient: 1/10" in str(gap) for gap in report["gaps"]
    )


def test_compatible_period_input_index_and_mismatched_period_block(tmp_path):
    bs = [
        ("現金及約當現金", 100),
        ("流動資產合計", 50),
        ("非流動資產合計", 50),
        ("資產總計", 100),
        ("負債總計", 40),
        ("權益總計", 60),
        ("負債及權益總計", 100),
    ]
    income = [
        ("營業收入", 100),
        ("營業成本", 40),
        ("營業毛利", 60),
        ("營業費用合計", 10),
        ("營業利益", 50),
        ("營業外收入及支出合計", 10),
        ("稅前淨利", 60),
        ("所得稅費用", 10),
        ("本期淨利", 50),
    ]
    cf = [
        ("本期稅前淨利", 60),
        ("營業活動之淨現金流入", 10),
        ("投資活動之淨現金流入", 0),
        ("籌資活動之淨現金流入", 0),
        ("匯率變動對現金及約當現金之影響", 0),
        ("本期現金及約當現金增加數", 10),
        ("期初現金及約當現金餘額", 90),
        ("期末現金及約當現金餘額", 100),
    ]
    pages = []
    for title, periods, rows in [
        ("合併資產負債表", "115年6月30日 114年12月31日 114年6月30日", bs),
        ("合併綜合損益表", "115年1月1日至6月30日 114年1月1日至6月30日", income),
        ("合併現金流量表", "115年1月1日至6月30日 114年1月1日至6月30日", cf),
    ]:
        pages.append(
            [title, periods, "單位：新台幣千元"]
            + [
                f"{label} {amount} {amount}"
                + (f" {amount}" if title == "合併資產負債表" else "")
                for label, amount in rows
            ]
        )
    fs = _pdf(tmp_path / "fs.pdf", pages)
    with fitz.open(fs) as document:
        cover = document.new_page()
        pixels = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 2, 2), False)
        pixels.clear_with(255)
        cover.insert_image(cover.rect, stream=pixels.tobytes("png"))
        document.saveIncr()
    annual = _pdf(tmp_path / "annual.pdf", [["114年年報"]])
    records = [_record(fs), _record(annual)]
    records[1].update(doc_type="annual_report", period="2025")
    inputs = tmp_path / "tw_equity_inputs"
    inputs.mkdir()
    (inputs / "2360.json").write_text(
        json.dumps(
            dict(
                company_name="Fixture Corp",
                group="industrial",
                prior={"fiscal_year": 2020, "annual_report_path": "old.pdf"},
                fy_consolidated_fs_path="old-fy.pdf",
                fy_fs_period="FY2020",
                parent_fs_path="old-parent.pdf",
            )
        )
    )
    report = validate_collection(
        tmp_path, ["2360"], tmp_path / "out", documents=records
    )
    assert len(report["input_files"]) == 1, report["gaps"]
    assert report["documents"][0]["pdf_warnings"]["image_pages"] == [4]
    generated = json.loads(Path(report["input_files"][0]).read_text())
    assert generated["consolidated_fs_path"] == str(fs)
    assert generated["annual_report_path"] == str(annual)
    assert generated["fiscal_year"] == 2025
    assert generated["fs_period"] == "2026H1"
    assert generated["parent_fs_path"] is None
    assert set(generated) == {
        "company_name",
        "group",
        "parent_fs_path",
        "ticker",
        "consolidated_fs_path",
        "annual_report_path",
        "fs_period",
        "fiscal_year",
    }
    assert len(report["financial_samples"]) == 20
    assert {row["statement"] for row in report["financial_samples"]} == {
        "bs",
        "is",
        "cf",
    }
    original_path = Path(report["input_files"][0])
    original_bytes = original_path.read_bytes()
    original_mtime = original_path.stat().st_mtime_ns
    annual_revision = _pdf(tmp_path / "annual-revised.pdf", [["114年年報 修訂B"]])
    revised_record = _record(annual_revision)
    revised_record.update(doc_type="annual_report", period="2025")
    combined_records = records + [revised_record]
    revised = validate_collection(
        tmp_path, ["2360"], tmp_path / "out", documents=combined_records
    )
    assert len(revised["input_files"]) == 2
    assert str(original_path) in revised["input_files"]
    assert {
        json.loads(Path(path).read_text())["annual_report_path"]
        for path in revised["input_files"]
    } == {str(annual), str(annual_revision)}
    assert original_path.read_bytes() == original_bytes
    assert original_path.stat().st_mtime_ns == original_mtime
    for manifest in revised["input_sources"]:
        assert len(manifest["version_id"]) == 129
        assert manifest["version_id"] == "_".join(
            row["sha256"] for row in manifest["sources"]
        )
        source_path = Path(manifest["input_path"]).with_name("2360.sources.json")
        assert json.loads(source_path.read_text()) == manifest
    stored = {
        path: (Path(path).read_bytes(), Path(path).stat().st_mtime_ns)
        for path in revised["input_files"]
    }
    resumed = validate_collection(
        tmp_path, ["2360"], tmp_path / "out", documents=list(reversed(combined_records))
    )
    assert set(resumed["input_files"]) == set(stored)
    assert all(
        (Path(path).read_bytes(), Path(path).stat().st_mtime_ns) == prior
        for path, prior in stored.items()
    )
    wrong = dict(records[0], period="2025Q2")
    failed = validate_collection(
        tmp_path, ["2360"], tmp_path / "wrong", documents=[wrong, records[1]]
    )
    assert failed["input_files"] == []
    assert "declared_period_mismatch_or_missing" in failed["documents"][0]["gaps"]
