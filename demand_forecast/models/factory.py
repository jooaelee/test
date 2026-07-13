"""Build the candidate model set for a series given its label.

The tuner evaluates up to ``max_trials`` (~10) of these per series and keeps the
best by backtest — this is the "정확도를 평가하고 모델 피처를 조정" search. The
"features" being adjusted are each model's smoothing/window/trend knobs.
"""
from __future__ import annotations

from typing import List

from .base import Forecaster
from .intermittent import Croston, SBA, TSB
from .timeseries import SES, Holt, MovingAverage, SeasonalNaive


# Candidate configs for 교체형 (intermittent) — strictly the Croston family, per
# the design spec ("교체형은 Croston SBA"). SBA first: the recommended default.
# The ~10 trials explore the smoothing "features" (alpha/beta) and the variant.
_INTERMITTENT = [
    (SBA, {"alpha": 0.1}),
    (SBA, {"alpha": 0.15}),
    (SBA, {"alpha": 0.2}),
    (SBA, {"alpha": 0.05}),
    (SBA, {"alpha": 0.3}),
    (TSB, {"alpha": 0.1, "beta": 0.1}),
    (TSB, {"alpha": 0.2, "beta": 0.05}),
    (TSB, {"alpha": 0.1, "beta": 0.2}),
    (Croston, {"alpha": 0.1}),
    (Croston, {"alpha": 0.2}),
]

# Candidate configs for 지속형 (continuous) — strictly time-series models.
_CONTINUOUS = [
    (SES, {"alpha": None}),        # optimised SES
    (Holt, {"damped": True}),
    (Holt, {"damped": False}),
    (SES, {"alpha": 0.3}),
    (SES, {"alpha": 0.1}),
    (MovingAverage, {"window": 4}),
    (MovingAverage, {"window": 8}),
    (MovingAverage, {"window": 13}),
    (SeasonalNaive, {"season": 52}),
    (MovingAverage, {"window": 26}),
]

_REGISTRY = {c.name: c for c in
             (Croston, SBA, TSB, SES, Holt, MovingAverage, SeasonalNaive)}


def candidate_models(label: str, max_trials: int = 10) -> List[Forecaster]:
    specs = _INTERMITTENT if label == "교체형" else _CONTINUOUS
    return [cls(**params) for cls, params in specs[:max_trials]]


def build_model(name: str, params: dict) -> Forecaster:
    """Rebuild a model from a registry entry (name + params)."""
    cls = _REGISTRY[name]
    return cls(**params)
