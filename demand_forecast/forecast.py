"""Turn a tuned model into the deliverables: 4-week forecasts, large-shipment
probabilities, and routine (small-volume) expectations for a single series.

The 대량/소량 split is configurable (see :class:`Config.split_mode`):

* ``"channel"`` (default) — 소량 is demand shipped via express couriers
  (DHL/FedEx/UPS); 대량 is everything else (freight, pickup). The caller supplies
  the pre-split ``bulk_y`` (대량) and ``express_y`` (소량) weekly series.
* ``"quantile"`` — 대량 is a weekly quantity at/above a per-series quantile of the
  total series; 소량 is the winsorised remainder.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import numpy as np

from .config import Config
from .models import build_model
from .models.intermittent import TSB


@dataclass
class SeriesForecast:
    weekly: np.ndarray          # expected total demand per future week (length h)
    total: float                # cumulative expected demand over the horizon
    p_occurrence: float         # per-week probability of any shipment
    # Large (대량) / small (소량) decomposition --------------------------------
    large_threshold: float      # weekly qty defining 대량 (quantile mode; 0 in channel mode)
    p_large_week: float         # smoothed per-week probability of a 대량 week
    p_large_horizon: float      # probability of >=1 대량 shipment within h weeks
    expected_large_size: float  # expected qty of a 대량 shipment
    bulk_share: float           # 대량(비특송) share of this series' total volume
    routine_weekly: float       # expected 소량 weekly qty
    routine_total: float        # 소량 expectation over the horizon
    last_large_week: Optional[object] = None


def _bernoulli_rate(binary: np.ndarray, alpha: float = 0.2) -> float:
    """Smoothed probability that next week is a '1', via the TSB probability
    recursion (robust for sparse events)."""
    if binary.sum() == 0:
        return 0.0
    res = TSB(alpha=alpha, beta=alpha).fit(binary.astype(float)).forecast(1)
    return float(np.clip(res.p_occurrence, 0.0, 1.0))


def _large_from_series(large_y, model_name, params, h, week_index):
    """Occurrence probability + expected size for a 대량 weekly series."""
    large_y = np.asarray(large_y, float)
    mask = large_y > 0
    p_week = _bernoulli_rate(mask.astype(float))
    p_h = 1.0 - (1.0 - p_week) ** h
    sizes = large_y[mask]
    exp_size = float(sizes.mean()) if sizes.size else 0.0
    last = None
    if week_index is not None:
        idx = np.flatnonzero(mask)
        if idx.size:
            last = week_index[idx[-1]]
    return p_week, p_h, exp_size, last


def forecast_series(y: np.ndarray, model_name: str, params: dict, cfg: Config,
                    week_index=None, bulk_y=None, express_y=None) -> SeriesForecast:
    """Fit the chosen model on the full total-demand history and produce all
    outputs. In channel mode, ``bulk_y``/``express_y`` are the pre-split 대량/소량
    weekly series; in quantile mode they are ignored and derived from ``y``."""
    y = np.asarray(y, float)
    h = cfg.horizon_weeks
    model = build_model(model_name, params).fit(y)
    res = model.forecast(h)
    weekly = np.clip(res.mean, 0.0, None)
    total_vol = float(y.sum())

    if cfg.split_mode == "channel":
        bulk = np.asarray(bulk_y, float) if bulk_y is not None else np.zeros_like(y)
        express = np.asarray(express_y, float) if express_y is not None else np.zeros_like(y)
        large_thr = 0.0
        p_week, p_h, exp_large, last_large = _large_from_series(
            bulk, model_name, params, h, week_index)
        bulk_share = float(bulk.sum() / total_vol) if total_vol > 0 else 0.0
        # 소량 forecast: apply the chosen model to the express-only series.
        routine_weekly = float(np.clip(
            build_model(model_name, params).fit(express).forecast(1).mean[0], 0.0, None))
    else:  # quantile mode (original behaviour)
        nz = y[y > 0]
        large_thr = float(np.quantile(nz, cfg.large_quantile)) if nz.size else 0.0
        large_mask = y >= max(large_thr, 1e-9)
        p_week, p_h, exp_large, last_large = _large_from_series(
            np.where(large_mask, y, 0.0), model_name, params, h, week_index)
        bulk_share = float(y[large_mask].sum() / total_vol) if total_vol > 0 else 0.0
        capped = np.minimum(y, large_thr) if large_thr > 0 else y
        routine_weekly = float(np.clip(
            build_model(model_name, params).fit(capped).forecast(1).mean[0], 0.0, None))

    return SeriesForecast(
        weekly=weekly,
        total=float(weekly.sum()),
        p_occurrence=float(np.clip(res.p_occurrence, 0.0, 1.0)),
        large_threshold=large_thr,
        p_large_week=p_week,
        p_large_horizon=float(p_h),
        expected_large_size=exp_large,
        bulk_share=bulk_share,
        routine_weekly=routine_weekly,
        routine_total=routine_weekly * h,
        last_large_week=last_large,
    )
