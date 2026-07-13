"""Time-series models for 지속형 (continuous-demand) SKUs and customers.

These series have regular weekly demand, so ordinary smoothing / trend models
work well. We keep a small, fast, robust set and let the tuner pick the best by
backtest. statsmodels powers SES/Holt; if a fit fails we fall back to a mean.
"""
from __future__ import annotations

import warnings
import numpy as np

from .base import Forecaster, ForecastResult

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    try:
        from statsmodels.tsa.holtwinters import (
            SimpleExpSmoothing, ExponentialSmoothing,
        )
        _HAS_SM = True
    except Exception:  # pragma: no cover
        _HAS_SM = False


def _occurrence(y: np.ndarray) -> float:
    return float((y > 0).mean()) if len(y) else 0.0


class MovingAverage(Forecaster):
    name = "ma"

    def _fit(self, y):
        k = int(self.params.get("window", 8))
        self._level = float(y[-k:].mean()) if len(y) else 0.0
        self._occ = _occurrence(y)

    def _predict(self, h):
        return ForecastResult(mean=np.full(h, max(self._level, 0.0)),
                              p_occurrence=self._occ, demand_size=self._level)


class SeasonalNaive(Forecaster):
    """Repeat the value from ``season`` weeks ago (default 52 = yearly)."""
    name = "snaive"

    def _fit(self, y):
        self._y = np.asarray(y, float)
        self._season = int(self.params.get("season", 52))
        self._occ = _occurrence(y)

    def _predict(self, h):
        m, y = self._season, self._y
        if len(y) >= m:
            base = np.array([y[-m + (t % m)] for t in range(h)])
        else:
            base = np.full(h, y[-1] if len(y) else 0.0)
        return ForecastResult(mean=np.clip(base, 0, None),
                              p_occurrence=self._occ, demand_size=base.mean())


class SES(Forecaster):
    name = "ses"

    def _fit(self, y):
        self._occ = _occurrence(y)
        alpha = self.params.get("alpha", None)
        if _HAS_SM and len(y) >= 3 and y.sum() > 0:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    fit_kw = {"optimized": alpha is None}
                    if alpha is not None:
                        fit_kw["smoothing_level"] = alpha
                    self._model = SimpleExpSmoothing(y).fit(**fit_kw)
                    self._level = float(self._model.forecast(1)[0])
                    return
                except Exception:
                    pass
        self._model = None
        self._level = float(y[-8:].mean()) if len(y) else 0.0

    def _predict(self, h):
        if self._model is not None:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                fc = np.asarray(self._model.forecast(h), float)
        else:
            fc = np.full(h, self._level)
        return ForecastResult(mean=np.clip(fc, 0, None),
                              p_occurrence=self._occ, demand_size=float(fc.mean()))


class Holt(Forecaster):
    """Holt's linear trend (optionally damped)."""
    name = "holt"

    def _fit(self, y):
        self._occ = _occurrence(y)
        damped = bool(self.params.get("damped", True))
        self._model = None
        if _HAS_SM and len(y) >= 6 and y.sum() > 0:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    self._model = ExponentialSmoothing(
                        y, trend="add", damped_trend=damped, seasonal=None
                    ).fit()
                except Exception:
                    self._model = None
        self._level = float(y[-8:].mean()) if len(y) else 0.0

    def _predict(self, h):
        if self._model is not None:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                fc = np.asarray(self._model.forecast(h), float)
        else:
            fc = np.full(h, self._level)
        return ForecastResult(mean=np.clip(fc, 0, None),
                              p_occurrence=self._occ, demand_size=float(fc.mean()))
