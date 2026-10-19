"""Step 1: Exploratory Data Analysis (EDA) of the California housing data.

Run:  python eda.py
Output: findings printed in the terminal + charts saved in eda_output/
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # save charts to files, no window needed
import matplotlib.pyplot as plt
import pandas as pd

OUT = Path("eda_output")
OUT.mkdir(exist_ok=True)
TARGET = "median_house_value"

df = pd.read_csv("data/california_housing.csv")


def section(title):
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


# 1. Size and shape
section("1. What does the data look like?")
print(f"{len(df):,} rows (one per neighbourhood block), {df.shape[1]} columns")
print(df.head())
print("\nColumn types:")
print(df.dtypes)

# 2. Missing values
section("2. Missing values")
missing = df.isna().sum()
print(missing[missing > 0])
print("-> total_bedrooms has gaps. train.py fills them with the median.")

# 3. Basic stats
section("3. Summary statistics")
print(df.describe().T.round(2))

# 4. The target: house prices
section("4. House prices (the thing we predict)")
p = df[TARGET]
print(f"Median price: ${p.median():,.0f}")
print(f"Cheapest: ${p.min():,.0f}   Most expensive: ${p.max():,.0f}")
capped = (p >= 500_000).sum()
print(f"{capped} blocks ({capped / len(df):.1%}) sit exactly at $500,001.")
print("-> That's a cap, not a real price. train.py drops these rows.")

fig, ax = plt.subplots(figsize=(8, 4))
ax.hist(p, bins=50, color="#3b6ea5")
ax.set_title("Distribution of house prices (spike at the right = $500k cap)")
ax.set_xlabel("Median house value ($)")
ax.set_ylabel("Number of blocks")
fig.tight_layout()
fig.savefig(OUT / "1_price_distribution.png", dpi=120)

# 5. Which numbers move with price? (correlation)
section("5. Correlation with price (-1 to +1)")
corr = df.select_dtypes("number").corr()[TARGET].drop(TARGET).sort_values()
print(corr.round(2))
print("-> median_income is by far the strongest: richer areas, pricier homes.")

fig, ax = plt.subplots(figsize=(8, 4))
ax.barh(corr.index, corr.values, color=["#c0504d" if v < 0 else "#3b6ea5" for v in corr.values])
ax.set_title("How strongly each column moves with price")
ax.set_xlabel("Correlation with median house value")
fig.tight_layout()
fig.savefig(OUT / "2_correlation.png", dpi=120)

# 6. Income vs price
fig, ax = plt.subplots(figsize=(7, 5))
ax.scatter(df["median_income"] * 10_000, p, s=2, alpha=0.3, color="#3b6ea5")
ax.set_title("Income vs house price")
ax.set_xlabel("Median household income ($)")
ax.set_ylabel("Median house value ($)")
fig.tight_layout()
fig.savefig(OUT / "3_income_vs_price.png", dpi=120)

# 7. Location: ocean proximity
section("6. Price by distance to the ocean")
by_ocean = df.groupby("ocean_proximity")[TARGET].agg(["count", "median"]).sort_values("median")
print(by_ocean.round(0))
print("-> INLAND is much cheaper. ISLAND has only 5 rows, too few to trust.")

fig, ax = plt.subplots(figsize=(8, 4))
ax.bar(by_ocean.index, by_ocean["median"], color="#3b6ea5")
ax.set_title("Median house value by ocean proximity")
ax.set_ylabel("Median house value ($)")
fig.tight_layout()
fig.savefig(OUT / "4_ocean_proximity.png", dpi=120)

# 8. Map of prices
fig, ax = plt.subplots(figsize=(7, 7))
sc = ax.scatter(df["longitude"], df["latitude"], c=p, s=3, cmap="viridis")
fig.colorbar(sc, label="Median house value ($)")
ax.set_title("Prices on the map: coast (LA, San Francisco) is expensive")
ax.set_xlabel("Longitude")
ax.set_ylabel("Latitude")
fig.tight_layout()
fig.savefig(OUT / "5_price_map.png", dpi=120)

# 9. Engineered features: do per-household numbers help?
section("7. New features (built from the raw totals)")
df["rooms_per_household"] = df["total_rooms"] / df["households"]
df["bedrooms_per_room"] = df["total_bedrooms"] / df["total_rooms"]
df["people_per_household"] = df["population"] / df["households"]
new = ["rooms_per_household", "bedrooms_per_room", "people_per_household"]
print(df[new + [TARGET]].corr()[TARGET].drop(TARGET).round(2))
print("-> bedrooms_per_room (-0.26) beats total_bedrooms (0.05): ratios carry more signal.")

section("Done")
print(f"Charts saved in {OUT.resolve()}")
