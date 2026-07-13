"""SKU lifecycle status: still active vs end-of-life (EOL).

교체형 (replacement-type) SKUs eventually get discontinued or superseded by a
new part number. Once that happens, its demand truly is zero going forward —
forecasting it is not "hard", it's meaningless. This module flags each series
as **active** (수명이 다하지 않음 — still plausibly due for another order) or
**end-of-life** (단종/수명 종료), using only its own shipment history: how long
it has been quiet, relative to how long it has *historically* gone quiet
between orders (ADI).

A series goes end-of-life once its silence exceeds a grace period of
``adi * eol_adi_multiplier`` weeks, floored/capped to
``[eol_min_grace_weeks, eol_max_grace_weeks]`` so that neither a very frequent
nor a very sparse reorder pattern produces a degenerate grace window.

지속형 (continuous) series are always treated as active — regular, ongoing
demand does not "expire" the way a discontinued part number does.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Config


def eol_grace_weeks(adi: float, cfg: Config) -> float:
    """Weeks of silence a series may go before being presumed end-of-life."""
    if not np.isfinite(adi):
        return float(cfg.eol_min_grace_weeks)
    return float(np.clip(adi * cfg.eol_adi_multiplier,
                         cfg.eol_min_grace_weeks, cfg.eol_max_grace_weeks))


def assess_lifecycle(desc: pd.DataFrame, week_index, cfg: Config) -> pd.DataFrame:
    """Add ``recency_weeks``, ``eol_grace_weeks``, ``is_active`` to a
    classification frame produced by :func:`classification.classify_series`
    (must already have ``adi``, ``label``, ``last_ship_week``).
    """
    desc = desc.copy()
    if desc.empty:
        for col in ("recency_weeks", "eol_grace_weeks", "is_active"):
            desc[col] = []
        return desc

    as_of = week_index[-1]

    def _recency(last_ship):
        if pd.isna(last_ship):
            return np.inf
        return float((as_of - last_ship).days) / 7.0

    desc["recency_weeks"] = desc["last_ship_week"].apply(_recency)
    desc["eol_grace_weeks"] = desc["adi"].apply(lambda a: eol_grace_weeks(a, cfg))
    desc["is_active"] = np.where(
        desc["label"] == "지속형",
        True,
        desc["recency_weeks"] <= desc["eol_grace_weeks"],
    )
    return desc
