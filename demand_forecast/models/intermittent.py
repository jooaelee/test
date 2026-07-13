"""Intermittent-demand models for 교체형 (replacement-type) SKUs.

These SKUs ship sporadically: many zero weeks punctuated by occasional orders.
Classic per-period smoothing (SES on the raw series) is badly biased here, so we
use the Croston family, which separately smooths *demand size* and *interval*.

* Croston (1972): forecast = z / p        (z=size, p=interval)
* SBA (Syntetos-Boylan Approx.): multiplies by (1 - a/2) to remove Croston's
  positive bias — the recommended default for intermittent demand.
* TSB (Teunter-Syntetos-Babai): updates the demand *probability* every period,
  so it decays gracefully for obsolescent items and yields a clean per-week
  occurrence probability — which we reuse for the "대량 출고 확률" report.
"""
from __future__ import annotations

import numpy as np

from .base import Forecaster, ForecastResult


def _croston_smooth(y: np.ndarray, alpha: float):
    """Return smoothed (size z, interval p) using Croston's recursion."""
    nz = np.flatnonzero(y > 0)
    if nz.size == 0:
        return 0.0, np.inf
    # Initialise from the first demand and its position (interval from start).
    z = float(y[nz[0]])
    p = float(nz[0] + 1)
    last = nz[0]
    for t in nz[1:]:
        interval = float(t - last)
        z = alpha * y[t] + (1 - alpha) * z
        p = alpha * interval + (1 - alpha) * p
        last = t
    return z, p


class Croston(Forecaster):
    name = "croston"

    def _fit(self, y):
        alpha = self.params.get("alpha", 0.1)
        self._z, self._p = _croston_smooth(y, alpha)
        self._rate = 0.0 if not np.isfinite(self._p) or self._p == 0 else self._z / self._p
        self._occ = 0.0 if not np.isfinite(self._p) or self._p == 0 else 1.0 / self._p

    def _predict(self, h):
        return ForecastResult(
            mean=np.full(h, self._rate, dtype=float),
            p_occurrence=self._occ,
            demand_size=self._z,
            meta={"z": self._z, "interval": self._p},
        )


class SBA(Croston):
    """Croston with the Syntetos-Boylan bias correction."""
    name = "sba"

    def _fit(self, y):
        super()._fit(y)
        alpha = self.params.get("alpha", 0.1)
        self._rate *= (1 - alpha / 2.0)


class TSB(Forecaster):
    name = "tsb"

    def _fit(self, y):
        alpha = self.params.get("alpha", 0.1)   # smooths demand size
        beta = self.params.get("beta", 0.1)     # smooths demand probability
        nz = np.flatnonzero(y > 0)
        if nz.size == 0:
            self._z, self._p = 0.0, 0.0
        else:
            z = float(y[nz[0]])
            p = 1.0 / float(nz[0] + 1)
            for t in range(len(y)):
                if y[t] > 0:
                    z = z + alpha * (y[t] - z)
                    p = p + beta * (1.0 - p)
                else:
                    p = p + beta * (0.0 - p)
            self._z, self._p = z, float(np.clip(p, 0.0, 1.0))
        self._rate = self._p * self._z

    def _predict(self, h):
        return ForecastResult(
            mean=np.full(h, self._rate, dtype=float),
            p_occurrence=self._p,
            demand_size=self._z,
            meta={"z": self._z, "prob": self._p},
        )
