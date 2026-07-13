"""Persistent model registry — the mechanism behind "새 데이터 입력 시 고도화".

Each run stores, per series, the chosen model/params and the backtest accuracy,
plus an appended accuracy-history entry keyed by run date. On the next run the
previous choice becomes the "champion" challenger (see :mod:`tuning`), so the
selected model only changes when a challenger measurably improves accuracy, and
the ``accuracy_history`` shows whether forecasts get better over time.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
import numpy as np


class Registry:
    def __init__(self, path: str):
        self.path = Path(path)
        self.data = {"series": {}, "runs": []}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                pass
        self.data.setdefault("series", {})
        self.data.setdefault("runs", [])

    # -- champions ----------------------------------------------------------
    def champion(self, series_id: str) -> Optional[dict]:
        entry = self.data["series"].get(series_id)
        if not entry:
            return None
        return {"model_name": entry.get("model_name"), "params": entry.get("params", {})}

    def prior_score(self, series_id: str) -> Optional[float]:
        entry = self.data["series"].get(series_id)
        return entry.get("rmsse") if entry else None

    # -- updates ------------------------------------------------------------
    def update(self, series_id: str, grain: str, label: str,
               model_name: str, params: dict, score, run_date: str):
        entry = self.data["series"].get(series_id, {"accuracy_history": []})
        entry.update({
            "grain": grain,
            "label": label,
            "model_name": model_name,
            "params": params,
            "rmsse": _num(score.rmsse),
            "mase": _num(score.mase),
            "smape": _num(score.smape),
            "n_folds": score.n_folds,
            "last_run": run_date,
        })
        hist = entry.setdefault("accuracy_history", [])
        hist.append({"run_date": run_date, "model": model_name,
                     "rmsse": _num(score.rmsse), "mase": _num(score.mase)})
        entry["accuracy_history"] = hist[-24:]  # keep last 24 runs
        self.data["series"][series_id] = entry

    def log_run(self, run_date: str, summary: dict):
        self.data["runs"].append({"run_date": run_date, **summary})
        self.data["runs"] = self.data["runs"][-52:]

    def improvement(self, series_id: str) -> Optional[float]:
        """Relative RMSSE change vs the previous run (negative = improved).

        Guarded against a near-zero previous RMSSE (which makes the ratio
        explode) and clipped to a sane band so aggregates stay meaningful.
        """
        hist = self.data["series"].get(series_id, {}).get("accuracy_history", [])
        if len(hist) < 2:
            return None
        prev, cur = hist[-2].get("rmsse"), hist[-1].get("rmsse")
        if prev is None or cur is None or prev < 1e-3:
            return None
        return float(np.clip((cur - prev) / prev, -1.0, 5.0))

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2),
                             encoding="utf-8")


def _num(x):
    """JSON-safe float (inf/nan -> None)."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if np.isfinite(x) else None
