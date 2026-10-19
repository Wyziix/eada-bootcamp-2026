#!/usr/bin/env python3
"""Export the saved Ames pipeline for browser inference; never refit the model.

The portal fills unasked features from a representative 2006–2009 training
property in the selected neighborhood/type. Simplified-form accuracy is scored
separately on 2010. Run after activating ~/myenv/bin/activate.
"""
from pathlib import Path
import hashlib
import json
import warnings

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "portal/public/assets"
QUALITY = [2, 4, 5, 7, 9]
NAMES = dict(zip(
    "Blmngtn Blueste BrDale BrkSide ClearCr CollgCr Crawfor Edwards Gilbert Greens GrnHill IDOTRR Landmrk MeadowV Mitchel NAmes NoRidge NPkVill NridgHt NWAmes OldTown SWISU Sawyer SawyerW Somerst StoneBr Timber Veenker".split(),
    ["Bloomington Heights", "Bluestem", "Briardale", "Brookside", "Clear Creek", "College Creek", "Crawford", "Edwards", "Gilbert", "Greens", "Green Hills", "Iowa DOT & Railroad", "Landmark", "Meadow Village", "Mitchell", "North Ames", "Northridge", "Northpark Villa", "Northridge Heights", "Northwest Ames", "Old Town", "South & West of ISU", "Sawyer", "Sawyer West", "Somerset", "Stone Brook", "Timberland", "Veenker"]))


def clean(v):
    if pd.isna(v):
        return None
    return v.item() if hasattr(v, "item") else v


def adapt(form, profiles):
    row = dict(profiles[form["neighborhood"]][form["type"]]["features"])
    area, year = form["area"], form["year"]
    fraction = row["2nd Flr SF"] / max(row["Gr Liv Area"], 1)
    row.update({"Neighborhood": form["neighborhood"], "Gr Liv Area": area,
                "Overall Qual": QUALITY[form["quality"] - 1], "Year Built": year,
                "Year Remod/Add": max(year, row["Year Remod/Add"]),
                "Bedroom AbvGr": form["bedrooms"], "Full Bath": form["bathrooms"],
                "Garage Cars": form["garage"], "Garage Area": form["garage"] * 240,
                "1st Flr SF": round(area * (1 - fraction)), "2nd Flr SF": round(area * fraction),
                "Low Qual Fin SF": 0})
    row["TotRms AbvGrd"] = max(form["bedrooms"] + 3, 4)
    if form["garage"] == 0:
        row.update({"Garage Type": "NA", "Garage Yr Blt": None, "Garage Finish": "NA", "Garage Qual": "NA", "Garage Cond": "NA"})
    elif not row.get("Garage Yr Blt"):
        row.update({"Garage Type": "Attchd", "Garage Yr Blt": year, "Garage Finish": "Unf", "Garage Qual": "TA", "Garage Cond": "TA"})
    return row


def export_hist_model(model, meta, saved):
    """Serialize either fitted histogram pipeline for identical browser inference."""
    pipe = model.regressor_
    pre, hist = pipe.named_steps["preprocess"], pipe.named_steps["model"]
    num = pre.named_transformers_["numeric"]
    imp, scale = num.named_steps["impute"], num.named_steps["scale"]
    enc = pre.named_transformers_["categorical"].named_steps["encode"]
    categorical = []
    base = [str(c[0]) for c in enc.categories_]
    offset = 0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        for i, col in enumerate(meta["categorical_columns"]):
            cats = [str(c) for c in enc.categories_[i]]
            inputs = np.array([base[:] for _ in range(len(cats) + 1)], dtype=object)
            inputs[:, i] = cats + ["__PORTAL_UNKNOWN__"]
            size = enc._n_features_outs[i]
            vectors = enc.transform(inputs)[:, offset:offset+size]
            indices = [int(np.argmax(v)) if v.any() else -1 for v in vectors]
            categorical.append({"column": col, "size": int(size), "mapping": dict(zip(cats, indices[:-1])), "unknown": indices[-1]})
            offset += size
    trees = []
    for stage in hist._predictors:
        nodes = stage[0].nodes
        assert not nodes["is_categorical"].any()
        trees.append([[float(n["value"]), int(n["feature_idx"]), float(n["num_threshold"]), int(n["left"]), int(n["right"]), int(n["is_leaf"]), int(n["missing_go_to_left"])] for n in nodes])
    exported = {"name": meta["selected_model"], "sha256": hashlib.sha256(saved.read_bytes()).hexdigest(),
                "numeric": meta["numeric_columns"], "medians": imp.statistics_.tolist(),
                "indicators": imp.indicator_.features_.tolist(), "mean": scale.mean_.tolist(),
                "scale": scale.scale_.tolist(), "categorical": categorical,
                "baseline": float(hist._baseline_prediction[0, 0]), "trees": trees}
    return exported


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    meta = json.loads((ROOT / "models/ames/model_metadata.json").read_text())
    saved = ROOT / "models/ames/best_model.joblib"
    model = joblib.load(saved)
    exported = export_hist_model(model, meta, saved)
    (OUT / "model.json").write_text(json.dumps(exported, separators=(",", ":"), allow_nan=False))
    raw = pd.read_csv(ROOT / "dat/ames/ames_housing.csv", dtype=str, keep_default_na=False)
    frame = raw[meta["feature_columns"]].apply(lambda c: c.str.strip().replace("", np.nan))
    for col in meta["numeric_columns"]:
        frame[col] = pd.to_numeric(frame[col])
    training = frame[frame["Yr Sold"].isin(meta["fit_years"])].copy()
    profiles = {}
    distance_cols = ["Gr Liv Area", "Overall Qual", "Year Built", "Bedroom AbvGr", "Full Bath", "Garage Cars"]
    for code in sorted(NAMES):
        profiles[code] = {}
        for kind in ["house", "townhouse"]:
            type_mask = training["Bldg Type"].eq("1Fam") if kind == "house" else training["Bldg Type"].isin(["Twnhs", "TwnhsE"])
            group = training[type_mask & training["Neighborhood"].eq(code)]
            count = len(group)
            if count == 0:
                group = training[type_mask]
            vals = group[distance_cols].fillna(group[distance_cols].median())
            dist = ((vals - vals.median()) / training[distance_cols].std()).pow(2).sum(axis=1)
            chosen = group.loc[dist.idxmin()]
            profiles[code][kind] = {"count": count, "features": {c: clean(chosen[c]) for c in meta["feature_columns"]}}
    neighborhoods = [{"code": c, "name": NAMES[c], "count": int(training.Neighborhood.eq(c).sum())} for c in sorted(NAMES, key=NAMES.get)]
    # Validate the actual simplified UX, rather than borrowing the full model's KPIs.
    test = frame[frame["Yr Sold"].eq(2010) & frame["Bldg Type"].isin(["1Fam", "Twnhs", "TwnhsE"])]
    forms = []
    for _, row in test.iterrows():
        forms.append({"neighborhood": row["Neighborhood"], "type": "house" if row["Bldg Type"] == "1Fam" else "townhouse",
                      "area": int(row["Gr Liv Area"]), "year": int(row["Year Built"]),
                      "quality": min(range(5), key=lambda i: abs(QUALITY[i] - row["Overall Qual"])) + 1,
                      "bedrooms": int(row["Bedroom AbvGr"]), "bathrooms": int(row["Full Bath"]),
                      "garage": int(row["Garage Cars"]) if pd.notna(row["Garage Cars"]) else 0})
    adapted = pd.DataFrame([adapt(f, profiles) for f in forms])[meta["feature_columns"]]
    for col in meta["numeric_columns"]:
        adapted[col] = pd.to_numeric(adapted[col])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        predictions = model.predict(adapted)
    actual = pd.to_numeric(raw.loc[test.index, "SalePrice"]).to_numpy()
    error = np.abs(predictions - actual)
    validation = {"test_year": 2010, "n": len(test), "mae": float(error.mean()),
                  "rmse": float(np.sqrt((error**2).mean())), "within20": float((error / actual <= .2).mean() * 100),
                  "note": "Descriptive 2010 evaluation of this simplified form. This holdout was already inspected in the original benchmark; it is not a new untouched test."}
    config = {"profiles": profiles, "neighborhoods": neighborhoods, "quality": QUALITY,
              "fit_count": len(training), "validation": validation,
              "source": "https://jse.amstat.org/v19n3/decock.pdf"}
    (OUT / "config.json").write_text(json.dumps(config, separators=(",", ":"), allow_nan=False))
    # Raw and adapted vectors cover preprocessing (including missing indicators),
    # target inverse transform, and all 341 original held-out records.
    all_test = frame[frame["Yr Sold"].eq(2010)]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        original_predictions = model.predict(all_test)
    fixtures = {"rows": [{c: clean(row[c]) for c in meta["feature_columns"]} for _, row in all_test.iterrows()],
                "predictions": original_predictions.tolist(), "forms": forms, "adapted_predictions": predictions.tolist()}
    fixture_path = ROOT / "portal/tests/fixtures.json"
    fixture_path.parent.mkdir(exist_ok=True)
    fixture_path.write_text(json.dumps(fixtures, separators=(",", ":"), allow_nan=False))
    print(json.dumps({"exported_model_bytes": (OUT / "model.json").stat().st_size, "simplified_form_validation": validation}, indent=2))


if __name__ == "__main__":
    main()
