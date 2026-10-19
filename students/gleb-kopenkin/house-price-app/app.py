"""Step 4: a small web app that uses the trained model.

Run:  streamlit run app.py   (run train.py first)
"""
import joblib
import pandas as pd
import streamlit as st

saved = joblib.load("model.joblib")
model = saved["model"]

st.title("California house price predictor")
st.caption(
    f"Model: {saved['name']}. On houses it never saw, it is off by about "
    f"${saved['mae']:,.0f} on average. Prices are 1990 census values."
)

st.subheader("Location")
ocean = st.selectbox("Distance to ocean", ["<1H OCEAN", "INLAND", "NEAR OCEAN", "NEAR BAY", "ISLAND"])
col1, col2 = st.columns(2)
lat = col1.number_input("Latitude", 32.5, 42.0, 34.05, help="Los Angeles is about 34.05")
lon = col2.number_input("Longitude", -124.5, -114.0, -118.25, help="Los Angeles is about -118.25")

st.subheader("Neighbourhood")
income = st.slider("Median household income ($ thousands / year)", 5, 150, 40)
age = st.slider("Median age of houses (years)", 1, 52, 25)
rooms = st.slider("Rooms per household", 1.0, 10.0, 5.0, 0.1)
bedrooms = st.slider("Bedrooms per household", 0.5, 5.0, 1.0, 0.1)
people = st.slider("People per household", 1.0, 6.0, 3.0, 0.1)

# Build one row with the same columns the model was trained on
row = pd.DataFrame([{
    "longitude": lon,
    "latitude": lat,
    "housing_median_age": age,
    "median_income": income / 10,  # dataset stores income in $10,000s
    "rooms_per_household": rooms,
    "bedrooms_per_room": bedrooms / rooms,
    "people_per_household": people,
    "ocean_proximity": ocean,
}])

price = model.predict(row)[0]
st.metric("Predicted median house value", f"${price:,.0f}")

with st.expander("Try this"):
    st.write(
        "Move only the income slider and watch the price. Then change the location: "
        "Fresno (36.74, -119.79, INLAND) vs San Francisco (37.77, -122.42, NEAR BAY). "
        "Income and location drive most of the prediction."
    )
