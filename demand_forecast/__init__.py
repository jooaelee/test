"""Warehouse demand-forecasting pipeline.

A weekly, re-runnable pipeline that turns raw inbound/outbound warehouse data
into customer-facing demand forecasts for the shipper (화주):

    1. load & clean inputs (inbound / outbound / inventory)
    2. label each SKU 교체형(intermittent) / 지속형(continuous) and select the
       top-20%-by-volume forecast targets
    3. forecast the next 4 weeks — Croston/SBA/TSB for 교체형, SES/Holt/MA for
       지속형 — choosing the best model per series by rolling-origin backtest
       (~10 trials each)
    4. persist a model registry so accuracy improves as new data arrives (고도화)
    5. emit a report: large-shipment probability (SKU/customer/channel) and
       small-volume forecast (per customer), as CSVs + an HTML dashboard.

Entry point: :func:`demand_forecast.pipeline.run`.
"""
from .config import Config, load_config

__all__ = ["Config", "load_config"]
__version__ = "0.1.0"
