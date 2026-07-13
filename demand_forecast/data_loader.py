"""Load and normalise the raw warehouse files into tidy weekly demand series.

The raw ESSENCORE exports are CP949-encoded CSVs with trailing whitespace in
headers and numeric cells, and ``YYYYMMDD`` integer dates. This module hides all
of that and produces clean long-format tables plus weekly-aggregated series for
each forecasting grain (SKU, customer, channel, and their crosses).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import warnings

import numpy as np
import pandas as pd

from .config import Config


# Canonical column names we rely on downstream, mapped from the raw headers.
_OUT_RENAME = {
    "Center Code": "center_code",
    "Center": "center",
    "Shipper": "shipper",
    "Shipper Name": "shipper_name",
    "Customer": "customer",
    "Company": "company",
    "Order No.": "order_no",
    "Out Type": "out_type",
    "Order Data": "order_date",
    "Out Date": "date",
    "Item Code": "item_code",
    "Item": "item",
    "Item Group": "item_group",
    "Item GR Name": "item_group_name",
    "DCM_NM": "channel",
    "Quantity": "qty",
    "Quantity Unit": "qty_unit",
    "Package Qty": "pkg_qty",
    "Package Qty Unit": "pkg_qty_unit",
}

_IN_RENAME = {
    "Center Code": "center_code",
    "Center": "center",
    "Shipper": "shipper",
    "Shipper Name": "shipper_name",
    "Manufacturer": "manufacturer",
    "Order No.": "order_no",
    "Inbound Type": "in_type",
    "Order Date": "order_date",
    "Inbound Date": "date",
    "Item Code": "item_code",
    "Item": "item",
    "Item Group Code": "item_group_code",
    "Item Group CD Name": "item_group_name",
    "Quantity": "qty",
    "Quantity Unit": "qty_unit",
    "Package Qty": "pkg_qty",
    "Package Qty Unit": "pkg_qty_unit",
}


@dataclass
class WarehouseData:
    """Container for the cleaned inputs and the run's derived time axis."""
    outbound: pd.DataFrame          # cleaned Sales demand rows
    inbound: pd.DataFrame           # cleaned inbound rows
    inventory: pd.DataFrame         # weekly SKU inventory (derived or supplied)
    as_of: pd.Timestamp             # last day included in training
    week_index: pd.DatetimeIndex    # full weekly axis up to as_of


def _strip_cols(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [c.strip() for c in df.columns]
    return df


def _to_num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.strip(), errors="coerce")


def _to_date(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s.astype(str).str.strip(), format="%Y%m%d", errors="coerce")


def _clean_str(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip()


def week_start(dates: pd.Series, anchor: str) -> pd.Series:
    """Map dates to the start-of-week timestamp for the given anchor."""
    return dates.dt.to_period(anchor).apply(lambda p: p.start_time)


def _read_csv(path: str, encoding: str) -> pd.DataFrame:
    """Read a CSV, trying the configured encoding then common fallbacks.

    Uploaded files may be CP949 (the source export), UTF-8, or Latin-1; try them
    in turn so the UI works regardless of how the user saved the file.
    """
    tried = []
    for enc in [encoding, "cp949", "utf-8-sig", "utf-8", "latin1"]:
        if enc in tried:
            continue
        tried.append(enc)
        try:
            return pd.read_csv(path, encoding=enc)
        except (UnicodeDecodeError, LookupError):
            continue
    # Last resort: replace undecodable bytes so we never hard-fail on encoding.
    return pd.read_csv(path, encoding="latin1", encoding_errors="replace")


def load(cfg: Config) -> WarehouseData:
    """Read, clean and weekly-index the inputs described by ``cfg``."""
    raw_out = _strip_cols(_read_csv(cfg.outbound_path, cfg.encoding))
    raw_in = _strip_cols(_read_csv(cfg.inbound_path, cfg.encoding))

    out = raw_out.rename(columns=_OUT_RENAME)
    inb = raw_in.rename(columns=_IN_RENAME)

    for df in (out, inb):
        df["date"] = _to_date(df["date"])
        df["qty"] = _to_num(df["qty"])
        for col in ("item_code", "item_group"):
            if col in df:
                df[col] = _clean_str(df[col])
    for col in ("customer", "company", "channel", "out_type"):
        if col in out:
            out[col] = _clean_str(out[col])
    if "in_type" in inb:
        inb["in_type"] = _clean_str(inb["in_type"])

    # Drop unusable rows.
    out = out.dropna(subset=["date", "qty"])
    out = out[out["qty"] > 0]
    inb = inb.dropna(subset=["date", "qty"])
    inb = inb[inb["qty"] > 0]

    # As-of cutoff.
    data_max = out["date"].max()
    as_of = pd.Timestamp(cfg.as_of) if cfg.as_of else data_max
    out = out[out["date"] <= as_of]
    inb = inb[inb["date"] <= as_of]

    # Keep only genuine customer demand for forecasting (Sales, ...).
    demand = out[out["out_type"].isin(cfg.demand_out_types)].copy()

    # Weekly axis.
    demand["week"] = week_start(demand["date"], cfg.week_anchor)
    inb["week"] = week_start(inb["date"], cfg.week_anchor)
    out["week"] = week_start(out["date"], cfg.week_anchor)
    last_week = week_start(pd.Series([as_of]), cfg.week_anchor).iloc[0]
    first_week = min(demand["week"].min(), inb["week"].min())
    week_index = pd.date_range(first_week, last_week, freq="7D")

    inventory = _build_inventory(cfg, inb, out, week_index)

    return WarehouseData(
        outbound=demand,
        inbound=inb,
        inventory=inventory,
        as_of=pd.Timestamp(as_of),
        week_index=week_index,
    )


def _build_inventory(cfg, inb, out, week_index) -> pd.DataFrame:
    """Return weekly closing inventory per SKU.

    Uses a supplied inventory file when given, otherwise reconstructs a running
    balance from cumulative inbound minus *all* outbound (any out type consumes
    stock). The reconstruction is a signal, not an audited ledger.
    """
    if cfg.inventory_path and Path(cfg.inventory_path).exists():
        inv = _strip_cols(_read_csv(cfg.inventory_path, cfg.encoding))
        inv.columns = [c.lower().strip() for c in inv.columns]
        return inv

    in_wk = inb.groupby(["item_code", "week"])["qty"].sum().rename("in_qty")
    out_wk = out.groupby(["item_code", "week"])["qty"].sum().rename("out_qty")
    flows = pd.concat([in_wk, out_wk], axis=1).fillna(0.0)
    flows["net"] = flows["in_qty"] - flows["out_qty"]
    # Cumulative balance per SKU across the weekly axis.
    frames = []
    for sku, g in flows.groupby(level=0):
        s = g.droplevel(0).reindex(week_index, fill_value=0.0)
        bal = s["net"].cumsum().clip(lower=0)
        frames.append(pd.DataFrame({"item_code": sku, "week": week_index,
                                    "closing_inventory": bal.values}))
    if not frames:
        return pd.DataFrame(columns=["item_code", "week", "closing_inventory"])
    return pd.concat(frames, ignore_index=True)


def weekly_series(demand: pd.DataFrame, keys, week_index: pd.DatetimeIndex):
    """Yield ``(key, np.ndarray)`` weekly demand vectors for each group.

    The vector is aligned to ``week_index`` (zeros for weeks with no shipment),
    which is what the intermittent-demand models expect.
    """
    grouped = demand.groupby(keys + ["week"])["qty"].sum()
    key_level = keys if isinstance(keys, list) else [keys]
    for key, g in grouped.groupby(level=list(range(len(key_level)))):
        s = g.droplevel(list(range(len(key_level))))
        vec = s.reindex(week_index, fill_value=0.0).to_numpy(dtype=float)
        yield key, vec
