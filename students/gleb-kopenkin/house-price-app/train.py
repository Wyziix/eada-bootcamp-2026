"""Step 2-3: train a model on California housing data and check how good it is.

Run:  python train.py
Output: model.joblib (used by app.py) and scores printed in the terminal.
"""
import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

# 1. Load data
df = pd.read_csv("data/california_housing.csv")

# 2. Clean: prices are capped at 500,001 in this dataset, so those rows are
#    not real prices. Drop them so the model doesn't learn the cap.
df = df[df["median_house_value"] < 500_000]

# 3. Feature engineering: the raw columns are totals for a whole block
#    (e.g. 3,000 rooms). Per-household numbers mean more and are what a
#    user can actually type into the app.
df["rooms_per_household"] = df["total_rooms"] / df["households"]
df["bedrooms_per_room"] = df["total_bedrooms"] / df["total_rooms"]
df["people_per_household"] = df["population"] / df["households"]

NUMERIC = [
    "longitude", "latitude", "housing_median_age", "median_income",
    "rooms_per_household", "bedrooms_per_room", "people_per_household",
]
CATEGORY = ["ocean_proximity"]
TARGET = "median_house_value"

X = df[NUMERIC + CATEGORY]
y = df[TARGET]

# 4. Split: train on 80%, keep 20% hidden to test the model honestly
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)

# 5. Preprocessing: fill missing values, scale numbers, turn text into 0/1 columns
prep = ColumnTransformer([
    ("num", Pipeline([
        ("fill", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
    ]), NUMERIC),
    ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORY),
])

models = {
    "Linear regression (baseline)": LinearRegression(),
    "Gradient boosting": HistGradientBoostingRegressor(random_state=42),
}

# 6. Train each model and score it on the hidden 20%
best_name, best_pipe, best_mae = None, None, float("inf")
for name, model in models.items():
    pipe = Pipeline([("prep", prep), ("model", model)])
    pipe.fit(X_train, y_train)
    pred = pipe.predict(X_test)
    mae = mean_absolute_error(y_test, pred)
    r2 = r2_score(y_test, pred)
    print(f"{name:30s}  avg error: ${mae:,.0f}   R2: {r2:.2f}")
    if mae < best_mae:
        best_name, best_pipe, best_mae = name, pipe, mae

# 7. Save the best model so the app can use it without retraining
joblib.dump({"model": best_pipe, "name": best_name, "mae": best_mae}, "model.joblib")
print(f"\nSaved '{best_name}' to model.joblib")
