#!/usr/bin/env python3
"""Weekly entry point for the warehouse demand-forecasting pipeline.

Examples
--------
    # Use config.yaml next to the repo root, data in ./data
    python scripts/run_weekly.py --config config.yaml --data-dir /path/to/data

    # Point directly at the raw files and pin the as-of date
    python scripts/run_weekly.py \
        --inbound  ESSEN_HK_Inbound.csv \
        --outbound ESSEN_HK_Outbound.csv \
        --as-of 2026-06-11 --data-dir /workspace/test

Schedule it once a week (cron): ``0 6 * * 1  cd /repo && python scripts/run_weekly.py``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as a script without installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demand_forecast.config import load_config
from demand_forecast.pipeline import run


def main(argv=None):
    p = argparse.ArgumentParser(description="Weekly warehouse demand forecast")
    p.add_argument("--config", default=None, help="Path to config.yaml")
    p.add_argument("--data-dir", default=".", help="Base dir for relative data paths")
    p.add_argument("--inbound", default=None)
    p.add_argument("--outbound", default=None)
    p.add_argument("--inventory", default=None)
    p.add_argument("--as-of", default=None, help="YYYY-MM-DD (default: latest in data)")
    p.add_argument("--output-dir", default=None)
    args = p.parse_args(argv)

    cfg = load_config(
        args.config,
        inbound_path=args.inbound,
        outbound_path=args.outbound,
        inventory_path=args.inventory,
        as_of=args.as_of,
        output_dir=args.output_dir,
    )
    if args.output_dir:
        cfg.registry_path = str(Path(args.output_dir) / "registry.json")
        cfg.report_html = str(Path(args.output_dir) / "report.html")

    result = run(cfg, base_dir=args.data_dir)
    m = result.meta
    print(f"[OK] as_of={m['as_of']}  targets={m['n_targets']}  "
          f"sku_targets={m['n_sku_targets']}  runtime={m['runtime_sec']}s")
    print(f"     outputs -> {cfg.output_dir}/  (report: {cfg.report_html})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
