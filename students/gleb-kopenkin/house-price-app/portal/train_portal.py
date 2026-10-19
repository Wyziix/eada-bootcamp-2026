"""Train the model behind the price portal and build portal.html.

Data: 21,613 real house and apartment sales in King County (Seattle area),
May 2014 to May 2015. Unlike the California data, every row is ONE home,
with its size, bedrooms, bathrooms, etc. That's what a portal needs.

Run (from the portal folder):  python train_portal.py
Output: scores in the terminal and portal.html (open in any browser).
"""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error, r2_score
from sklearn.model_selection import train_test_split
from xgboost import XGBRegressor

SEED = 42
df = pd.read_csv("../data/king_county_sales.csv")

# ---- Clean ----
df = df[(df.bedrooms.between(1, 10)) & (df.bathrooms > 0)]  # drops a 33-bedroom typo and empty rows
df["renovated"] = (df.yr_renovated > 0).astype(int)

FEATURES = ["sqft_living", "bedrooms", "bathrooms", "floors", "sqft_lot", "yr_built", "renovated",
            "condition", "grade", "view", "waterfront", "lat", "long"]
X = df[FEATURES]
y = np.log(df.price)  # train on log(price): a 10% miss counts the same on cheap and expensive homes
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=SEED)
price_test = np.exp(y_test)

models = {
    "Linear regression": LinearRegression(),
    "XGBoost": XGBRegressor(n_estimators=600, max_depth=6, learning_rate=0.05, subsample=0.8,
                            colsample_bytree=0.8, n_jobs=4, random_state=SEED),
    "Histogram gradient boosting": HistGradientBoostingRegressor(max_iter=600, learning_rate=0.05,
                                                                 max_leaf_nodes=31, random_state=SEED),
}
scores = {}
for name, m in models.items():
    t0 = time.perf_counter()
    m.fit(X_train, y_train)
    pred = np.exp(m.predict(X_test))
    s = {"mae": mean_absolute_error(price_test, pred), "mape": mean_absolute_percentage_error(price_test, pred),
         "r2": r2_score(price_test, pred), "within10": float((abs(pred - price_test) / price_test <= 0.1).mean()),
         "train_s": time.perf_counter() - t0}
    scores[name] = s
    print(f"{name:28s} MAE ${s['mae']:>8,.0f}  MAPE {s['mape']:.1%}  R2 {s['r2']:.3f}  "
          f"within 10%: {s['within10']:.0%}  {s['train_s']:.1f}s")

# ---- Export histogram gradient boosting (tied best, and easy to run in a browser) ----
gbm = models["Histogram gradient boosting"]
trees = [[[int(n["feature_idx"]), float(n["num_threshold"]), int(n["left"]), int(n["right"]),
           round(float(n["value"]), 6) if n["is_leaf"] else None] for n in p.nodes]
         for (p,) in gbm._predictors]
model = {"features": FEATURES, "baseline": float(np.ravel(gbm._baseline_prediction)[0]), "trees": trees}


def predict_json(row):
    total = model["baseline"]
    for t in model["trees"]:
        i = 0
        while t[i][4] is None:
            i = t[i][2] if row[t[i][0]] <= t[i][1] else t[i][3]
        total += t[i][4]
    return np.exp(total)


check = X_test.head(300)
gap = max(abs(predict_json(r) - p) for r, p in zip(check.values.tolist(), np.exp(gbm.predict(check))))
print(f"\nJSON trees vs sklearn, biggest gap on 300 homes: ${gap:,.2f}")

s = scores["Histogram gradient boosting"]
stats = {"mae": round(s["mae"]), "mape": round(s["mape"], 4), "r2": round(s["r2"], 3),
         "within10": round(s["within10"], 3), "n_train": len(X_train), "n_test": len(X_test),
         "median_price": float(df.price.median()),
         "price_pcts": [round(float(v)) for v in np.percentile(df.price, np.arange(0, 101, 5))]}

# Recent sales for the map: 5,000 random homes (lon, lat, price in $k)
pts = df.sample(5000, random_state=1)
points = [[round(a, 3), round(b, 3), round(c / 1000)] for a, b, c in zip(pts.long, pts.lat, pts.price)]

html = Path("portal_template.html").read_text()
html = (html.replace("/*MODEL*/null", json.dumps(model, separators=(",", ":")))
            .replace("/*STATS*/null", json.dumps(stats))
            .replace("/*POINTS*/null", json.dumps(points, separators=(",", ":"))))
Path("portal.html").write_text(html)
print(f"Saved portal.html ({len(html) / 1024:,.0f} KB)")
