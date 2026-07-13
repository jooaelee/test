"""End-to-end weekly pipeline.

    load -> classify & select targets -> tune (per series) -> forecast 4 weeks
         -> large/small decomposition -> registry update -> CSV + HTML report

Run once per week (see ``scripts/run_weekly.py``). Every step is deterministic
given the inputs and ``config.yaml``.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict
import time

import numpy as np
import pandas as pd

from .config import Config
from . import data_loader
from .classification import classify_series, select_targets
from .lifecycle import assess_lifecycle
from .tuning import tune_series
from .forecast import forecast_series
from .registry import Registry
from . import report as report_mod


# Forecasting grains. Each maps a name -> the grouping key(s) in the demand table.
GRAINS = {
    "sku": ["item_code"],
    "customer": ["customer"],
    "channel": ["channel"],
    "sku_customer": ["item_code", "customer"],
    "sku_channel": ["item_code", "channel"],
    "customer_channel": ["customer", "channel"],
}


@dataclass
class RunResult:
    forecasts: pd.DataFrame       # per target series, 4-week forecast + accuracy
    large_prob: pd.DataFrame      # 대량 출고 확률 (sku / customer / channel + crosses)
    small_forecast: pd.DataFrame  # 소량 출고 예측치 (per customer)
    classes: pd.DataFrame         # SKU labels & descriptors
    meta: dict


def _series_id(grain: str, key) -> str:
    if isinstance(key, tuple):
        key = "|".join(str(k) for k in key)
    return f"{grain}::{key}"


def _key_cols(grain: str, key):
    keys = GRAINS[grain]
    vals = key if isinstance(key, tuple) else (key,)
    return dict(zip(keys, vals))


def run(cfg: Config, base_dir: str = ".") -> RunResult:
    cfg = cfg.resolved(base_dir)
    t0 = time.time()
    wh = data_loader.load(cfg)
    run_date = str(wh.as_of.date())
    registry = Registry(cfg.registry_path)
    future_weeks = pd.date_range(wh.week_index[-1] + pd.Timedelta(days=7),
                                 periods=cfg.horizon_weeks, freq="7D")

    all_forecasts, all_large = [], []
    classes_frames = []
    n_target_total = 0

    # Channel split for the 대량/소량 definition: express couriers (DHL/FedEx/UPS)
    # are 소량; all other channels are 대량. Pre-split once, reuse per grain.
    demand_bulk = demand_express = None
    if cfg.split_mode == "channel":
        express_set = {c.upper() for c in cfg.express_channels}
        is_exp = wh.outbound["channel"].astype(str).str.upper().isin(express_set)
        demand_bulk = wh.outbound[~is_exp]
        demand_express = wh.outbound[is_exp]

    for grain, keys in GRAINS.items():
        series = {k: v for k, v in
                  data_loader.weekly_series(wh.outbound, keys, wh.week_index)}
        if not series:
            continue
        if cfg.split_mode == "channel":
            series_bulk = dict(data_loader.weekly_series(demand_bulk, keys, wh.week_index))
            series_express = dict(data_loader.weekly_series(demand_express, keys, wh.week_index))
        else:
            series_bulk = series_express = {}
        desc = classify_series(series, wh.week_index, cfg)
        desc = assess_lifecycle(desc, wh.week_index, cfg)
        desc = select_targets(desc, cfg)
        desc["grain"] = grain
        classes_frames.append(desc)

        targets = desc[desc["is_target"]]
        n_target_total += len(targets)
        for _, row in targets.iterrows():
            key = row["key"]
            y = series[key]
            sid = _series_id(grain, key)
            champ = registry.champion(sid)
            outcome = tune_series(y, row["label"], cfg, champion=champ)
            bulk_y = series_bulk.get(key) if cfg.split_mode == "channel" else None
            express_y = series_express.get(key) if cfg.split_mode == "channel" else None
            sf = forecast_series(y, outcome.model_name, outcome.params, cfg,
                                 week_index=wh.week_index,
                                 bulk_y=bulk_y, express_y=express_y)
            registry.update(sid, grain, row["label"], outcome.model_name,
                            outcome.params, outcome.score, run_date)
            improvement = registry.improvement(sid)

            base = {"grain": grain, "series_id": sid, **_key_cols(grain, key),
                    "label": row["label"], "sb_class": row["sb_class"],
                    "total_qty_hist": row["total_qty"],
                    "model": outcome.model_name, "model_params": str(outcome.params),
                    "rmsse": outcome.score.rmsse, "mase": outcome.score.mase,
                    "smape": outcome.score.smape, "n_trials": len(outcome.trials),
                    "n_backtest_folds": outcome.score.n_folds,
                    "acc_change_vs_prev": improvement}
            fc_row = dict(base)
            fc_row.update({
                "forecast_total_4w": sf.total,
                "p_occurrence_week": sf.p_occurrence,
                "routine_weekly": sf.routine_weekly,
                "routine_total_4w": sf.routine_total,
                "bulk_share": sf.bulk_share,
            })
            for i, wk in enumerate(future_weeks):
                fc_row[f"w{i+1}_{wk.date()}"] = sf.weekly[i]
            all_forecasts.append(fc_row)

            large_row = dict(base)
            large_row.update({
                "large_threshold": sf.large_threshold,
                "p_large_week": sf.p_large_week,
                "p_large_4w": sf.p_large_horizon,
                "expected_large_size": sf.expected_large_size,
                "bulk_share": sf.bulk_share,
                "last_large_week": (str(sf.last_large_week.date())
                                    if sf.last_large_week is not None else None),
            })
            all_large.append(large_row)

    forecasts = pd.DataFrame(all_forecasts)
    large_prob = pd.DataFrame(all_large)
    classes = pd.concat(classes_frames, ignore_index=True) if classes_frames \
        else pd.DataFrame()

    # SKU lifecycle summary (교체형 active vs end-of-life), for the report.
    lifecycle_summary = {"sku_replacement_total": 0, "sku_replacement_active": 0,
                         "sku_replacement_eol": 0}
    if not classes.empty:
        sku_desc = classes[classes["grain"] == "sku"]
        is_repl = sku_desc["label"] == "교체형"
        n_repl = int(is_repl.sum())
        n_active_repl = int((is_repl & sku_desc["is_active"]).sum())
        lifecycle_summary = {
            "sku_replacement_total": n_repl,
            "sku_replacement_active": n_active_repl,
            "sku_replacement_eol": n_repl - n_active_repl,
        }

    # 소량 출고 예측치: routine expectation, per customer.
    small = forecasts[forecasts["grain"] == "customer"].copy() \
        if not forecasts.empty else pd.DataFrame()
    if not small.empty:
        small = small[["customer", "label", "model", "routine_weekly",
                       "routine_total_4w", "forecast_total_4w",
                       "p_occurrence_week", "rmsse", "mase"]] \
            .sort_values("routine_total_4w", ascending=False).reset_index(drop=True)

    # Median RMSSE over "active" series only: many top-volume SKUs are recently
    # dormant, giving all-zero backtest windows (RMSSE 0) that would drag the
    # median to 0 and hide real accuracy. Restrict to series with signal.
    med_rmsse = None
    n_active = 0
    beats_naive = None
    if not forecasts.empty:
        finite = forecasts["rmsse"].replace([np.inf, -np.inf], np.nan).dropna()
        # Share of targets beating the naive (last-value) benchmark, RMSSE < 1 —
        # the honest headline for intermittent demand (point sMAPE saturates).
        beats_naive = float((finite < 1.0).mean()) if len(finite) else None
        active = finite[finite > 1e-9]
        n_active = int(len(active))
        med_rmsse = float(active.median()) if n_active else None
    # Previous run's median (last logged run, before we append this one).
    prev_runs = registry.data.get("runs", [])
    prev_median = prev_runs[-1].get("median_rmsse") if prev_runs else None

    # Express (소량) vs bulk (대량) volume/order shares, for report transparency.
    express_vol_share = express_cnt_share = None
    if cfg.split_mode == "channel" and demand_express is not None:
        tot = float(wh.outbound["qty"].sum())
        express_vol_share = float(demand_express["qty"].sum() / tot) if tot else 0.0
        express_cnt_share = (float(len(demand_express) / len(wh.outbound))
                             if len(wh.outbound) else 0.0)

    summary = {
        "n_targets": int(n_target_total),
        "n_sku_targets": int((forecasts["grain"] == "sku").sum()) if not forecasts.empty else 0,
        "median_rmsse": med_rmsse,
        "n_active_series": n_active,
        "beats_naive_share": beats_naive,
        "runtime_sec": round(time.time() - t0, 1),
        "horizon_weeks": cfg.horizon_weeks,
        "future_weeks": [str(w.date()) for w in future_weeks],
    }
    registry.log_run(run_date, summary)
    registry.save()

    meta = {"as_of": run_date, "data_start": str(wh.week_index[0].date()),
            "n_weeks": len(wh.week_index), "future_weeks": summary["future_weeks"],
            "prev_median_rmsse": prev_median,
            "split_mode": cfg.split_mode,
            "express_channels": list(cfg.express_channels),
            "express_vol_share": express_vol_share,
            "express_cnt_share": express_cnt_share,
            "eol_adi_multiplier": cfg.eol_adi_multiplier,
            "eol_min_grace_weeks": cfg.eol_min_grace_weeks,
            "eol_max_grace_weeks": cfg.eol_max_grace_weeks,
            **lifecycle_summary, **summary}

    result = RunResult(forecasts, large_prob, small, classes, meta)
    report_mod.write_outputs(result, cfg)
    return result
