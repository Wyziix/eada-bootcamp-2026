"""Published Ames market-index lookups. No guessed or interpolated periods."""
from pathlib import Path
import hashlib
import json
import re

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "dat/market/ames_hpi.csv"
REFERENCE_PERIOD = "2010Q2"
TARGET_PERIOD = "2026Q2"
MARKET_DIR = ROOT / "models/ames_market"


def load_index():
    source = json.loads(INDEX_PATH.with_name("source.json").read_text())
    if hashlib.sha256(INDEX_PATH.read_bytes()).hexdigest() != source["snapshot_sha256"]:
        raise ValueError("Market-index CSV differs from its recorded source snapshot.")
    frame = pd.read_csv(INDEX_PATH)
    if frame["period"].duplicated().any() or not frame["period"].str.fullmatch(r"\d{4}Q[1-4]").all():
        raise ValueError("Market-index periods must be unique calendar quarters.")
    if not np.isfinite(frame["index"]).all() or (frame["index"] <= 0).any():
        raise ValueError("Market-index observations must be positive and finite.")
    return dict(zip(frame["period"], frame["index"])), source


def index_value(index, period):
    if not re.fullmatch(r"\d{4}Q[1-4]", period) or period not in index:
        raise ValueError(f"No published index for {period}; latest snapshot period is {max(index)}.")
    return float(index[period])


def sale_indices(frame, index):
    years = pd.to_numeric(frame["Yr Sold"], errors="raise").to_numpy(dtype=float)
    months = pd.to_numeric(frame["Mo Sold"], errors="raise").to_numpy(dtype=float)
    if not (np.isfinite(years).all() and np.isfinite(months).all()
            and np.equal(years, np.floor(years)).all()
            and np.equal(months, np.floor(months)).all()
            and ((months >= 1) & (months <= 12)).all()):
        raise ValueError("Sale years and months must be valid whole calendar values.")
    return np.array([index_value(index, f"{int(y)}Q{(int(m)-1)//3+1}") for y, m in zip(years, months)])


def adjust_reference_price(values, index, reference_period=REFERENCE_PERIOD, target_period=TARGET_PERIOD):
    values = np.asarray(values, dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("Reference prices must be finite and nonnegative.")
    return values * index_value(index, target_period) / index_value(index, reference_period)


def report_context():
    path = MARKET_DIR / "model_metadata.json"
    if not path.exists():
        return None
    metadata = json.loads(path.read_text())
    index, source = load_index()
    if source["snapshot_sha256"] != metadata["index_source"]["snapshot_sha256"]:
        raise ValueError("Rebuild the market model after changing its index snapshot.")
    examples = pd.read_csv(MARKET_DIR / "example_predictions.csv").to_dict("records")
    metadata.update({"examples": examples, "scenarios_csv": (MARKET_DIR / "market_scenarios.csv").read_text(),
        "index_history": [{"period": p, "index": v} for p, v in index.items() if p >= "2006Q1"],
        "illustration_price": float(adjust_reference_price([200000], index)[0])})
    return metadata
