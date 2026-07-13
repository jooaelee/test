"""Rolling-origin backtesting and accuracy metrics.

For intermittent demand, per-week point accuracy is noisy and MAPE is undefined
(division by zero). We therefore score models on the business-relevant quantity:
the **h-week cumulative demand** at each rolling origin, using scaled errors that
are well defined even with many zeros.

Primary selection metric: RMSSE on cumulative h-step demand (lower is better).
We also report MASE, bias and sMAPE for reporting.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List
import numpy as np

from .models.base import Forecaster


@dataclass
class BacktestScore:
    rmsse: float
    mase: float
    smape: float
    bias: float
    n_folds: int


def _naive_scale(train: np.ndarray) -> float:
    """Mean absolute 1-step naive change over the training window (>0)."""
    if len(train) < 2:
        return 1.0
    d = np.abs(np.diff(train))
    m = d.mean()
    return float(m) if m > 0 else 1.0


def _naive_scale_sq(train: np.ndarray) -> float:
    if len(train) < 2:
        return 1.0
    d = np.diff(train)
    m = (d ** 2).mean()
    return float(m) if m > 0 else 1.0


def rolling_backtest(model_factory, y: np.ndarray, h: int,
                     folds: int, min_train: int) -> BacktestScore:
    """Evaluate ``model_factory()`` on ``folds`` rolling origins.

    ``model_factory`` is a zero-arg callable returning a *fresh* unfitted model,
    so each fold is trained independently (no leakage).
    """
    y = np.asarray(y, float)
    n = len(y)
    # Place fold cutoffs so each has h future weeks and >= min_train history.
    last_cut = n - h
    first_cut = max(min_train, n - h - folds + 1)
    cuts = list(range(first_cut, last_cut + 1))
    if not cuts:
        cuts = [max(min_train, n - h)] if n - h >= min_train else []
    if not cuts:
        return BacktestScore(np.inf, np.inf, np.inf, 0.0, 0)

    cum_err, cum_sq, smapes, biases = [], [], [], []
    for c in cuts:
        train, test = y[:c], y[c:c + h]
        if len(test) < h:
            continue
        model = model_factory().fit(train)
        fc = model.forecast(h).mean
        a_cum, f_cum = test.sum(), float(np.sum(fc))
        scale = _naive_scale(train) * h            # scale cumulative error too
        scale_sq = _naive_scale_sq(train) * (h ** 2)
        cum_err.append(abs(a_cum - f_cum) / scale)
        cum_sq.append((a_cum - f_cum) ** 2 / scale_sq)
        denom = (abs(a_cum) + abs(f_cum))
        smapes.append(2 * abs(a_cum - f_cum) / denom if denom > 0 else 0.0)
        biases.append(f_cum - a_cum)

    if not cum_err:
        return BacktestScore(np.inf, np.inf, np.inf, 0.0, 0)
    return BacktestScore(
        rmsse=float(np.sqrt(np.mean(cum_sq))),
        mase=float(np.mean(cum_err)),
        smape=float(np.mean(smapes)),
        bias=float(np.mean(biases)),
        n_folds=len(cum_err),
    )
