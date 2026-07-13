"""Configuration for the warehouse demand-forecasting pipeline.

All tunable knobs live here so a weekly run is fully reproducible. Values can be
overridden from a YAML file (see ``config.yaml``) via :func:`load_config`.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
import copy


@dataclass
class Config:
    # ------------------------------------------------------------------ inputs
    # Paths to the raw warehouse files. The pipeline needs inbound + outbound;
    # an explicit inventory (재고현황) file is optional — if absent it is derived
    # from the running balance of inbound minus outbound per SKU.
    inbound_path: str = "ESSEN_HK_Inbound.csv"
    outbound_path: str = "ESSEN_HK_Outbound.csv"
    inventory_path: Optional[str] = None
    encoding: str = "cp949"  # source files are CP949 (Korean) encoded

    # As-of date for the run. ``None`` means "use the latest date in the data".
    # A weekly cron passes today's date; forecasts start the following week.
    as_of: Optional[str] = None  # "YYYY-MM-DD"

    # -------------------------------------------------------------- aggregation
    week_anchor: str = "W-SUN"      # ISO-style weeks ending Sunday
    horizon_weeks: int = 4          # forecast the next 4 weeks
    # Only these outbound types represent genuine customer demand.
    demand_out_types: tuple = ("Sales",)

    # ---------------------------------------------------------- target selection
    # Forecast the volume drivers only: the top X% of SKUs / customers by volume.
    target_volume_quantile: float = 0.80   # top 20%
    min_history_weeks: int = 8             # need at least this much history
    min_active_weeks: int = 2             # and at least this many weeks with demand

    # ------------------------------------------------------ demand classification
    # Syntetos-Boylan cut points on the weekly series.
    adi_cut: float = 1.32     # ADI >= cut -> intermittent (교체형)
    cv2_cut: float = 0.49     # CV^2 threshold (lumpy vs intermittent)
    # A series is "지속형" (continuous) only if it is regular AND recently active.
    continuous_recent_activity: float = 0.40  # active in >=40% of recent weeks
    recent_window_weeks: int = 52

    # ---------------------------------------------------- lifecycle (EOL) status
    # A 교체형 (intermittent) series is presumed "end-of-life" (수명이 다함) once
    # it has gone quiet for longer than its own historical reorder cadence would
    # suggest is normal. Grace period = adi * eol_adi_multiplier, clamped to
    # [eol_min_grace_weeks, eol_max_grace_weeks]. 지속형 series are always
    # considered active (continuous demand doesn't "expire" the same way).
    eol_adi_multiplier: float = 3.0
    eol_min_grace_weeks: int = 12
    eol_max_grace_weeks: int = 52

    # --------------------------------------------------------------- large/small
    # How to split 대량(large) vs 소량(small) shipments:
    #   "channel"  -> by outbound channel: express couriers (DHL/FedEx/UPS) are
    #                 소량(small parcels); every other channel (freight, pickup)
    #                 is 대량(large). Operational default — express is ~0.3% of
    #                 volume but ~37% of orders, clearly the small-parcel stream.
    #   "quantile" -> relative per-series magnitude: a weekly shipment is 대량 if
    #                 at/above ``large_quantile`` of that series' own history.
    split_mode: str = "channel"
    express_channels: tuple = ("DHL", "FEDEX", "UPS")  # 특송 = 소량
    large_quantile: float = 0.80  # used only when split_mode == "quantile"

    # ---------------------------------------------------------------- backtesting
    backtest_folds: int = 6         # rolling-origin folds
    max_trials: int = 10            # candidate configs evaluated per series (~10회)
    champion_margin: float = 0.02   # a challenger must beat champion by >=2% to win

    # ------------------------------------------------------------------- outputs
    output_dir: str = "outputs"
    registry_path: str = "outputs/registry.json"
    report_html: str = "outputs/report.html"

    def resolved(self, base: Optional[str] = None) -> "Config":
        """Return a copy with relative paths resolved against ``base`` dir."""
        c = copy.deepcopy(self)
        if base:
            b = Path(base)
            for attr in ("inbound_path", "outbound_path", "inventory_path"):
                v = getattr(c, attr)
                if v and not Path(v).is_absolute():
                    setattr(c, attr, str(b / v))
        return c

    def to_dict(self) -> dict:
        return asdict(self)


def load_config(path: Optional[str] = None, **overrides) -> Config:
    """Build a :class:`Config`, optionally layering a YAML file then kwargs."""
    cfg = Config()
    if path and Path(path).exists():
        import yaml  # pyyaml is a declared dependency
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        for k, v in data.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
    for k, v in overrides.items():
        if v is not None and hasattr(cfg, k):
            setattr(cfg, k, v)
    return cfg
