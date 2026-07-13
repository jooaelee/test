"""Common model interface."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import numpy as np


@dataclass
class ForecastResult:
    mean: np.ndarray             # expected demand per future week, length h
    p_occurrence: float = 0.0    # per-week probability demand > 0 (if modelled)
    demand_size: float = 0.0     # expected size when demand occurs
    meta: dict = field(default_factory=dict)


class Forecaster:
    """Minimal base class. Subclasses implement ``_fit`` and ``_predict``."""

    name = "base"

    def __init__(self, **params):
        self.params = params
        self._fitted = False
        self._last: Optional[ForecastResult] = None

    # -- public API ---------------------------------------------------------
    def fit(self, y: np.ndarray) -> "Forecaster":
        self.y = np.asarray(y, dtype=float)
        self._fit(self.y)
        self._fitted = True
        return self

    def forecast(self, h: int) -> ForecastResult:
        if not self._fitted:
            raise RuntimeError("call fit() before forecast()")
        res = self._predict(h)
        self._last = res
        return res

    # -- to be overridden ---------------------------------------------------
    def _fit(self, y: np.ndarray) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def _predict(self, h: int) -> ForecastResult:  # pragma: no cover
        raise NotImplementedError

    # -- helpers ------------------------------------------------------------
    def label(self) -> str:
        ps = ",".join(f"{k}={v}" for k, v in sorted(self.params.items()))
        return f"{self.name}({ps})" if ps else self.name
