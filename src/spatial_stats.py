"""Stop-level spatial analysis: hot spots, spatial autocorrelation and spatial regression.

Usage:
    python src/spatial_stats.py

Needs clean.py and walksheds.py to have run first. The unit of analysis is the
timepoint stop (where reliability is actually measured), with demographics
from that stop's street-network walkshed. Writes:
  results/spatial_regression.txt      model output and diagnostics
  results/stop_reliability.csv        one row per stop, without geometry
  data/processed/gis/stops.gpkg       the same, as points for ArcGIS Pro

Steps:
  1. Getis-Ord Gi* hot spot analysis on stop on-time rates, the same statistic
     as ArcGIS Pro's Hot Spot Analysis tool, with a false discovery rate
     correction for testing many stops at once.
  2. Global Moran's I: do nearby stops have similar reliability?
  3. OLS of on-time rate on walkshed car-free share and income, with controls,
     plus Lagrange multiplier tests for spatial dependence in the residuals.
  4. If those tests call for it, a spatial error or spatial lag model.
"""

from pathlib import Path

import duckdb
import geopandas as gpd
import numpy as np
import pandas as pd
from esda.getisord import G_Local
from esda.moran import Moran
from libpysal.weights import KNN
from spreg import ML_Error, ML_Lag, OLS

import equity

ROOT = Path(__file__).resolve().parents[1]
TIMEPOINTS = ROOT / "data" / "processed" / "timepoints_2025.parquet"
WALKSHEDS = ROOT / "data" / "processed" / "stop_walksheds.gpkg"
RESULTS = ROOT / "results"
GIS = ROOT / "data" / "processed" / "gis"

MIN_EVENTS = 500  # stops scored fewer times than this are too noisy to map
K_NEIGHBORS = 8
DOWNTOWN = (-71.0605, 42.3555)  # Downtown Crossing
SEED = 2025


def stop_reliability():
    return duckdb.sql(f"""
        SELECT
            stop_id,
            any_value(time_point_id)                         AS time_point_id,
            count(on_time)                                   AS timepoints_scored,
            avg(on_time::INT)                                AS on_time_rate,
            count(DISTINCT route_id)                         AS routes,
            avg((standard_type = 'Headway')::INT)            AS share_frequent,
            avg((point_type = 'Startpoint')::INT)            AS share_origin,
            avg((point_type = 'Endpoint')::INT)              AS share_destination
        FROM '{TIMEPOINTS.as_posix()}'
        WHERE on_time IS NOT NULL
        GROUP BY stop_id
        HAVING count(on_time) >= {MIN_EVENTS}
    """).df()


def stop_points():
    feeds = sorted((ROOT / "data" / "raw" / "gtfs_2025").glob("2025????"))
    stops = pd.concat(
        pd.read_csv(f / "stops.txt", dtype=str, usecols=["stop_id", "stop_name", "stop_lat", "stop_lon"]) for f in feeds
    ).drop_duplicates("stop_id", keep="last")
    return gpd.GeoDataFrame(
        stops, geometry=gpd.points_from_xy(stops.stop_lon.astype(float), stops.stop_lat.astype(float)), crs="EPSG:4326"
    ).to_crs(equity.MA_METERS)


def walkshed_demographics(stop_ids):
    sheds = gpd.read_file(WALKSHEDS)
    sheds = sheds[sheds.stop_id.isin(stop_ids)]
    tracts = equity.tracts_with_acs()
    pieces = gpd.overlay(sheds[["stop_id", "geometry"]], tracts, how="intersection")
    share = pieces.area / pieces.tract_area
    pieces["hh"] = pieces.households * share
    pieces["hh_no_vehicle"] = pieces.households_no_vehicle * share
    pieces["hh_with_income"] = pieces.hh.where(pieces.median_hh_income.notna())
    pieces["income_x_hh"] = pieces.median_hh_income * pieces.hh_with_income
    out = pieces.groupby("stop_id")[["hh", "hh_no_vehicle", "income_x_hh", "hh_with_income"]].sum()
    out["share_no_vehicle"] = out.hh_no_vehicle / out.hh
    out["avg_median_income"] = out.income_x_hh / out.hh_with_income
    out = out.join(sheds.set_index("stop_id").area.rename("walkshed_m2"))
    out["hh_per_km2"] = out.hh / (out.walkshed_m2 / 1e6)
    return out[["hh", "share_no_vehicle", "avg_median_income", "hh_per_km2"]].reset_index()


def hot_spots(gdf, w):
    g = G_Local(gdf.on_time_rate.values, w, star=True, transform="B", permutations=9999, seed=SEED)
    gdf["gi_z"] = g.Zs
    gdf["gi_p"] = g.p_sim
    # Benjamini-Hochberg false discovery rate, as ArcGIS Pro's "Apply False Discovery Rate Correction" option
    order = np.argsort(g.p_sim)
    ranked = g.p_sim[order] * len(g.p_sim) / (np.arange(len(g.p_sim)) + 1)
    q = np.empty_like(ranked)
    q[order] = np.minimum.accumulate(ranked[::-1])[::-1]
    gdf["gi_q"] = np.clip(q, 0, 1)

    def label(z, q):
        if q > 0.10:
            return "Not significant"
        level = "99%" if q <= 0.01 else "95%" if q <= 0.05 else "90%"
        # high z = cluster of high on-time rates (good service); low z = cluster of poor service
        return f"Reliable cluster ({level})" if z > 0 else f"Unreliable cluster ({level})"

    gdf["hot_spot"] = [label(z, q) for z, q in zip(gdf.gi_z, gdf.gi_q)]
    return gdf


def regressions(gdf, w):
    gdf = gdf.dropna(subset=["share_no_vehicle", "avg_median_income"]).copy()
    w = KNN.from_dataframe(gdf, k=K_NEIGHBORS)
    w.transform = "r"
    gdf["income_10k"] = gdf.avg_median_income / 10_000
    gdf["log_hh_per_km2"] = np.log1p(gdf.hh_per_km2)
    x_cols = [
        "share_no_vehicle", "income_10k",              # what we're testing
        "km_to_downtown", "log_hh_per_km2", "routes",  # where the stop is and how busy
        "share_frequent", "share_origin", "share_destination",  # which on-time test applies
    ]
    y = gdf[["on_time_rate"]].values
    X = gdf[x_cols].values

    lines = []
    np.random.seed(SEED)  # Moran has no seed argument; this makes its permutation p-value reproducible
    moran_y = Moran(gdf.on_time_rate.values, w, permutations=9999)
    lines.append(f"Stops analyzed: {len(gdf):,}  (timepoint stops scored at least {MIN_EVENTS} times)")
    lines.append(f"Spatial weights: {K_NEIGHBORS} nearest neighbors, row-standardized\n")
    lines.append(f"Moran's I of on-time rate: {moran_y.I:.3f}  (pseudo p = {moran_y.p_sim:.4f})\n")

    ols = OLS(y, X, w=w, spat_diag=True, moran=True, name_y="on_time_rate", name_x=x_cols, name_w="knn8", name_ds="stops")
    lines.append(ols.summary)

    lm = {"error": ols.rlm_error[1], "lag": ols.rlm_lag[1]}
    chosen = None
    if min(lm.values()) < 0.05:
        chosen = "error" if lm["error"] <= lm["lag"] else "lag"
        model = (ML_Error if chosen == "error" else ML_Lag)(
            y, X, w=w, name_y="on_time_rate", name_x=x_cols, name_w="knn8", name_ds="stops"
        )
        lines.append(f"\nRobust LM tests favor a spatial {chosen} model (robust LM p: error {lm['error']:.4f}, lag {lm['lag']:.4f})\n")
        lines.append(model.summary)
    else:
        lines.append("\nRobust LM tests show no significant spatial dependence left in the OLS residuals; OLS is adequate.\n")
    return "\n".join(lines), chosen


def carfree_sensitivity(gdf):
    """How the car-free relationship changes as controls are added (OLS, robust standard errors).

    The sign flips once distance to downtown is controlled for: car-free areas
    are mostly close in, where routes are short and more reliable.
    """
    import statsmodels.formula.api as smf

    d = gdf.dropna(subset=["share_no_vehicle", "avg_median_income"]).copy()
    d["carfree_10pts"] = d.share_no_vehicle * 10
    d["income_10k"] = d.avg_median_income / 10_000
    d["log_hh_per_km2"] = np.log1p(d.hh_per_km2)
    test_type = "share_frequent + share_origin + share_destination"
    specs = {
        "No controls": "carfree_10pts",
        "+ income": "carfree_10pts + income_10k",
        "+ distance to downtown": "carfree_10pts + income_10k + km_to_downtown",
        "+ on-time test type only": f"carfree_10pts + income_10k + {test_type}",
        "Full model": f"carfree_10pts + income_10k + km_to_downtown + log_hh_per_km2 + routes + {test_type}",
    }
    rows = []
    for label, rhs in specs.items():
        m = smf.ols(f"on_time_rate ~ {rhs}", d).fit(cov_type="HC1")
        rows.append({
            "model": label,
            "carfree_effect_pts_per_10": m.params["carfree_10pts"] * 100,
            "std_error_pts": m.bse["carfree_10pts"] * 100,
            "p_value": m.pvalues["carfree_10pts"],
            "n": int(m.nobs),
        })
    return pd.DataFrame(rows)


def main():
    rel = stop_reliability()
    pts = stop_points().merge(rel, on="stop_id")  # drops virtual timepoints (bridges, tunnels) that aren't real stops
    pts = pts.merge(walkshed_demographics(set(pts.stop_id)), on="stop_id", how="left")
    downtown = gpd.GeoSeries.from_xy([DOWNTOWN[0]], [DOWNTOWN[1]], crs="EPSG:4326").to_crs(equity.MA_METERS).iloc[0]
    pts["km_to_downtown"] = pts.distance(downtown) / 1000

    w = KNN.from_dataframe(pts, k=K_NEIGHBORS)
    pts = hot_spots(pts, w)
    report, chosen = regressions(pts, w)

    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "spatial_regression.txt").write_text(report, encoding="utf-8")
    sens = carfree_sensitivity(pts)
    sens.round(4).to_csv(RESULTS / "carfree_sensitivity.csv", index=False)
    cols = [c for c in pts.columns if c not in ("geometry", "stop_lat", "stop_lon")]
    pts[cols].round(4).sort_values("on_time_rate").to_csv(RESULTS / "stop_reliability.csv", index=False)
    GIS.mkdir(parents=True, exist_ok=True)
    pts.drop(columns=["stop_lat", "stop_lon"]).to_file(GIS / "stops.gpkg", layer="timepoint_stops", driver="GPKG")

    print(f"{len(pts):,} stops analyzed")
    print(pts.hot_spot.value_counts().to_string())
    print(f"Model: {'spatial ' + chosen if chosen else 'OLS'}; full output in results/spatial_regression.txt")
    print("\nCar-free effect as controls are added (results/carfree_sensitivity.csv):")
    print(sens.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
