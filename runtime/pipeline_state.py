import json
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class PipelineState:
    """Per-agent checkpoint manager. Each agent call is an independent checkpoint."""

    def __init__(self, ticker: str, year: int, prior_year: int | None = None,
                 filing_type: str = "10-K", quarter: str | None = None):
        self.ticker = ticker
        self.year = year
        self.prior_year = prior_year
        self.filing_type = filing_type
        self.quarter = quarter
        suffix = filing_type.replace("-", "")
        if quarter:
            suffix += f"_{quarter}"
        self.path = BASE_DIR / f"data/cache/pipeline_{ticker}_{year}_{suffix}.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
            # Validate same run params
            if (self._data.get("ticker") != ticker
                    or self._data.get("year") != year
                    or self._data.get("prior_year") != prior_year
                    or self._data.get("filing_type", "10-K") != filing_type
                    or self._data.get("quarter") != quarter):
                print(f"  [State] 參數不同，重新開始")
                self._init_fresh()
            else:
                done = [k for k, v in self._data["steps"].items()
                        if v.get("status") == "done"]
                if done:
                    print(f"  [State] 載入既有進度，已完成：{', '.join(done)}")
                # Reset any "running" steps to "pending" (crashed)
                for k, v in self._data["steps"].items():
                    if v.get("status") == "running":
                        v["status"] = "pending"
                        print(f"  [State] 重設中斷步驟：{k}")
        else:
            self._init_fresh()

    def _init_fresh(self):
        self._data = {
            "ticker": self.ticker,
            "year": self.year,
            "prior_year": self.prior_year,
            "filing_type": self.filing_type,
            "quarter": self.quarter,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "steps": {},
        }
        self._save()

    def _save(self):
        self._data["updated_at"] = datetime.now().isoformat()
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def is_done(self, step_key: str) -> bool:
        return self._data["steps"].get(step_key, {}).get("status") == "done"

    def get_result(self, step_key: str) -> dict | None:
        step = self._data["steps"].get(step_key)
        if step and step.get("status") == "done":
            return step.get("result")
        return None

    def mark_running(self, step_key: str):
        self._data["steps"].setdefault(step_key, {})
        self._data["steps"][step_key]["status"] = "running"
        self._save()

    def mark_done(self, step_key: str, result: dict):
        self._data["steps"][step_key] = {
            "status": "done",
            "result": result,
            "completed_at": datetime.now().isoformat(),
        }
        self._save()

    def mark_eval(self, step_key: str, eval_result: dict):
        """Store eval result, appending to history for debug."""
        step = self._data["steps"].setdefault(step_key, {})
        step["status"] = "done"
        step["result"] = eval_result
        step.setdefault("history", []).append({
            "ts": datetime.now().isoformat(),
            **eval_result,
        })
        self._save()

    def invalidate(self, step_key: str):
        """Reset a done step to pending so it will re-run."""
        if step_key in self._data["steps"]:
            self._data["steps"][step_key]["status"] = "pending"
            self._data["steps"][step_key].pop("result", None)
            self._save()

    def clear(self):
        """Remove state file."""
        if self.path.exists():
            self.path.unlink()
