# House price app

## Your Boston file, decoded

506 rows, one per Boston neighbourhood (1970s). 14 columns, no header. Labeled copy: `data/boston_with_headers.csv`.

| Column | Meaning |
|---|---|
| CRIM | Crime rate per person |
| ZN | % of land zoned for big residential lots |
| INDUS | % of land used by industry (non-retail business) |
| CHAS | 1 if next to the Charles River, else 0 |
| NOX | Air pollution (nitric oxides, parts per 10 million) |
| RM | Average rooms per home |
| AGE | % of homes built before 1940 |
| DIS | Distance to 5 Boston job centres |
| RAD | Access to highways (index, higher = better) |
| TAX | Property tax per $10,000 of value |
| PTRATIO | Pupils per teacher in local schools |
| B | Formula based on the share of Black residents (see below) |
| LSTAT | % of lower-income residents |
| MEDV | **The target:** median home price, in $1,000s (24.0 = $24,000) |

**The B problem:** B = 1000 × (share of Black residents − 0.63)². The original authors built it assuming race affects house prices. Using it means your model prices homes partly by the race of the neighbours. scikit-learn removed this dataset in 2023 for that reason.

## Why I switched to California

- Real column names you can read, prices in plain dollars.
- 20,640 rows instead of 506, so results are more stable.
- It has the problems real data has: missing values, a text column, prices capped at $500,001. Good practice.
- No race column.

File: `data/california_housing.csv` (1990 census, one row per block group).

## Learning path

1. **Explore (EDA)**: `python eda.py` prints the findings and saves 5 charts in `eda_output/`.
2. **Train**: `train.py` cleans data, builds features, trains 2 models.
3. **Evaluate**: compare on 20% of data the model never saw. Linear regression: off by ~$46.5k. Gradient boosting: off by ~$29k (R² 0.81). Keep the better one.
4. **App**: `python export_model.py` turns the model into JSON and builds `app.html`, a page that runs the model in any browser (double-click to open). `app.py` is the same idea in Streamlit.
5. **Compare models**: `python compare_models.py` trains 6 algorithms (linear regression, decision tree, random forest, XGBoost, neural network, histogram gradient boosting), scores them and builds `model_report.html`. Takes about a minute.
6. **Website**: `portal/` holds the price portal.
   - `python build_california_portal.py` trains a model with common-sense rules (richer area or more space never lowers the price) and builds `california_portal.html`. The page turns 1990 predictions into 2026 prices with each metro's FHFA House Price Index growth (April 1990 → April 2026, figures from FRED, stored in the template).
   - `python train_portal.py` builds `portal.html`, a Seattle-area version trained on 21,613 real single-home sales. It can ask for m², bathrooms and build quality, which the California data doesn't have.
7. **Next**: tune the best model, explain which inputs matter, deploy free on Streamlit Community Cloud.

## Run it on your laptop

```
pip install -r requirements.txt
python eda.py
python train.py
python export_model.py   # builds app.html
python compare_models.py  # builds model_report.html
streamlit run app.py     # optional Python version
```
