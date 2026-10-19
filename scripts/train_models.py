#!/usr/bin/env python3
"""Benchmark small Ames Housing regressors and produce an offline HTML report.

Run with the project's activated virtual environment. Model selection uses
expanding calendar-year validation; 2010 is reserved for final evaluation.
"""
from __future__ import annotations

import os

# Keep small fits from occupying the workstation's entire CPU pool.
for _variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_variable, "2")

import argparse
import hashlib
import json
import platform
import time
import warnings
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import joblib
import jinja2
import numpy as np
import pandas as pd
import plotly
import plotly.graph_objects as go
import scipy
import sklearn
import xgboost
from jinja2 import Environment, FileSystemLoader, select_autoescape
from plotly.offline import get_plotlyjs
from sklearn.base import clone
from sklearn.compose import ColumnTransformer, TransformedTargetRegressor
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeRegressor
from threadpoolctl import threadpool_limits
from xgboost import XGBRegressor

from eda import load_data, read_dictionary

ROOT = Path(__file__).resolve().parents[1]
SEED = 42
EXCLUDED = ["Order", "PID", "Sale Type", "Sale Condition"]
BLUE, TEAL, AMBER = "#335fe5", "#087f75", "#b96e13"
MODEL_INFO = {
    "Median baseline": ("Reference", "Always predicts the median training sale price. A useful model should beat this.", "No learned rules; median price in USD."),
    "Linear regression": ("Linear", "A straight-line relationship after encoding the property categories and taking log prices.", "Ordinary least squares; no regularization."),
    "Decision tree": ("Tree", "A short sequence of rules, such as quality and floor-area thresholds.", "Maximum depth 6; at least 8 homes per leaf."),
    "Random forest": ("Ensemble", "Averages many small trees to reduce the instability of a single tree.", "160 trees; maximum depth 14; at least 2 homes per leaf; 80% of features per split."),
    "XGBoost": ("Boosting", "Adds shallow trees, each correcting errors left by earlier trees.", "220 trees; depth 3; learning rate 0.05; 85% row and column sampling; histogram tree construction."),
    "Neural network": ("Neural", "A small network that learns nonlinear combinations of the encoded inputs.", "Two hidden layers (32, 16); Adam; at most 250 epochs; early stopping after 15 unimproved epochs."),
    "Ridge regression": ("Linear", "Regularized linear regression: shrinks coefficients to stabilize correlated inputs.", "L2 penalty alpha=10; SVD solver."),
    "Histogram gradient boosting": ("Boosting", "Another compact boosting approach that groups feature values into bins.", "180 iterations; 15 leaves; depth 4; learning rate 0.06; at least 15 homes per leaf; L2=1."),
}


def metrics(actual, predicted):
    actual, predicted = np.asarray(actual), np.asarray(predicted)
    if not np.isfinite(predicted).all() or (predicted < 0).any():
        raise ValueError("A model produced non-finite or negative house prices.")
    error = predicted - actual
    percentage = np.abs(error) / actual
    return {
        "rmse": float(np.sqrt(mean_squared_error(actual, predicted))),
        "mae": float(mean_absolute_error(actual, predicted)),
        "r2": float(r2_score(actual, predicted)),
        "mape": float(percentage.mean() * 100),
        "median_ape": float(np.median(percentage) * 100),
        "within_10": float((percentage <= .10).mean() * 100),
        "within_20": float((percentage <= .20).mean() * 100),
        "bias": float(error.mean()),
    }


def make_preprocessor(numeric, categorical):
    return ColumnTransformer([
        ("numeric", Pipeline([
            ("impute", SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)),
            ("scale", StandardScaler()),
        ]), numeric),
        ("categorical", Pipeline([
            ("impute", SimpleImputer(strategy="constant", fill_value="__MISSING__", keep_empty_features=True)),
            ("encode", OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=10,
                                      drop="first", sparse_output=False)),
        ]), categorical),
    ], remainder="drop")


def make_models(numeric, categorical):
    estimators = {
        "Median baseline": DummyRegressor(strategy="median"),
        "Linear regression": LinearRegression(),
        "Decision tree": DecisionTreeRegressor(max_depth=6, min_samples_leaf=8, random_state=SEED),
        "Random forest": RandomForestRegressor(n_estimators=160, max_depth=14, min_samples_leaf=2,
                                                max_features=.8, n_jobs=2, random_state=SEED),
        "XGBoost": XGBRegressor(n_estimators=220, max_depth=3, learning_rate=.05, subsample=.85,
                                colsample_bytree=.85, objective="reg:squarederror", reg_lambda=1,
                                tree_method="hist", n_jobs=2, random_state=SEED),
        "Neural network": TransformedTargetRegressor(
            regressor=MLPRegressor(hidden_layer_sizes=(32, 16), alpha=.1, batch_size=64,
                learning_rate_init=.001, max_iter=250, early_stopping=True,
                validation_fraction=.15, n_iter_no_change=15, tol=1e-4, random_state=SEED),
            transformer=StandardScaler()),
        "Ridge regression": Ridge(alpha=10, solver="svd"),
        "Histogram gradient boosting": HistGradientBoostingRegressor(
            max_iter=180, max_leaf_nodes=15, max_depth=4, learning_rate=.06,
            min_samples_leaf=15, l2_regularization=1, early_stopping=False, random_state=SEED),
    }
    models = {}
    for name, estimator in estimators.items():
        pipeline = Pipeline([("preprocess", make_preprocessor(numeric, categorical)), ("model", estimator)])
        models[name] = pipeline if name == "Median baseline" else TransformedTargetRegressor(
            regressor=pipeline, func=np.log1p, inverse_func=np.expm1)
    return models


def fit_record(model, X, y):
    start = time.perf_counter()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model.fit(X, y)
    duration = time.perf_counter() - start
    return duration, sorted({str(w.message) for w in caught})


def predict_quiet(model, X):
    # Unknown categories are deliberately supported by the encoder. Record their
    # counts separately instead of repeating sklearn's expected warning per call.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Found unknown categories.*", category=UserWarning)
        return model.predict(X)


def chart(fig, name, height=390):
    fig.update_layout(template="plotly_white", height=height,
        margin=dict(l=70, r=30, t=30, b=65), font=dict(family="system-ui, sans-serif", color="#213547", size=12),
        yaxis=dict(automargin=True),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        colorway=[BLUE, TEAL, AMBER, "#9464c4", "#d96372", "#5c7f90", "#65a55b", "#969baf"],
        legend=dict(orientation="h", y=1.13, x=0))
    return fig.to_html(full_html=False, include_plotlyjs=False, div_id=name,
        config={"responsive": True, "displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]})


def bootstrap_intervals(actual, predicted):
    rng = np.random.default_rng(SEED)
    error = np.asarray(predicted) - np.asarray(actual)
    samples = error[rng.integers(0, len(error), size=(1500, len(error)))]
    return {
        "mae": np.quantile(np.abs(samples).mean(axis=1), [.025, .975]).tolist(),
        "rmse": np.quantile(np.sqrt((samples ** 2).mean(axis=1)), [.025, .975]).tolist(),
    }


def read_prediction_input(path: Path, metadata):
    """Apply deterministic input parsing; learned imputations stay in the model."""
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = set(metadata["feature_columns"]) - set(raw.columns)
    if missing:
        raise ValueError("Missing required input columns: " + ", ".join(sorted(missing)))
    if raw.empty:
        raise ValueError("Input CSV contains no rows.")
    frame = pd.DataFrame(index=raw.index)
    for column in metadata["feature_columns"]:
        values = raw[column].str.strip().replace("", np.nan)
        frame[column] = pd.to_numeric(values, errors="raise") if column in metadata["numeric_columns"] else values
    if not np.isfinite(frame[metadata["numeric_columns"]].to_numpy(dtype=float)[
            ~frame[metadata["numeric_columns"]].isna().to_numpy()]).all():
        raise ValueError("Numeric inputs must be finite or blank.")
    return raw, frame


def run(input_path, output_path, artifacts_path):
    started = time.perf_counter()
    definitions = read_dictionary(ROOT / "dat/ames/data_description.txt")
    raw, data = load_data(input_path, definitions)
    years = data["Yr Sold"].astype(int)
    if set(years.unique()) != {2006, 2007, 2008, 2009, 2010}:
        raise ValueError("This benchmark expects the original Ames sale years 2006–2010.")
    if data["PID"].duplicated().any():
        raise ValueError("Repeated parcel IDs require a grouped evaluation strategy.")
    feature_columns = [c for c in data if c not in EXCLUDED + ["SalePrice"]]
    X, y = data[feature_columns], data["SalePrice"]
    numeric = X.select_dtypes(include="number").columns.tolist()
    categorical = [c for c in feature_columns if c not in numeric]
    dev, test = np.flatnonzero(years < 2010), np.flatnonzero(years == 2010)
    folds = [(np.flatnonzero(years < year), np.flatnonzero(years == year), year)
             for year in (2007, 2008, 2009)]
    fold_description = [{"train_years": f"2006–{year-1}" if year > 2007 else "2006",
        "validation_year": year, "train_rows": len(train), "validation_rows": len(valid)}
        for train, valid, year in folds]
    models = make_models(numeric, categorical)
    records, cv_rows, last_models = [], [], {}
    print(f"{len(data):,} sales | {len(feature_columns)} inputs | development {len(dev):,} | test {len(test):,}", flush=True)

    # Complete every validation comparison and choose the winner before accessing
    # test outcomes for scoring or fitting any final models.
    for name, prototype in models.items():
        print(f"Validating {name} ...", flush=True)
        rows, messages = [], []
        for train, valid, year in folds:
            fitted = clone(prototype)
            duration, notices = fit_record(fitted, X.iloc[train], y.iloc[train])
            prediction = predict_quiet(fitted, X.iloc[valid])
            result = {"model": name, "year": year, "fit_seconds": duration,
                      **metrics(y.iloc[valid], prediction)}
            rows.append(result)
            cv_rows.append(result)
            messages.extend(notices)
            print(f"  {year}: RMSE ${result['rmse']:,.0f}; fit {duration:.2f}s", flush=True)
        last_models[name] = fitted
        family, explanation, size = MODEL_INFO[name]
        records.append({"name": name, "family": family, "explanation": explanation, "size": size,
            "cv_rmse": float(np.mean([r["rmse"] for r in rows])),
            "cv_rmse_std": float(np.std([r["rmse"] for r in rows], ddof=1)),
            "cv_mae": float(np.mean([r["mae"] for r in rows])),
            "cv_fit_seconds": float(sum(r["fit_seconds"] for r in rows)),
            "warnings": sorted(set(messages)), "folds": rows})
    ranked = sorted([r for r in records if r["name"] != "Median baseline"], key=lambda r: r["cv_rmse"])
    winner_name = ranked[0]["name"]
    print(f"Selected on validation: {winner_name}", flush=True)
    for i, record in enumerate(ranked, start=1):
        record["rank"] = i
    next(r for r in records if r["name"] == "Median baseline")["rank"] = 8
    records.sort(key=lambda r: r["rank"])

    # Explain the selected model using only the final development fold (2009).
    print("Computing development-only feature importance ...", flush=True)
    importance_start = time.perf_counter()
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Found unknown categories.*", category=UserWarning)
        importance = permutation_importance(last_models[winner_name], X.iloc[folds[-1][1]],
            y.iloc[folds[-1][1]], scoring="neg_root_mean_squared_error", n_repeats=3,
            n_jobs=1, random_state=SEED)
    importance_rows = sorted([{"feature": feature, "increase_rmse": float(mean), "std": float(std)}
        for feature, mean, std in zip(feature_columns, importance.importances_mean, importance.importances_std)],
        key=lambda row: row["increase_rmse"], reverse=True)
    importance_seconds = time.perf_counter() - importance_start

    predictions, winner_model = {}, None
    for record in records:
        name = record["name"]
        fitted = clone(models[name])
        duration, notices = fit_record(fitted, X.iloc[dev], y.iloc[dev])
        prediction = predict_quiet(fitted, X.iloc[test])
        predictions[name] = prediction
        record.update({"test": metrics(y.iloc[test], prediction),
            "train": metrics(y.iloc[dev], predict_quiet(fitted, X.iloc[dev])),
            "fit_seconds": duration, "total_fit_seconds": duration + record["cv_fit_seconds"],
            "warnings": sorted(set(record["warnings"] + notices))})
        # Warmed batch timing includes learned imputation/encoding and prediction.
        timings = []
        for _ in range(5):
            tick = time.perf_counter()
            predict_quiet(fitted, X.iloc[test])
            timings.append(time.perf_counter() - tick)
        record["predict_ms_per_1000"] = float(np.median(timings) * 1000 * 1000 / len(test))
        regressor = fitted if name == "Median baseline" else fitted.regressor_
        record["encoded_features"] = int(len(regressor.named_steps["preprocess"].get_feature_names_out()))
        parameters = {k: v for k, v in regressor.named_steps["model"].get_params().items()
                      if not k.startswith("regressor__")}
        # XGBoost's default missing-value sentinel is NaN, which is configuration
        # data rather than a failed numeric result. Represent it as the text NaN
        # while keeping the output strict JSON (including every measured KPI).
        record["parameters"] = json.loads(json.dumps(parameters, default=json_default), parse_constant=str)
        if name == "Neural network":
            network = regressor.named_steps["model"].regressor_
            record["epochs"] = int(network.n_iter_)
            record["network_parameters"] = int(sum(a.size for a in network.coefs_) + sum(a.size for a in network.intercepts_))
        print(f"Final {name}: test RMSE ${record['test']['rmse']:,.0f}; fit {duration:.2f}s", flush=True)
        if name == winner_name:
            winner_model = fitted

    winner = next(r for r in records if r["name"] == winner_name)
    baseline = next(r for r in records if r["name"] == "Median baseline")
    actual = y.iloc[test].to_numpy()
    selected_prediction = predictions[winner_name]
    ci = bootstrap_intervals(actual, selected_prediction)
    unknown_counts = {c: int((~X.iloc[test][c].isin(X.iloc[dev][c].dropna().unique()) & X.iloc[test][c].notna()).sum())
                      for c in categorical}
    unknown_counts = {k: v for k, v in unknown_counts.items() if v}
    segments = []
    for label, mask in [("Under $150k", actual < 150000),
                        ("$150k–$250k", (actual >= 150000) & (actual < 250000)),
                        ("$250k and above", actual >= 250000)]:
        if mask.sum() >= 2:
            segments.append({"label": label, "count": int(mask.sum()), **metrics(actual[mask], selected_prediction[mask])})

    artifacts_path.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prediction_table = data.iloc[test][["Order", "PID", "Neighborhood", "Yr Sold", "Gr Liv Area", "SalePrice"]].copy()
    for name, prediction in predictions.items():
        prediction_table[name] = prediction
    prediction_table["selected_error_usd"] = selected_prediction - actual
    prediction_table["selected_absolute_error_usd"] = abs(selected_prediction - actual)
    prediction_table["selected_ape_pct"] = abs(selected_prediction - actual) / actual * 100
    prediction_table.to_csv(artifacts_path / "test_predictions.csv", index=False)
    pd.DataFrame(cv_rows).to_csv(artifacts_path / "validation_metrics.csv", index=False)
    flat_metrics = [{"model": r["name"], "validation_rank": r["rank"],
        "cv_rmse_usd": r["cv_rmse"], "cv_rmse_year_std_usd": r["cv_rmse_std"],
        "final_fit_seconds": r["fit_seconds"], "all_fit_seconds": r["total_fit_seconds"],
        "predict_ms_per_1000": r["predict_ms_per_1000"],
        **{f"test_{k}": v for k, v in r["test"].items()}} for r in records]
    pd.DataFrame(flat_metrics).to_csv(artifacts_path / "model_metrics.csv", index=False)
    data.iloc[test[:3]][["Order", "PID"] + feature_columns].to_csv(artifacts_path / "example_properties.csv", index=False)
    joblib.dump(winner_model, artifacts_path / "best_model.joblib", compress=3)
    versions = {"python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__,
        "scikit-learn": sklearn.__version__, "xgboost": xgboost.__version__, "scipy": scipy.__version__,
        "plotly": plotly.__version__, "jinja2": jinja2.__version__, "joblib": joblib.__version__}
    metadata = {"selected_model": winner_name, "random_seed": SEED,
        "input_file": str(input_path.resolve()), "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        "feature_columns": feature_columns, "numeric_columns": numeric, "categorical_columns": categorical,
        "excluded_columns": EXCLUDED, "target": "SalePrice", "units": "Historical USD (2006–2010)",
        "fit_years": [2006, 2007, 2008, 2009], "test_year": 2010,
        "training_order_ids": data.iloc[dev]["Order"].tolist(), "test_order_ids": data.iloc[test]["Order"].tolist(),
        "selection_rule": "Lowest unweighted mean RMSE over validation years 2007, 2008, 2009; excludes median baseline",
        "folds": fold_description, "versions": versions, "thread_limit": 2,
        "target_transform": "log1p, inverse expm1; no mean-bias correction; median baseline uses USD directly",
        "bootstrap_95_percent": ci, "test_unknown_category_counts": unknown_counts,
        "importance_seconds": importance_seconds, "importance": importance_rows,
        "models": records, "generated_at": datetime.now(ZoneInfo("Europe/Madrid")).isoformat()}
    # The main elapsed clock includes fits, scoring, explanation and serialization;
    # HTML rendering is the only subsequent workload.
    metadata["elapsed_seconds"] = time.perf_counter() - started
    (artifacts_path / "model_metadata.json").write_text(json.dumps(metadata, indent=2, default=json_default, allow_nan=False), encoding="utf-8")

    render_saved_report(artifacts_path, output_path)
    print(f"Report: {output_path.resolve()}", flush=True)
    print(f"Artifacts: {artifacts_path.resolve()}", flush=True)
    print(f"Total wall time: {time.perf_counter()-started:.1f}s", flush=True)


def render_saved_report(artifacts_path, output_path):
    """Refresh the HTML from saved measurements without changing fitted models."""
    from market_adjustment import report_context

    metadata = json.loads((artifacts_path / "model_metadata.json").read_text())
    records = metadata["models"]
    winner = next(r for r in records if r["name"] == metadata["selected_model"])
    baseline = next(r for r in records if r["name"] == "Median baseline")
    ranked = sorted([r for r in records if r["name"] != "Median baseline"], key=lambda r: r["cv_rmse"])
    prediction_table = pd.read_csv(artifacts_path / "test_predictions.csv", dtype={"Order": str, "PID": str})
    cv_rows = pd.read_csv(artifacts_path / "validation_metrics.csv").to_dict("records")
    actual = prediction_table["SalePrice"].to_numpy()
    selected_prediction = prediction_table[winner["name"]].to_numpy()
    ci = metadata["bootstrap_95_percent"]
    importance_rows = metadata["importance"]
    feature_columns = metadata["feature_columns"]
    numeric, categorical = metadata["numeric_columns"], metadata["categorical_columns"]
    test = metadata["test_order_ids"]
    dev = metadata["training_order_ids"]
    segments = []
    for label, mask in [("Under $150k", actual < 150000),
                        ("$150k–$250k", (actual >= 150000) & (actual < 250000)),
                        ("$250k and above", actual >= 250000)]:
        if mask.sum() >= 2:
            segments.append({"label": label, "count": int(mask.sum()), **metrics(actual[mask], selected_prediction[mask])})
    flat_metrics = pd.read_csv(artifacts_path / "model_metrics.csv")
    charts = make_charts(records, cv_rows, actual, selected_prediction, importance_rows)
    worst = prediction_table.sort_values("selected_absolute_error_usd", ascending=False).head(12).to_dict("records")
    environment = Environment(loader=FileSystemLoader(ROOT / "scripts/templates"), autoescape=select_autoescape(["html", "j2"]))
    environment.filters.update(money=lambda v: f"${v:,.0f}", integer=lambda v: f"{v:,}",
        decimal=lambda v: f"{v:.2f}", percent=lambda v: f"{v:.1f}%")
    # Download data are embedded: the report is independently shareable.
    downloads = {"metrics": flat_metrics.to_csv(index=False),
                 "predictions": prediction_table.to_csv(index=False),
                 "validation": pd.DataFrame(cv_rows).to_csv(index=False)}
    market = report_context()
    if market:
        history = market["index_history"]
        figure = go.Figure(go.Scatter(x=[str(pd.Period(r["period"], freq="Q").start_time.date()) for r in history],
            y=[r["index"] / market["reference_index"] * 100 for r in history], mode="lines", line=dict(color=TEAL, width=3),
            hovertemplate="%{x}<br>Market level: %{y:.1f} (2010Q2 = 100)<extra></extra>"))
        figure.add_hline(y=100, line_dash="dash", line_color="#8391a5")
        figure.update_layout(xaxis_title="Published index period", yaxis_title="Ames metro HPI · 2010Q2 = 100")
        market["chart"] = chart(figure, "market-index-chart")
        downloads["market"] = market["scenarios_csv"]
    report = environment.get_template("ames_models.html.j2").render(
        metadata=metadata, records=records, winner=winner, baseline=baseline, charts=charts, market=market,
        ci=ci, segments=segments, worst=worst, downloads=downloads, plotly_js=get_plotlyjs(),
        test_rows=len(test), dev_rows=len(dev), rows=len(test)+len(dev), feature_count=len(feature_columns),
        numeric_count=len(numeric), categorical_count=len(categorical),
        baseline_improvement=(1-winner["test"]["rmse"]/baseline["test"]["rmse"])*100,
        cv_gap=ranked[1]["cv_rmse"]-ranked[0]["cv_rmse"], runner_up=ranked[1]["name"],
        test_best=min(records, key=lambda r: r["test"]["rmse"])["name"],
        generated=datetime.now(ZoneInfo("Europe/Madrid")).strftime("%d %B %Y, %H:%M %Z"))
    output_path.write_text(report, encoding="utf-8")
    return output_path


def json_default(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (StandardScaler, MLPRegressor)):
        return repr(value)
    raise TypeError(f"Cannot serialize {type(value)}")


def make_charts(records, cv_rows, actual, predicted, importance_rows):
    labels = [r["name"] for r in records]
    figure = go.Figure()
    for key, label, color in [("cv_rmse", "Validation RMSE · mean of 3 years", BLUE), ("test", "2010 test RMSE", TEAL)]:
        figure.add_trace(go.Bar(name=label, x=labels,
            y=[r[key]["rmse"] if key == "test" else r[key] for r in records], marker_color=color,
            hovertemplate="%{x}<br>RMSE: $%{y:,.0f}<extra>%{fullData.name}</extra>"))
    figure.update_layout(barmode="group", yaxis_title="RMSE in USD · lower is better", yaxis_tickprefix="$", xaxis_tickangle=-22)
    comparison = chart(figure, "accuracy-chart", 445)
    figure = go.Figure()
    for r in records:
        figure.add_trace(go.Scatter(x=[row["year"] for row in r["folds"]], y=[row["rmse"] for row in r["folds"]],
            mode="lines+markers", name=r["name"], line=dict(width=3 if r["rank"] == 1 else 1.5),
            visible=True if r["rank"] in [1, 2, 3, 8] else "legendonly",
            hovertemplate="%{x}: $%{y:,.0f}<extra>%{fullData.name}</extra>"))
    figure.update_layout(xaxis=dict(title="Validation year", dtick=1), yaxis_title="Validation RMSE (USD)",
        legend=dict(orientation="h", y=-.25, x=0), margin=dict(b=120))
    stability = chart(figure, "stability-chart", 445)
    figure = go.Figure(go.Scatter(x=actual, y=predicted, mode="markers",
        marker=dict(color=TEAL, size=7, opacity=.65),
        hovertemplate="Actual $%{x:,.0f}<br>Predicted $%{y:,.0f}<extra></extra>"))
    low, high = float(min(actual.min(), predicted.min())), float(max(actual.max(), predicted.max()))
    figure.add_trace(go.Scatter(x=[low, high], y=[low, high], mode="lines", line=dict(color="#8391a5", dash="dash"), showlegend=False, hoverinfo="skip"))
    figure.update_layout(xaxis_title="Actual sale price (USD)", yaxis_title="Predicted price (USD)", showlegend=False)
    scatter = chart(figure, "prediction-chart")
    figure = go.Figure(go.Scatter(x=actual, y=predicted-actual, mode="markers",
        marker=dict(color=BLUE, size=7, opacity=.65),
        hovertemplate="Actual $%{x:,.0f}<br>Error $%{y:,.0f}<extra></extra>"))
    figure.add_hline(y=0, line_dash="dash", line_color="#8391a5")
    figure.update_layout(xaxis_title="Actual sale price (USD)", yaxis_title="Prediction − actual (USD)", showlegend=False)
    residual = chart(figure, "residual-chart")
    figure = go.Figure(go.Bar(x=[r["total_fit_seconds"] for r in records][::-1], y=labels[::-1],
        orientation="h", marker_color=BLUE, hovertemplate="%{y}<br>Total fitting: %{x:.2f}s<extra></extra>"))
    figure.update_layout(xaxis_title="Seconds · 3 validation fits + 1 final fit", margin=dict(l=195))
    # Preserve room for full model labels after the shared defaults are applied.
    speed = chart(figure, "speed-chart")
    top = importance_rows[:12][::-1]
    figure = go.Figure(go.Bar(x=[r["increase_rmse"] for r in top], y=[r["feature"] for r in top],
        orientation="h", marker_color=TEAL,
        error_x=dict(type="data", array=[r["std"] for r in top]),
        hovertemplate="%{y}<br>RMSE increase $%{x:,.0f}<extra></extra>"))
    figure.update_layout(xaxis_title="Extra 2009 RMSE when a feature is shuffled (USD)", yaxis=dict(automargin=True))
    importance = chart(figure, "importance-chart", 430)
    return {"comparison": comparison, "stability": stability, "scatter": scatter,
            "residual": residual, "speed": speed, "importance": importance}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "dat/ames/ames_housing.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/ames_models.html")
    parser.add_argument("--artifacts", type=Path, default=ROOT / "models/ames")
    parser.add_argument("--report-only", action="store_true", help="Refresh HTML from saved metrics without retraining")
    args = parser.parse_args()
    with threadpool_limits(limits=2):
        if args.report_only:
            render_saved_report(args.artifacts, args.output)
        else:
            run(args.input, args.output, args.artifacts)


if __name__ == "__main__":
    main()
