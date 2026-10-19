"""Step 5: test 6 algorithms on the same data and compare them.

Run:  python compare_models.py
Output: scores in the terminal, results/model_comparison.json, and
        model_report.html (built from report_template.html).

All models are kept small so the whole script runs in about a minute.
"""
import json
import pickle
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer, TransformedTargetRegressor
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression
from sklearn.metrics import (mean_absolute_error, mean_absolute_percentage_error,
                             mean_squared_error, r2_score)
from sklearn.model_selection import KFold, cross_val_score, train_test_split
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeRegressor
from xgboost import XGBRegressor

SEED = 42

# ---- Same data prep and split as train.py, so results are comparable ----
df = pd.read_csv("data/california_housing.csv")
df = df[df["median_house_value"] < 500_000]
df["rooms_per_household"] = df["total_rooms"] / df["households"]
df["bedrooms_per_room"] = df["total_bedrooms"] / df["total_rooms"]
df["people_per_household"] = df["population"] / df["households"]

NUMERIC = ["longitude", "latitude", "housing_median_age", "median_income",
           "rooms_per_household", "bedrooms_per_room", "people_per_household"]
CATEGORY = ["ocean_proximity"]
X = df[NUMERIC + CATEGORY]
y = df["median_house_value"]
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=SEED)


def prep():
    return ColumnTransformer([
        ("num", Pipeline([("fill", SimpleImputer(strategy="median")),
                          ("scale", StandardScaler())]), NUMERIC),
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORY),
    ])


# ---- The 6 models, each kept small ----
MODELS = {
    "Linear regression": (
        LinearRegression(),
        "Draws one straight-line formula: price = a×income + b×rooms + ... Fast and easy to explain, "
        "but can't bend to fit curves.",
    ),
    "Decision tree": (
        DecisionTreeRegressor(max_depth=10, min_samples_leaf=20, random_state=SEED),
        "Asks yes/no questions (income > $50k? inland?) until it reaches a price. "
        "Depth capped at 10 so it doesn't memorise the data.",
    ),
    "Random forest": (
        RandomForestRegressor(n_estimators=100, max_depth=15, min_samples_leaf=5,
                              n_jobs=-1, random_state=SEED),
        "100 decision trees, each trained on a random slice of the data. "
        "The final price is their average, which cancels out individual mistakes.",
    ),
    "XGBoost": (
        XGBRegressor(n_estimators=400, max_depth=6, learning_rate=0.05,
                     subsample=0.8, colsample_bytree=0.8, n_jobs=4, random_state=SEED),
        "Builds trees one after another, each one fixing the errors of the ones before. "
        "The go-to method for table data in industry.",
    ),
    "Neural network": (
        TransformedTargetRegressor(
            regressor=MLPRegressor(hidden_layer_sizes=(64, 32), early_stopping=True,
                                   max_iter=300, random_state=SEED),
            transformer=StandardScaler(),
        ),
        "Two small layers of 64 and 32 'neurons' that learn weights by trial and error. "
        "Powerful on images and text, usually not the best on small tables.",
    ),
    "Histogram gradient boosting": (
        HistGradientBoostingRegressor(max_iter=500, learning_rate=0.05,
                                      early_stopping=True, random_state=SEED),
        "My pick: same idea as XGBoost, but groups values into bins first, so it trains "
        "very fast and handles missing values by itself. Built into scikit-learn.",
    ),
}

results = []
for name, (model, how) in MODELS.items():
    pipe = Pipeline([("prep", prep()), ("model", model)])

    # 5-fold cross-validation on the training set: how stable is the score?
    cv = -cross_val_score(pipe, X_train, y_train, cv=KFold(5, shuffle=True, random_state=SEED),
                          scoring="neg_mean_absolute_error", n_jobs=1)

    t0 = time.perf_counter()
    pipe.fit(X_train, y_train)
    train_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    pred = pipe.predict(X_test)
    predict_ms = (time.perf_counter() - t0) / len(X_test) * 1000 * 1000  # ms per 1,000 rows

    err = np.abs(pred - y_test) / y_test
    r = {
        "name": name,
        "how": how,
        "mae": float(mean_absolute_error(y_test, pred)),
        "rmse": float(np.sqrt(mean_squared_error(y_test, pred))),
        "r2": float(r2_score(y_test, pred)),
        "mape": float(mean_absolute_percentage_error(y_test, pred)),
        "within10": float((err <= 0.10).mean()),
        "cv_mae": float(cv.mean()),
        "cv_std": float(cv.std()),
        "train_s": round(train_s, 3),
        "predict_ms": round(predict_ms, 2),
        "size_kb": round(len(pickle.dumps(pipe)) / 1024, 1),
    }
    results.append(r)
    print(f"{name:28s} MAE ${r['mae']:>7,.0f}  R2 {r['r2']:.3f}  within 10%: {r['within10']:.0%}  "
          f"train {train_s:5.1f}s  size {r['size_kb']:>8,.0f} KB")

# Same 400 test houses for every model, for the predicted-vs-actual charts
sample_idx = np.random.default_rng(SEED).choice(len(X_test), 400, replace=False)
for (name, (model, _)), r in zip(MODELS.items(), results):
    pipe = Pipeline([("prep", prep()), ("model", model)]).fit(X_train, y_train)
    p = pipe.predict(X_test.iloc[sample_idx])
    r["sample"] = [[round(float(a) / 1000, 1), round(float(b) / 1000, 1)] for a, b in zip(y_test.iloc[sample_idx], p)]

results.sort(key=lambda r: r["mae"])
out = {"rows_train": len(X_train), "rows_test": len(X_test), "median_price": float(y_test.median()),
       "results": results}
Path("results").mkdir(exist_ok=True)
Path("results/model_comparison.json").write_text(json.dumps(out, indent=1))

html = Path("report_template.html").read_text().replace("/*DATA*/null", json.dumps(out))
Path("model_report.html").write_text(html)
print(f"\nBest: {results[0]['name']}. Saved results/model_comparison.json and model_report.html")
