"""Build california_portal.html: the user-friendly price portal for California.

Uses the model from ../model.json (made by train.py + export_model.py).
Run (from the portal folder):  python build_california_portal.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import train_test_split

df = pd.read_csv("../data/california_housing.csv")
df = df[df.median_house_value < 500_000]
df["rooms_per_household"] = df.total_rooms / df.households
df["bedrooms_per_room"] = df.total_bedrooms / df.total_rooms
df["people_per_household"] = df.population / df.households

# A portal model with "common sense" rules (monotonic constraints):
#   richer neighbourhood -> price can only go up       (+1)
#   more rooms per home  -> price can only go up       (+1)
#   bigger share of the rooms are bedrooms -> can only go down (-1, smaller living space)
#   more people per home -> price can only go down     (-1)
# Without these, the trees sometimes say odd things for made-up homes,
# like "a poorer neighbourhood makes this home pricier". Accuracy barely changes.
NUMERIC = ["longitude", "latitude", "housing_median_age", "median_income",
           "rooms_per_household", "bedrooms_per_room", "people_per_household"]
RULES = [0, 0, 0, 1, 1, -1, -1]
CATS = sorted(df.ocean_proximity.unique())
X = df[NUMERIC].fillna(df[NUMERIC].median())
for c in CATS:
    X[c] = (df.ocean_proximity == c).astype(int)
y = df.median_house_value
X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42)
gbm = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.08, monotonic_cst=RULES + [0] * len(CATS),
                                    random_state=42).fit(X_tr, y_tr)
mae = mean_absolute_error(y_te, gbm.predict(X_te))
print(f"Portal model (with rules): average error ${mae:,.0f}")

model = {
    "numeric": NUMERIC, "categories": CATS, "mae": round(mae),
    "baseline": float(np.ravel(gbm._baseline_prediction)[0]),
    # one row per node: [feature, threshold, left, right, leaf value or null]
    "trees": [[[int(n["feature_idx"]), float(n["num_threshold"]), int(n["left"]), int(n["right"]),
                round(float(n["value"]), 2) if n["is_leaf"] else None] for n in p.nodes]
              for (p,) in gbm._predictors],
}
gap = 0.0
for row, ref in zip(X_te.head(300).values.tolist(), gbm.predict(X_te.head(300))):
    t = model["baseline"]
    for tree in model["trees"]:
        i = 0
        while tree[i][4] is None:
            i = tree[i][2] if row[tree[i][0]] <= tree[i][1] else tree[i][3]
        t += tree[i][4]
    gap = max(gap, abs(t - ref))
print(f"JSON trees vs sklearn, biggest gap on 300 rows: ${gap:,.2f}")

# The friendly 5-level "neighbourhood" scale = the typical income of each fifth of blocks
income_levels = df.groupby(pd.qcut(df.median_income, 5), observed=True).median_income.median().round(2).tolist()

stats = {
    "mae": model["mae"],
    "income_levels": income_levels,
    "people": round(float((df.population / df.households).median()), 2),  # not asked: set to the typical value
    "price_pcts": [round(float(v)) for v in np.percentile(df.median_house_value, np.arange(0, 101, 5))],
}

# 6,000 blocks for the map: lon, lat, price in $k, ocean category index
pts = pd.read_csv("../data/california_housing.csv").sample(6000, random_state=1)
cats = model["categories"]
points = [[round(r.longitude, 2), round(r.latitude, 2), round(r.median_house_value / 1000),
           cats.index(r.ocean_proximity)] for r in pts.itertuples()]

html = Path("california_template.html").read_text()
html = (html.replace("/*MODEL*/null", json.dumps(model, separators=(",", ":")))
            .replace("/*STATS*/null", json.dumps(stats))
            .replace("/*POINTS*/null", json.dumps(points, separators=(",", ":"))))
Path("california_portal.html").write_text(html)
print(f"Saved california_portal.html ({len(html) / 1024:,.0f} KB). Income levels: {income_levels}")
