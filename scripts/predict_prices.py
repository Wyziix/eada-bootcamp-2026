#!/usr/bin/env python3
"""Predict historical Ames house prices with the saved benchmark winner."""
import argparse
import json
from pathlib import Path

import joblib
import numpy as np

from train_models import ROOT, predict_quiet, read_prediction_input


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="CSV with the original Ames predictor columns")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model-dir", type=Path, default=ROOT / "models/ames")
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("Choose an output path different from the input CSV.")
    metadata = json.loads((args.model_dir / "model_metadata.json").read_text())
    raw, features = read_prediction_input(args.input, metadata)
    model = joblib.load(args.model_dir / "best_model.joblib")
    prediction = predict_quiet(model, features)
    if not np.isfinite(prediction).all() or (prediction < 0).any():
        raise ValueError("Model returned invalid predictions.")
    raw["predicted_sale_price_usd"] = prediction
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw.to_csv(args.output, index=False)
    print(f"Predicted {len(raw):,} properties with {metadata['selected_model']} → {args.output.resolve()}")


if __name__ == "__main__":
    main()
