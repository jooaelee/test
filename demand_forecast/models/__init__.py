"""Forecasting models for warehouse demand.

Two families, matching the two SKU labels:

* 교체형 (intermittent / replacement)  -> :mod:`intermittent` : Croston, SBA, TSB
* 지속형 (continuous)                   -> :mod:`timeseries`   : SES, Holt, MA, seasonal-naive

Every model exposes the same tiny interface via :class:`base.Forecaster`:
``fit(y)`` then ``forecast(h)`` returning a length-``h`` vector of expected
weekly demand.
"""
from .base import Forecaster, ForecastResult
from .intermittent import Croston, SBA, TSB
from .timeseries import SES, Holt, MovingAverage, SeasonalNaive
from .factory import candidate_models, build_model

__all__ = [
    "Forecaster", "ForecastResult",
    "Croston", "SBA", "TSB",
    "SES", "Holt", "MovingAverage", "SeasonalNaive",
    "candidate_models", "build_model",
]
