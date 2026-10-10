"""inputs.py — 台股財報 pipeline 輸入載入與驗證。

讀取 `<base_dir>/tw_equity_inputs/<ticker>.json`，回傳 TwEquityInputs dataclass。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


FH_SCHEMA_GROUPS: frozenset[str] = frozenset({"fh", "bank"})


def uses_fh_schema(group: str | None) -> bool:
    """金控（fh）與銀行（bank）同走金控三表 schema；group 標籤本身不改。"""
    return group in FH_SCHEMA_GROUPS


@dataclass(frozen=True)
class PriorYearInputs:
    fiscal_year: int
    annual_report_path: Path
    consolidated_fs_path: Path | None
    parent_fs_path: Path | None

    @property
    def roc_year(self) -> int:
        """民國年：fiscal_year - 1911。"""
        return self.fiscal_year - 1911


@dataclass(frozen=True)
class TwEquityInputs:
    ticker: str
    company_name: str
    fiscal_year: int
    annual_report_path: Path
    consolidated_fs_path: Path | None
    parent_fs_path: Path | None
    prior: PriorYearInputs | None = None
    group: str | None = None  # 公司類別（"fh" 金控、"bank" 銀行；兩者同走 fh schema）；缺 → None（工業流程）

    @property
    def roc_year(self) -> int:
        """民國年：fiscal_year - 1911。"""
        return self.fiscal_year - 1911


def load_inputs(ticker: str, *, base_dir: Path | None = None) -> TwEquityInputs:
    """讀取 <base_dir>/tw_equity_inputs/<ticker>.json 並回傳 TwEquityInputs。

    Args:
        ticker: 股票代號（如 "3653"）。
        base_dir: 輸入目錄的根路徑；預設為工作目錄。

    Raises:
        FileNotFoundError: 輸入 JSON 或必填 PDF 路徑不存在。
        ValueError: 必填欄位缺失或型別錯誤（訊息含欄名）。
    """
    if base_dir is None:
        base_dir = Path(".")

    json_path = base_dir / "tw_equity_inputs" / f"{ticker}.json"
    if not json_path.exists():
        raise FileNotFoundError(f"輸入檔不存在：{json_path}")

    with json_path.open(encoding="utf-8") as f:
        data = json.load(f)

    # 驗證必填欄位
    errors: list[str] = []

    def _require_str(key: str) -> str | None:
        val = data.get(key)
        if val is None:
            errors.append(key)
            return None
        if not isinstance(val, str):
            errors.append(key)
            return None
        return val

    ticker_val = _require_str("ticker")
    company_name = _require_str("company_name")
    annual_report_path_str = _require_str("annual_report_path")

    fiscal_year_raw = data.get("fiscal_year")
    if fiscal_year_raw is None:
        errors.append("fiscal_year")
        fiscal_year: int | None = None
    elif not isinstance(fiscal_year_raw, int):
        errors.append("fiscal_year")
        fiscal_year = None
    else:
        fiscal_year = fiscal_year_raw

    if errors:
        raise ValueError(f"必填欄位缺失或型別錯誤：{', '.join(errors)}")

    # 型別已驗證，使用 assert 讓型別檢查器收窄
    assert ticker_val is not None
    assert company_name is not None
    assert annual_report_path_str is not None
    assert fiscal_year is not None

    def _resolve(rel: str) -> Path:
        """將相對路徑相對於 base_dir 解析；絕對路徑原樣回傳。"""
        p = Path(rel)
        if not p.is_absolute():
            p = base_dir / p
        return p

    annual_report_path = _resolve(annual_report_path_str)
    if not annual_report_path.exists():
        raise FileNotFoundError(f"年報 PDF 不存在：{annual_report_path}")

    def _optional_path(key: str, src: dict | None = None) -> Path | None:
        val = (data if src is None else src).get(key)
        if val is None:
            return None
        p = _resolve(val)
        if not p.exists():
            raise FileNotFoundError(f"{key} 指定的檔案不存在：{p}")
        return p

    consolidated_fs_path = _optional_path("consolidated_fs_path")
    parent_fs_path = _optional_path("parent_fs_path")

    prior = _load_prior(data.get("prior"), fiscal_year, _resolve, _optional_path)

    return TwEquityInputs(
        ticker=ticker_val,
        company_name=company_name,
        fiscal_year=fiscal_year,
        annual_report_path=annual_report_path,
        consolidated_fs_path=consolidated_fs_path,
        parent_fs_path=parent_fs_path,
        prior=prior,
        group=data.get("group"),
    )


def _load_prior(raw, fiscal_year, _resolve, _optional_path) -> PriorYearInputs | None:
    """解析選填的 prior 區塊；缺或 null → None。"""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("必填欄位缺失或型別錯誤：prior")
    errors: list[str] = []
    py = raw.get("fiscal_year")
    if not isinstance(py, int) or isinstance(py, bool):
        errors.append("prior.fiscal_year")
    ar = raw.get("annual_report_path")
    if not isinstance(ar, str):
        errors.append("prior.annual_report_path")
    if errors:
        raise ValueError(f"必填欄位缺失或型別錯誤：{', '.join(errors)}")
    if py != fiscal_year - 1:
        raise ValueError(
            f"prior.fiscal_year 必須為 fiscal_year-1：fiscal_year={fiscal_year}，"
            f"prior.fiscal_year={py}"
        )
    ar_path = _resolve(ar)
    if not ar_path.exists():
        raise FileNotFoundError(f"prior 年報 PDF 不存在：{ar_path}")
    return PriorYearInputs(
        fiscal_year=py,
        annual_report_path=ar_path,
        consolidated_fs_path=_optional_path("consolidated_fs_path", raw),
        parent_fs_path=_optional_path("parent_fs_path", raw),
    )
