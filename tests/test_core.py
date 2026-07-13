"""Sanity tests for the forecasting core: model correctness, metrics, tuning.

Run: ``python -m pytest tests/ -q``  (or ``python tests/test_core.py``).
"""
from __future__ import annotations

import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from demand_forecast.models.intermittent import Croston, SBA, TSB, _croston_smooth
from demand_forecast.models.timeseries import SES, MovingAverage
from demand_forecast.backtest import rolling_backtest, _naive_scale
from demand_forecast.classification import _adi_cv2, _sb_class, classify_series, select_targets
from demand_forecast.lifecycle import assess_lifecycle, eol_grace_weeks
from demand_forecast.config import Config


def test_croston_constant_interval():
    # Demand of 10 every 3rd week -> rate should approach 10/3.
    y = np.zeros(30)
    y[::3] = 10.0
    z, p = _croston_smooth(y, alpha=0.2)
    rate = z / p
    assert 2.5 < rate < 4.0, rate


def test_sba_below_croston():
    y = np.zeros(40); y[::4] = np.array([5, 7, 6, 8, 5, 9, 4, 6, 7, 5], float)
    cr = Croston(alpha=0.2).fit(y).forecast(4).mean[0]
    sba = SBA(alpha=0.2).fit(y).forecast(4).mean[0]
    assert sba < cr  # bias correction shrinks the estimate


def test_tsb_probability_bounds():
    y = np.zeros(50); y[::5] = 3.0
    res = TSB(alpha=0.1, beta=0.1).fit(y).forecast(4)
    assert 0.0 <= res.p_occurrence <= 1.0
    assert res.mean[0] >= 0.0


def test_zero_series_is_safe():
    y = np.zeros(20)
    for m in (Croston(alpha=0.1), SBA(alpha=0.1), TSB(alpha=0.1, beta=0.1),
              SES(), MovingAverage(window=4)):
        res = m.fit(y).forecast(4)
        assert np.all(res.mean == 0.0)
        assert 0.0 <= res.p_occurrence <= 1.0


def test_naive_scale_positive():
    assert _naive_scale(np.array([1.0, 1.0, 1.0])) == 1.0  # zero-var -> 1.0 guard
    assert _naive_scale(np.array([0.0, 5.0, 0.0, 5.0])) > 0


def test_backtest_runs():
    rng = np.random.default_rng(0)
    y = rng.poisson(2, size=60).astype(float)
    score = rolling_backtest(lambda: SBA(alpha=0.1), y, h=4, folds=6, min_train=20)
    assert score.n_folds > 0
    assert np.isfinite(score.rmsse)


def test_classification_labels():
    cfg = Config()
    # Regular weekly demand -> smooth / low ADI.
    y = np.full(52, 5.0)
    adi, cv2, n = _adi_cv2(y)
    assert adi < cfg.adi_cut
    assert _sb_class(adi, cv2, cfg) == "smooth"
    # Sparse -> intermittent quadrant.
    y2 = np.zeros(52); y2[::10] = 4.0
    adi2, cv2_2, _ = _adi_cv2(y2)
    assert adi2 >= cfg.adi_cut


def test_eol_grace_weeks_clamped():
    cfg = Config()
    # A very frequent reorder pattern (adi=1) shouldn't get a tiny grace window.
    assert eol_grace_weeks(1.0, cfg) == cfg.eol_min_grace_weeks
    # A very sparse pattern (adi=100) shouldn't get an unbounded grace window.
    assert eol_grace_weeks(100.0, cfg) == cfg.eol_max_grace_weeks
    # A mid-range pattern should scale with adi * multiplier.
    assert eol_grace_weeks(10.0, cfg) == 10.0 * cfg.eol_adi_multiplier
    # Non-finite (never shipped) falls back to the floor.
    assert eol_grace_weeks(np.inf, cfg) == cfg.eol_min_grace_weeks


def test_lifecycle_continuous_always_active():
    cfg = Config()
    week_index = pd.date_range("2024-01-07", periods=52, freq="7D")
    y = np.full(52, 5.0)
    desc = classify_series({"SKU_CONT": y}, week_index, cfg)
    desc = assess_lifecycle(desc, week_index, cfg)
    row = desc.iloc[0]
    assert row["label"] == "지속형"
    assert row["is_active"] == True  # noqa: E712 (numpy bool)


def test_lifecycle_flags_stale_replacement_sku_eol():
    cfg = Config()
    week_index = pd.date_range("2024-01-07", periods=104, freq="7D")
    # Ships every ~4 weeks, but nothing at all in the last 60+ weeks -> EOL.
    y = np.zeros(104)
    y[4:40:4] = 3.0
    desc = classify_series({"SKU_DEAD": y}, week_index, cfg)
    desc = assess_lifecycle(desc, week_index, cfg)
    row = desc.iloc[0]
    assert row["label"] == "교체형"
    assert row["is_active"] == False  # noqa: E712


def test_lifecycle_keeps_recent_replacement_sku_active():
    cfg = Config()
    week_index = pd.date_range("2024-01-07", periods=52, freq="7D")
    # Ships every ~4 weeks throughout, including recently -> still active.
    y = np.zeros(52)
    y[4::4] = 3.0
    desc = classify_series({"SKU_ALIVE": y}, week_index, cfg)
    desc = assess_lifecycle(desc, week_index, cfg)
    row = desc.iloc[0]
    assert row["label"] == "교체형"
    assert row["is_active"] == True  # noqa: E712


def test_select_targets_continuous_uncapped_replacement_active_and_top_volume():
    cfg = Config(target_volume_quantile=0.5, min_active_weeks=2)
    week_index = pd.date_range("2024-01-07", periods=52, freq="7D")

    series = {}
    # 지속형, low volume -> must still be a target (no volume cut for 지속형).
    series["CONT_LOW"] = np.full(52, 1.0)
    # 교체형, active (recent orders), high volume -> should be a target.
    y_active_hi = np.zeros(52); y_active_hi[::4] = 500.0
    series["REPL_ACTIVE_HI"] = y_active_hi
    # 교체형, active, low volume -> likely excluded by the volume cut among actives.
    y_active_lo = np.zeros(52); y_active_lo[::4] = 1.0
    series["REPL_ACTIVE_LO"] = y_active_lo
    # 교체형, EOL (quiet for a very long time despite a frequent historical
    # cadence) and high historical volume -> must be excluded despite volume.
    y_eol = np.zeros(52); y_eol[2:10:2] = 1000.0
    series["REPL_EOL_HI"] = y_eol

    desc = classify_series(series, week_index, cfg)
    desc = assess_lifecycle(desc, week_index, cfg)
    desc = select_targets(desc, cfg)
    by_key = desc.set_index("key")["is_target"].to_dict()

    assert by_key["CONT_LOW"] == True  # noqa: E712
    assert by_key["REPL_ACTIVE_HI"] == True  # noqa: E712
    assert by_key["REPL_EOL_HI"] == False  # noqa: E712 -- EOL excludes despite volume


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
