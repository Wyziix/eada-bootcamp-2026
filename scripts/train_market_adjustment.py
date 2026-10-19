#!/usr/bin/env python3
"""Fit the compact selected architecture to index-normalized historical prices.

Exports a separate 2010Q2 reference model and published-index 2026Q2 scenarios.
No contemporary property-level accuracy is claimed. Original model is preserved.
"""
import hashlib
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from threadpoolctl import threadpool_limits

from eda import load_data, read_dictionary
from export_portal_model import adapt, clean, export_hist_model
from market_adjustment import (ROOT, MARKET_DIR, REFERENCE_PERIOD, TARGET_PERIOD,
    load_index, index_value, sale_indices, adjust_reference_price)
from train_models import make_models, metrics, fit_record, predict_quiet, render_saved_report


def main():
    start = time.perf_counter()
    index, source = load_index()
    reference = index_value(index, REFERENCE_PERIOD)
    target = index_value(index, TARGET_PERIOD)
    original = json.loads((ROOT / "models/ames/model_metadata.json").read_text())
    input_path = ROOT / "dat/ames/ames_housing.csv"
    if hashlib.sha256(input_path.read_bytes()).hexdigest() != original["input_sha256"]:
        raise ValueError("Historical model metadata belongs to a different input dataset.")
    _, data = load_data(input_path, read_dictionary(ROOT / "dat/ames/data_description.txt"))
    features = [c for c in original["feature_columns"] if c not in {"Yr Sold", "Mo Sold"}]
    numeric = [c for c in original["numeric_columns"] if c in features]
    categorical = [c for c in features if c not in numeric]
    X = data[features]
    observed_index = sale_indices(data, index)
    # Every label is put in the same market period before learning. Calendar
    # variables are removed, so inference never extrapolates a tree to year 2026.
    y_reference = data.SalePrice.to_numpy() * reference / observed_index
    train = data["Yr Sold"].lt(2010).to_numpy()
    test = data["Yr Sold"].eq(2010).to_numpy()
    name = original["selected_model"]
    if name != "Histogram gradient boosting":
        raise ValueError("The browser exporter currently supports the selected histogram boosting architecture only.")
    model = clone(make_models(numeric, categorical)[name])
    duration, notices = fit_record(model, X.loc[train], y_reference[train])
    test_reference = predict_quiet(model, X.loc[test])
    test_nominal = test_reference * observed_index[test] / reference
    full_metrics = metrics(data.loc[test, "SalePrice"], test_nominal)

    # Score the actual simplified UI separately, keeping the same adapter and
    # representative properties as the historical UI for a consistent experience.
    config = json.loads((ROOT / "portal/public/assets/config.json").read_text())
    fixtures = json.loads((ROOT / "portal/tests/fixtures.json").read_text())
    forms = fixtures["forms"]
    simplified_features = pd.DataFrame([adapt(f, config["profiles"]) for f in forms])[features]
    for column in numeric:
        simplified_features[column] = pd.to_numeric(simplified_features[column])
    simplified_reference = predict_quiet(model, simplified_features)
    supported = test & data["Bldg Type"].isin(["1Fam", "Twnhs", "TwnhsE"]).to_numpy()
    if len(forms) != int(supported.sum()):
        raise ValueError("Portal fixtures must be rebuilt with export_portal_model.py.")
    # Assert source order and supplied input identity before pairing with prices.
    for form, (_, row) in zip(forms, data.loc[supported].iterrows()):
        if form["area"] != row["Gr Liv Area"] or form["neighborhood"] != row["Neighborhood"] or form["year"] != row["Year Built"]:
            raise ValueError("Portal fixture order differs from the source sales.")
    simplified_nominal = simplified_reference * observed_index[supported] / reference
    simplified_metrics = {"n": len(forms), "test_year": 2010,
        **metrics(data.loc[supported, "SalePrice"], simplified_nominal)}

    MARKET_DIR.mkdir(parents=True, exist_ok=True)
    saved = MARKET_DIR / "best_model.joblib"
    joblib.dump(model, saved, compress=3)
    metadata = {"selected_model": name, "feature_columns": features, "numeric_columns": numeric,
        "categorical_columns": categorical, "reference_period": REFERENCE_PERIOD,
        "reference_index": reference, "target_period": TARGET_PERIOD, "target_index": target,
        "adjustment_factor": target/reference, "growth_percent": (target/reference-1)*100,
        "fit_count": int(train.sum()), "fit_years": [2006, 2007, 2008, 2009],
        "training_order_ids": data.loc[train, "Order"].tolist(),
        "test_order_ids": data.loc[test, "Order"].tolist(), "test_count": int(test.sum()),
        "historical_2010_full_inputs": full_metrics, "simplified_validation": simplified_metrics,
        "evaluation_note": "Descriptive retrospective 2010 check on a previously inspected holdout. Revised HPI values and sale-quarter indices are used; this is not an as-of-date forecast or an independent test.",
        "accuracy_2026": None, "index_source": source, "input_sha256": original["input_sha256"],
        "architecture_selection": "Uses the compact architecture chosen in the original historical validation; no new hyperparameter search.",
        "normalization": "SalePrice * HPI(2010Q2) / HPI(recorded sale quarter). Sale year and month are excluded from predictors.",
        "scenario_assumptions": "Property characteristics stay as supplied. All homes follow the Ames metropolitan all-transactions index. No automatic renovations, deterioration, neighborhood-specific drift, or individual prediction interval.",
        "units": "USD at the 2010Q2 market reference, then scaled to the requested published quarter",
        "model_sha256": hashlib.sha256(saved.read_bytes()).hexdigest(), "fit_seconds": duration,
        "warnings": notices, "random_seed": 42, "generated_at": datetime.now(ZoneInfo("Europe/Madrid")).isoformat(),
        "versions": original["versions"]}
    prediction_table = data.loc[test, ["Order", "PID", "Neighborhood", "SalePrice", "Yr Sold", "Mo Sold"]].copy()
    prediction_table["reference_price_2010_q2_usd"] = test_reference
    prediction_table["predicted_at_actual_sale_quarter_usd"] = test_nominal
    prediction_table["scenario_2026_q2_usd"] = adjust_reference_price(test_reference, index)
    prediction_table.to_csv(MARKET_DIR / "test_predictions.csv", index=False)
    scenarios = data[["Order", "Neighborhood", "Yr Sold", "Mo Sold", "SalePrice"]].rename(columns={"SalePrice":"actual_historical_sale_price_usd"}).copy()
    scenarios["reference_price_2010_q2_usd"] = predict_quiet(model, X)
    scenarios["scenario_2026_q2_usd"] = adjust_reference_price(scenarios["reference_price_2010_q2_usd"], index)
    scenarios["index_factor"] = target/reference
    scenarios.to_csv(MARKET_DIR / "market_scenarios.csv", index=False)
    # Match the existing three 2010 example properties, without including prices
    # or price predictions as model inputs.
    examples = scenarios.loc[data.index[test][:3]].copy()
    examples.to_csv(MARKET_DIR / "example_predictions.csv", index=False)
    metadata["elapsed_seconds"] = time.perf_counter()-start
    (MARKET_DIR / "model_metadata.json").write_text(json.dumps(metadata, indent=2, allow_nan=False)+"\n")

    assets = ROOT / "portal/public/assets"
    exported = export_hist_model(model, metadata, saved)
    (assets / "market-model.json").write_text(json.dumps(exported, separators=(",", ":"), allow_nan=False))
    public_metadata = {k: metadata[k] for k in ["selected_model", "reference_period", "reference_index", "target_period", "target_index", "adjustment_factor", "growth_percent", "index_source", "scenario_assumptions", "simplified_validation", "accuracy_2026", "model_sha256"]}
    (assets / "market.json").write_text(json.dumps(public_metadata, separators=(",", ":"), allow_nan=False))
    market_fixtures = {"rows": [{c: clean(row[c]) for c in features} for _, row in X.loc[test].iterrows()],
        "reference_predictions": test_reference.tolist(), "scenario_predictions": adjust_reference_price(test_reference, index).tolist(),
        "forms": forms, "adapted_reference_predictions": simplified_reference.tolist(),
        "adapted_scenario_predictions": adjust_reference_price(simplified_reference, index).tolist()}
    (ROOT / "portal/tests/market-fixtures.json").write_text(json.dumps(market_fixtures, separators=(",", ":"), allow_nan=False))
    render_saved_report(ROOT / "models/ames", ROOT / "reports/ames_models.html")
    print(json.dumps({"reference_period": REFERENCE_PERIOD, "target_period": TARGET_PERIOD,
        "adjustment_factor": target/reference, "historical_full_input_metrics": full_metrics,
        "historical_simplified_metrics": simplified_metrics, "elapsed_seconds": time.perf_counter()-start}, indent=2))


if __name__ == "__main__":
    with threadpool_limits(limits=2):
        main()
