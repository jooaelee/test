"""Per-series model selection: the ~10-trial accuracy-improvement loop.

For each target series we backtest up to ``max_trials`` candidate configurations
(the "예측시 10회 정도 수행"), record every trial's accuracy, and keep the best.
A registry champion (from a previous run) is included as an extra challenger so
the model only changes when a new config beats it by a margin — giving stable,
monotonically-improving "고도화" as fresh data arrives.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List
import numpy as np

from .config import Config
from .models import candidate_models, build_model
from .backtest import rolling_backtest, BacktestScore


@dataclass
class TuningOutcome:
    model_name: str
    params: dict
    score: BacktestScore
    trials: List[dict] = field(default_factory=list)
    from_champion: bool = False


def tune_series(y: np.ndarray, label: str, cfg: Config,
                champion: Optional[dict] = None) -> TuningOutcome:
    """Search candidate models for ``y`` and return the best configuration."""
    y = np.asarray(y, float)
    min_train = max(cfg.min_history_weeks, len(y) - cfg.horizon_weeks - cfg.backtest_folds)
    min_train = max(cfg.min_history_weeks, min(min_train, len(y) - cfg.horizon_weeks))

    trials, best = [], None
    candidates = candidate_models(label, cfg.max_trials)

    # Fold the previous champion in as an extra challenger.
    champion_spec = None
    if champion and champion.get("model_name"):
        champion_spec = (champion["model_name"], champion.get("params", {}))

    def eval_model(model, is_champ=False):
        score = rolling_backtest(lambda m=model: _fresh(m), y,
                                 cfg.horizon_weeks, cfg.backtest_folds, min_train)
        rec = {"model": model.label(), "name": model.name, "params": dict(model.params),
               "rmsse": score.rmsse, "mase": score.mase, "smape": score.smape,
               "bias": score.bias, "champion": is_champ}
        trials.append(rec)
        return score

    for m in candidates:
        s = eval_model(m)
        cand = TuningOutcome(m.name, dict(m.params), s, from_champion=False)
        if best is None or _better(cand.score, best.score):
            best = cand

    # Champion challenge: only replace it if a challenger wins by the margin.
    if champion_spec is not None:
        try:
            cm = build_model(champion_spec[0], champion_spec[1])
            cs = eval_model(cm, is_champ=True)
            champ_out = TuningOutcome(cm.name, dict(cm.params), cs,
                                      from_champion=True)
            # Keep champion unless the best challenger improves RMSSE by margin.
            if np.isfinite(cs.rmsse):
                if not (best is not None and best.score.rmsse
                        <= cs.rmsse * (1 - cfg.champion_margin)):
                    best = champ_out
        except Exception:
            pass

    if best is None:
        best = TuningOutcome("sba", {"alpha": 0.1},
                             BacktestScore(np.inf, np.inf, np.inf, 0.0, 0))
    best.trials = trials
    return best


def _fresh(model):
    """Return a new, unfitted instance mirroring ``model``'s class + params."""
    return model.__class__(**model.params)


def _better(a: BacktestScore, b: BacktestScore) -> bool:
    """Lower RMSSE wins; fall back to MASE when RMSSE ties/non-finite."""
    if not np.isfinite(b.rmsse):
        return np.isfinite(a.rmsse)
    if not np.isfinite(a.rmsse):
        return False
    if abs(a.rmsse - b.rmsse) > 1e-9:
        return a.rmsse < b.rmsse
    return a.mase < b.mase
