"""Step 4b: turn model.joblib into model.json so a web page can run it.

A browser can't run scikit-learn, but a gradient boosting model is just
100 small decision trees plus some scaling numbers. We save those as JSON,
and the JavaScript in app.html walks the trees the same way Python does.

Run:  python export_model.py   (after train.py)
"""
import json

import joblib
import numpy as np
import pandas as pd

saved = joblib.load("model.joblib")
pipe = saved["model"]
prep = pipe.named_steps["prep"]
gbm = pipe.named_steps["model"]

num_pipe = prep.named_transformers_["num"]
onehot = prep.named_transformers_["cat"]

trees = []
for (predictor,) in gbm._predictors:
    # one row per node: [feature, threshold, left child, right child, missing goes left, leaf value or null]
    trees.append([
        [int(n["feature_idx"]), float(n["num_threshold"]), int(n["left"]),
         int(n["right"]), int(n["missing_go_to_left"]),
         round(float(n["value"]), 2) if n["is_leaf"] else None]
        for n in predictor.nodes
    ])

export = {
    "name": saved["name"],
    "mae": round(float(saved["mae"])),
    "numeric": list(prep.transformers_[0][2]),
    "fill": num_pipe.named_steps["fill"].statistics_.tolist(),
    "mean": num_pipe.named_steps["scale"].mean_.tolist(),
    "scale": num_pipe.named_steps["scale"].scale_.tolist(),
    "categories": onehot.categories_[0].tolist(),
    "baseline": float(np.ravel(gbm._baseline_prediction)[0]),
    "trees": trees,
}


# Check: re-run the exported trees in plain Python and compare with sklearn
def predict(row):
    x = [(row[c] - m) / s for c, m, s in zip(export["numeric"], export["mean"], export["scale"])]
    x += [1.0 if row["ocean_proximity"] == c else 0.0 for c in export["categories"]]
    total = export["baseline"]
    for tree in export["trees"]:
        i = 0
        while tree[i][5] is None:
            f, thr, left, right = tree[i][:4]
            i = left if x[f] <= thr else right
        total += tree[i][5]
    return total


sample = pd.read_csv("data/california_housing.csv").dropna().sample(200, random_state=0)
sample["rooms_per_household"] = sample["total_rooms"] / sample["households"]
sample["bedrooms_per_room"] = sample["total_bedrooms"] / sample["total_rooms"]
sample["people_per_household"] = sample["population"] / sample["households"]
cols = export["numeric"] + ["ocean_proximity"]
diff = max(abs(predict(r) - p) for r, p in zip(sample[cols].to_dict("records"), pipe.predict(sample[cols])))
print(f"Biggest gap between JSON trees and sklearn on 200 rows: ${diff:,.2f}")

with open("model.json", "w") as f:
    json.dump(export, f, separators=(",", ":"))
print(f"Saved model.json ({len(export['trees'])} trees)")

# Map points for the page: a random 6,000 blocks (lon, lat, price in $k, ocean category index)
df = pd.read_csv("data/california_housing.csv").sample(6000, random_state=1)
cats = export["categories"]
points = [[round(r.longitude, 2), round(r.latitude, 2), round(r.median_house_value / 1000),
           cats.index(r.ocean_proximity)] for r in df.itertuples()]

# Build app.html: paste the model and map points into the template
html = open("app_template.html").read()
html = html.replace("/*MODEL*/null", json.dumps(export, separators=(",", ":")))
html = html.replace("/*POINTS*/null", json.dumps(points, separators=(",", ":")))
with open("app.html", "w") as f:
    f.write(html)
print("Saved app.html (open it in any browser)")
