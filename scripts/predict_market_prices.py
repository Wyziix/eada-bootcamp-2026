#!/usr/bin/env python3
"""Apply the reference-price model and a published Ames market-index quarter."""
import argparse
import json
from pathlib import Path

import joblib

from market_adjustment import MARKET_DIR, TARGET_PERIOD, load_index, adjust_reference_price
from train_models import read_prediction_input, predict_quiet


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-period", default=TARGET_PERIOD, help="Published quarter, e.g. 2026Q2")
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("Choose a separate output file.")
    metadata = json.loads((MARKET_DIR / "model_metadata.json").read_text())
    index, source = load_index()
    if source["snapshot_sha256"] != metadata["index_source"]["snapshot_sha256"]:
        raise ValueError("Market model and index snapshot must match; rebuild the market model.")
    raw, frame = read_prediction_input(args.input, metadata)
    prediction = predict_quiet(joblib.load(MARKET_DIR / "best_model.joblib"), frame)
    raw["reference_price_2010_q2_usd"] = prediction
    raw["market_adjusted_estimate_usd"] = adjust_reference_price(prediction, index, metadata["reference_period"], args.target_period)
    raw["estimate_period"] = args.target_period
    raw["accuracy_2026_measured"] = False
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw.to_csv(args.output, index=False)
    print(f"Wrote {len(raw)} market-adjusted scenarios for {args.target_period}: {args.output.resolve()}")


if __name__ == "__main__":
    main()
