#!/usr/bin/env python3
"""Explore the full Ames Housing CSV and write a standalone HTML report.

Run from any directory; defaults are relative to this project, not the shell.
No source records are changed, imputed, filtered, or used to train a model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import plotly
import plotly.graph_objects as go
import plotly.io as pio
from jinja2 import Environment, FileSystemLoader, select_autoescape
from plotly.offline import get_plotlyjs
from plotly.subplots import make_subplots


ROOT = Path(__file__).resolve().parents[1]
TARGET = "SalePrice"
IDENTIFIERS = {"Order", "PID"}
REQUIRED = {
    TARGET, "Order", "PID", "Gr Liv Area", "Overall Qual", "Neighborhood",
    "Full Bath", "Year Built", "Garage Cars", "Garage Yr Blt", "Yr Sold",
    "Mo Sold", "Sale Condition", "Lot Frontage", "MS SubClass",
}
BLUE = "#2257a5"
TEAL = "#15786d"
ORANGE = "#c67613"
RED = "#bd4040"
STARTER = ["Gr Liv Area", "Full Bath", "Year Built", "Neighborhood", "Garage Cars"]
ALIASES = {
    "Exterior 1st": "Exterior 1", "Exterior 2nd": "Exterior 2",
    "Bedroom AbvGr": "Bedroom", "Kitchen AbvGr": "Kitchen",
}
YEAR_COLUMNS = {"Year Built", "Year Remod/Add", "Garage Yr Blt", "Yr Sold"}


def key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def read_dictionary(path: Path) -> dict:
    """Read semantic types, descriptions, and category labels from the codebook."""
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"^([^\n(]+?)\s*\((Nominal|Ordinal|Discrete|Continuous)\)\s*:\s*([^\n]*)",
        re.MULTILINE,
    )
    matches = list(pattern.finditer(text))
    definitions = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[match.end():end].split("SPECIAL NOTES:")[0]
        levels = {}
        for line in block.splitlines():
            level = re.match(r"^\s+([A-Za-z0-9.&/-]+)\s+(.+?)\s*$", line)
            if level:
                levels[level.group(1)] = level.group(2)
        definitions[key(match.group(1))] = {
            "kind": match.group(2), "description": match.group(3).strip(),
            "levels": levels,
        }
    return definitions


def definition_for(column: str, definitions: dict) -> dict:
    definition = definitions.get(key(ALIASES.get(column, column)), {
        "kind": "Unspecified", "description": "See the source data dictionary.", "levels": {},
    })
    if column == "Neighborhood":
        # The source guide spells North Ames 'Names'; observations use 'NAmes'.
        return {**definition, "levels": {
            "NAmes" if code == "Names" else code: label
            for code, label in definition["levels"].items()
        }}
    return definition


def load_data(path: Path, definitions: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Keep IDs/category codes as text and preserve documented NA categories."""
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    absent = REQUIRED.difference(raw.columns)
    if absent:
        raise ValueError(
            "Use the full Ames CSV with its original column names. Missing columns: "
            + ", ".join(sorted(absent))
        )
    if raw.empty:
        raise ValueError("The input CSV has no observations.")
    undocumented = [column for column in raw if definition_for(column, definitions)["kind"] == "Unspecified"]
    if undocumented:
        raise ValueError("The dictionary has no definition for: " + ", ".join(undocumented))
    # The source contains padded category labels such as 'WD '. Trim only in memory.
    text = raw.apply(lambda series: series.str.strip())
    data = pd.DataFrame(index=text.index)
    for column in text:
        kind = definition_for(column, definitions)["kind"]
        numeric = kind in {"Continuous", "Discrete"} or column in {"Overall Qual", "Overall Cond"}
        if numeric and column not in IDENTIFIERS:
            data[column] = pd.to_numeric(text[column].replace("", np.nan), errors="raise")
        else:
            data[column] = text[column].replace("", np.nan)
    if data[TARGET].isna().any() or (data[TARGET] <= 0).any():
        raise ValueError("SalePrice must be present, numeric, and positive in every row.")
    return raw, data


def display(value, column: str | None = None) -> str:
    if pd.isna(value):
        return "Blank"
    if column in YEAR_COLUMNS:
        return f"{float(value):.0f}"
    if isinstance(value, (float, np.floating)):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    if isinstance(value, (int, np.integer)):
        return f"{value:,}"
    return str(value)


def profile_columns(data: pd.DataFrame, definitions: dict) -> list[dict]:
    records = []
    for column in data:
        values = data[column]
        definition = definition_for(column, definitions)
        numeric = pd.api.types.is_numeric_dtype(values)
        role = "Target" if column == TARGET else "Identifier" if column in IDENTIFIERS else "Input"
        documented_absence = definition["levels"].get("NA")
        examples = [display(value, column) for value in values.dropna().drop_duplicates().head(3)]
        records.append({
            "name": column, "kind": definition["kind"], "role": role,
            "description": definition["description"],
            "levels": definition["levels"],
            "missing": int(values.isna().sum()),
            "missing_pct": float(values.isna().mean() * 100),
            "absence": int(values.eq("NA").sum()) if documented_absence else 0,
            "absence_label": documented_absence or "—",
            "unique": int(values.nunique()), "examples": ", ".join(examples),
            "range": f"{display(values.min(), column)} to {display(values.max(), column)}" if numeric else "—",
            "median": display(values.median(), column) if numeric else "—",
        })
    return records


def table_records(frame: pd.DataFrame) -> list[dict]:
    return [{str(column): display(value, str(column)) for column, value in row.items()}
            for row in frame.to_dict("records")]


def make_analysis(raw: pd.DataFrame, data: pd.DataFrame, definitions: dict) -> dict:
    prices = data[TARGET]
    profile = profile_columns(data, definitions)
    numeric = data.select_dtypes(include="number")
    correlations = numeric.corr(method="pearson", min_periods=3)[TARGET].drop(TARGET).dropna()
    correlations = correlations.reindex(correlations.abs().sort_values(ascending=False).index)
    q1, q3 = prices.quantile([0.25, 0.75])
    iqr = q3 - q1
    lower, upper = float(q1 - 1.5 * iqr), float(q3 + 1.5 * iqr)
    area_review = data.loc[data["Gr Liv Area"] > 4000,
                           ["Order", "Gr Liv Area", TARGET, "Sale Condition"]]
    garage_review = data.loc[data["Garage Yr Blt"] > data["Yr Sold"],
                             ["Order", "Garage Yr Blt", "Yr Sold", TARGET]]
    quality_checks = [
        {"check": "Exact duplicate rows", "count": int(raw.duplicated().sum()),
         "meaning": "Repeated complete records, after keeping the first occurrence."},
        {"check": "Repeated parcel identifiers (PID)", "count": int(data["PID"].duplicated().sum()),
         "meaning": "Repeated properties could leak information across a random split."},
        {"check": "Missing or non-positive sale prices", "count": int((prices.isna() | prices.le(0)).sum()),
         "meaning": "The supervised learning target must be known and positive."},
        {"check": "Missing living area", "count": int(data["Gr Liv Area"].isna().sum()),
         "meaning": "Living area is a proposed application input."},
        {"check": "Non-positive recorded living area", "count": int(data["Gr Liv Area"].le(0).sum()),
         "meaning": "Review whether the record represents a habitable dwelling."},
        {"check": "Construction year after sale year", "count": int(data["Year Built"].gt(data["Yr Sold"]).sum()),
         "meaning": "Check the dates and whether this represents a sale before completion."},
        {"check": "Garage construction year after sale year", "count": len(garage_review),
         "meaning": "Review the source dates before deciding on a correction."},
        {"check": "Recorded sale month outside 1–12", "count": int((data["Mo Sold"].notna() & ~data["Mo Sold"].between(1, 12)).sum()),
         "meaning": "Sale months should be within the calendar range."},
    ]
    neighborhood = data.groupby("Neighborhood", observed=True)[TARGET].agg(["size", "median"]).reset_index()
    neighborhood.columns = ["Neighborhood", "Homes", "Median price"]
    neighborhood = neighborhood.sort_values("Median price")
    years = data.groupby("Yr Sold", observed=True)[TARGET].agg(["size", "median"]).reset_index()
    counts = {kind: sum(row["kind"] == kind and row["role"] == "Input" for row in profile)
              for kind in ("Nominal", "Ordinal", "Discrete", "Continuous")}
    stats = {
        "rows": len(data), "columns": len(data.columns),
        "input_columns": sum(row["role"] == "Input" for row in profile),
        "identifiers": sum(row["role"] == "Identifier" for row in profile),
        "price_min": float(prices.min()), "price_max": float(prices.max()),
        "price_mean": float(prices.mean()), "price_median": float(prices.median()),
        "price_q1": float(q1), "price_q3": float(q3), "price_skew": float(prices.skew()),
        "blank_cells": int(data.isna().sum().sum()),
        "rows_with_blanks": int(data.isna().any(axis=1).sum()),
        "columns_with_blanks": int(data.isna().any().sum()),
        "documented_absence_cells": sum(row["absence"] for row in profile),
        "year_min": int(data["Yr Sold"].min()), "year_max": int(data["Yr Sold"].max()),
        "neighborhoods": int(data["Neighborhood"].nunique()),
        "price_iqr_low": lower, "price_iqr_high": upper,
        "price_iqr_flagged": int((prices.lt(lower) | prices.gt(upper)).sum()),
        "large_homes": len(area_review), "garage_year_flags": len(garage_review),
        "starter_blank_cells": int(data[STARTER].isna().sum().sum()),
        "illustrative_test_rows": int(np.ceil(len(data) * 0.2)),
        "illustrative_train_rows": len(data) - int(np.ceil(len(data) * 0.2)),
        "input_types": counts,
    }
    findings = [
        {"title": "Price has a long upper tail",
         "text": f"The median is ${stats['price_median']:,.0f}; the mean is ${stats['price_mean']:,.0f}. "
                 "Expensive homes pull the mean upward. Compare raw-price and log-price models using validation."},
        {"title": "Quality and size deserve an early look",
         "text": "; ".join(f"{name}: r = {value:.2f}" for name, value in correlations.head(3).items())
                 + ". These are descriptive associations, not model accuracy or evidence of causation."},
        {"title": "Absence and unknown values need different treatment",
         "text": f"There are {stats['blank_cells']:,} blank cells and {stats['documented_absence_cells']:,} "
                 "literal NA entries documented as absent features. Cross-check related columns when interpreting blanks."},
        {"title": "Review unusual records before training",
         "text": f"{len(area_review)} homes exceed 4,000 sq ft. {len(garage_review)} garage construction dates "
                 "are later than the sale year. The report retains and lists these records for review."},
    ]
    return {"stats": stats, "profile": profile, "correlations": correlations,
            "neighborhood": neighborhood, "years": years, "checks": quality_checks,
            "area_review": area_review, "garage_review": garage_review, "findings": findings}


def style(figure: go.Figure, *, height: int = 400) -> go.Figure:
    figure.update_layout(
        template="plotly_white", height=height, autosize=True,
        font={"family": "Arial, sans-serif", "size": 12, "color": "#24344b"},
        paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
        margin={"l": 70, "r": 30, "t": 45, "b": 65},
        colorway=[BLUE, TEAL, ORANGE, RED],
        legend={"orientation": "h", "y": 1.16, "x": 0},
    )
    figure.update_xaxes(gridcolor="#edf1f5", zeroline=False)
    figure.update_yaxes(gridcolor="#edf1f5", zeroline=False)
    return figure


def build_figures(data: pd.DataFrame, analysis: dict) -> dict[str, go.Figure]:
    figures = {}
    prices = data[TARGET]

    distribution = make_subplots(rows=1, cols=2, subplot_titles=("Recorded prices", "Same prices on a log₁₀ scale"))
    distribution.add_trace(go.Histogram(x=prices, nbinsx=45, marker_color=BLUE, showlegend=False), row=1, col=1)
    distribution.add_trace(go.Histogram(x=np.log10(prices), nbinsx=40, marker_color=TEAL, showlegend=False), row=1, col=2)
    distribution.update_xaxes(title_text="Sale price (historical USD)", tickprefix="$", tickformat=",.0f", row=1, col=1)
    distribution.update_xaxes(title_text="log₁₀(sale price)", row=1, col=2)
    distribution.update_yaxes(title_text="Homes", row=1, col=1)
    distribution.update_yaxes(title_text="Homes", row=1, col=2)
    figures["price_distribution"] = style(distribution)

    profile = pd.DataFrame(analysis["profile"])
    missing = profile.loc[profile["missing"] > 0].nlargest(12, "missing").sort_values("missing")
    absence = profile.loc[profile["absence"] > 0].nlargest(10, "absence").sort_values("absence")
    completeness = make_subplots(rows=1, cols=2, horizontal_spacing=0.24,
                                subplot_titles=("Blank cells: largest 12 counts", "Documented absent features: largest 10 counts"))
    completeness.add_trace(go.Bar(x=missing["missing"], y=missing["name"], orientation="h", marker_color=ORANGE,
                                  showlegend=False, hovertemplate="%{y}: %{x:,} blank cells<extra></extra>"), row=1, col=1)
    completeness.add_trace(go.Bar(x=absence["absence"], y=absence["name"], orientation="h", marker_color=BLUE,
                                  showlegend=False, hovertemplate="%{y}: %{x:,} documented NA categories<extra></extra>"), row=1, col=2)
    completeness.update_xaxes(title_text="Number of homes")
    figures["completeness"] = style(completeness, height=460)

    strongest = analysis["correlations"].head(12).sort_values()
    correlation = go.Figure(go.Bar(x=strongest.values, y=strongest.index, orientation="h", marker_color=BLUE,
                                   text=[f"{value:.2f}" for value in strongest.values], textposition="outside",
                                   hovertemplate="%{y}: r = %{x:.3f}<extra></extra>"))
    correlation.update_xaxes(title_text="Pearson correlation with sale price", range=[min(-0.05, float(strongest.min()) - 0.1), 1])
    figures["price_correlations"] = style(correlation, height=440)

    living = go.Figure()
    for selected, name, color in ((data["Gr Liv Area"].le(4000), "Up to 4,000 sq ft", BLUE),
                                   (data["Gr Liv Area"].gt(4000), "Over 4,000 sq ft: review", RED)):
        subset = data.loc[selected]
        living.add_trace(go.Scatter(
            x=subset["Gr Liv Area"], y=subset[TARGET], mode="markers", name=name,
            marker={"color": color, "size": 6 if color == BLUE else 10, "opacity": 0.6 if color == BLUE else 0.95},
            customdata=subset[["Order", "Neighborhood", "Overall Qual", "Sale Condition"]].astype(str).values,
            hovertemplate="Record %{customdata[0]}<br>%{x:,} sq ft · $%{y:,.0f}<br>Neighborhood: %{customdata[1]}"
                          "<br>Quality: %{customdata[2]}<br>Sale condition: %{customdata[3]}<extra></extra>",
        ))
    living.add_vline(x=4000, line_dash="dot", line_color=RED)
    living.update_xaxes(title_text="Above-ground living area (sq ft)")
    living.update_yaxes(title_text="Sale price (historical USD)", tickprefix="$", tickformat=",.0f")
    figures["living_area"] = style(living, height=440)

    quality = go.Figure()
    for rating, subset in data.groupby("Overall Qual", observed=True):
        quality.add_trace(go.Box(y=subset[TARGET], name=f"{int(rating)} (n={len(subset)})", marker_color=BLUE,
                                boxpoints="outliers", showlegend=False))
    quality.update_xaxes(title_text="Overall material / finish quality: 1 = very poor; 10 = very excellent")
    quality.update_yaxes(title_text="Sale price (historical USD)", tickprefix="$", tickformat=",.0f")
    figures["quality"] = style(quality, height=420)

    neighborhood = analysis["neighborhood"]
    neighborhoods = go.Figure(go.Bar(
        x=neighborhood["Median price"], y=neighborhood["Neighborhood"], orientation="h", marker_color=TEAL,
        customdata=neighborhood[["Homes"]].values,
        hovertemplate="%{y}<br>Median: $%{x:,.0f}<br>Homes: %{customdata[0]}<extra></extra>",
    ))
    neighborhoods.update_xaxes(title_text="Median sale price (historical USD)", tickprefix="$", tickformat=",.0f")
    neighborhoods.update_yaxes(title_text="Neighborhood code", dtick=1)
    figures["neighborhoods"] = style(neighborhoods, height=max(500, 23 * len(neighborhood)))

    columns = [TARGET] + analysis["correlations"].head(9).index.tolist()
    matrix = data[columns].corr()
    heatmap = go.Figure(go.Heatmap(
        z=matrix.values, x=matrix.columns, y=matrix.index, zmin=-1, zmax=1,
        colorscale=[[0, "#b34b3c"], [0.5, "#f6f7fa"], [1, BLUE]],
        text=np.round(matrix.values, 2), texttemplate="%{text:.2f}", textfont={"size": 10},
        hovertemplate="%{y} / %{x}: r = %{z:.3f}<extra></extra>", colorbar={"title": "r"},
    ))
    heatmap.update_xaxes(tickangle=-40, showgrid=False)
    heatmap.update_yaxes(autorange="reversed", showgrid=False)
    figures["feature_overlap"] = style(heatmap, height=520)

    years = analysis["years"]
    by_year = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.18,
                           subplot_titles=("Recorded sales", "Median recorded sale price"))
    by_year.add_trace(go.Bar(x=years["Yr Sold"], y=years["size"], marker_color=BLUE, showlegend=False), row=1, col=1)
    by_year.add_trace(go.Scatter(x=years["Yr Sold"], y=years["median"], mode="lines+markers", line_color=TEAL,
                                showlegend=False, hovertemplate="%{x}: $%{y:,.0f}<extra></extra>"), row=2, col=1)
    by_year.update_xaxes(dtick=1)
    by_year.update_xaxes(title_text="Sale year", row=2, col=1)
    by_year.update_yaxes(title_text="Homes", row=1, col=1)
    by_year.update_yaxes(title_text="Median price", tickprefix="$", tickformat=",.0f", row=2, col=1)
    figures["sale_year"] = style(by_year, height=510)

    conditions = go.Figure()
    for condition, subset in data.groupby("Sale Condition", observed=True):
        conditions.add_trace(go.Box(y=subset[TARGET], name=f"{condition} (n={len(subset)})", marker_color=TEAL,
                                   boxpoints="outliers", showlegend=False))
    conditions.update_xaxes(title_text="Recorded sale condition")
    conditions.update_yaxes(title_text="Sale price (historical USD)", tickprefix="$", tickformat=",.0f")
    figures["sale_conditions"] = style(conditions, height=430)
    return figures


def render_report(input_path: Path, dictionary_path: Path, metadata_path: Path, output_path: Path) -> dict:
    definitions = read_dictionary(dictionary_path)
    raw, data = load_data(input_path, definitions)
    analysis = make_analysis(raw, data, definitions)
    figures = build_figures(data, analysis)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    charts = {name: pio.to_html(figure, full_html=False, include_plotlyjs=False, div_id=f"chart-{name}",
                                config={"displaylogo": False, "responsive": True, "scrollZoom": False})
              for name, figure in figures.items()}
    environment = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"),
                              autoescape=select_autoescape(default=True))
    environment.filters["integer"] = lambda value: f"{value:,.0f}"
    environment.filters["money"] = lambda value: f"${value:,.0f}"
    generated = datetime.now(ZoneInfo("Europe/Madrid")).isoformat(timespec="seconds")
    digest = hashlib.sha256(input_path.read_bytes()).hexdigest()
    summary = {
        "generated_at": generated, "input_file": input_path.name, "input_sha256": digest,
        "stats": analysis["stats"], "quality_checks": analysis["checks"],
        "correlations": {name: float(value) for name, value in analysis["correlations"].items()},
        "columns": analysis["profile"], "chart_count": len(charts),
        "area_review": table_records(analysis["area_review"]),
        "garage_year_review": table_records(analysis["garage_review"]),
    }
    html = environment.get_template("ames_eda.html.j2").render(
        **analysis, charts=charts, plotly_js=get_plotlyjs(), metadata=metadata,
        generated=generated, input_name=input_path.name, input_sha256=digest,
        versions={"Python": sys.version.split()[0], "pandas": pd.__version__, "NumPy": np.__version__, "Plotly": plotly.__version__},
        summary_json=json.dumps(summary, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c"),
        sample=table_records(data[["Order"] + STARTER + [TARGET]].head(6)),
        sample_headers=["Order"] + STARTER + [TARGET],
        area_rows=table_records(analysis["area_review"]),
        garage_rows=table_records(analysis["garage_review"]),
        missing_columns=sorted((row for row in analysis["profile"] if row["missing"]), key=lambda row: -row["missing"]),
        numeric_summary=table_records(data.select_dtypes(include="number").describe().T.reset_index(names="Column")),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "dat/ames/ames_housing.csv", help="Full Ames CSV with original column names")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/ames_eda.html", help="Standalone HTML report")
    parser.add_argument("--dictionary", type=Path, default=ROOT / "dat/ames/data_description.txt", help="UTF-8 Ames data dictionary")
    parser.add_argument("--metadata", type=Path, default=ROOT / "dat/ames/source.json", help="Optional source provenance JSON")
    args = parser.parse_args()
    if args.output.resolve() in {args.input.resolve(), args.dictionary.resolve(), args.metadata.resolve()}:
        parser.error("The report output must not overwrite a source file.")
    if args.output.suffix.lower() not in {".html", ".htm"}:
        parser.error("The output filename must end in .html or .htm.")
    try:
        summary = render_report(args.input, args.dictionary, args.metadata, args.output)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"EDA failed: {error}\n")
    print(f"Report: {args.output.resolve()}")
    print(f"Analyzed {summary['stats']['rows']:,} sales and {summary['stats']['columns']} columns; {summary['chart_count']} charts.")
    print(f"Median price: ${summary['stats']['price_median']:,.0f}; blank cells: {summary['stats']['blank_cells']:,}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
