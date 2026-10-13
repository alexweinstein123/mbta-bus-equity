"""Geographically weighted regression: where does car ownership relate to bus reliability?

Usage:
    python src/gwr.py

Needs spatial_stats.py to have run first. The global regression in
spatial_stats.py gives one network-wide relationship. GWR fits a separate
regression around every stop, using its nearest neighbors weighted by
distance, so each stop gets its own coefficients and we can map where a
relationship is strong, weak or absent. Writes:
  results/gwr_summary.txt          GWR and MGWR output
  data/processed/gis/stops_gwr.gpkg  local coefficients per stop, for ArcGIS Pro

Two models:
  GWR   one bandwidth (number of neighbors) shared by every variable.
  MGWR  multiscale GWR: each variable gets its own bandwidth, so a factor
        that works region-wide gets a large one and a local factor a small
        one. This is the current best practice (Fotheringham, Yang & Kang 2017).

Choices:
  - Variables are standardized (mean 0, SD 1), as MGWR requires, so
    coefficients are in standard deviations. The car-free coefficient is
    also converted back to "points of on-time rate per 10 points of
    car-free share" for readability.
  - Distance to downtown is left out: the local intercept already captures
    where a stop is. Number of routes is left out because it had no effect
    in the global model.
  - Adaptive bisquare kernel, bandwidths chosen by AICc.
  - Significance uses the corrected critical t-values of da Silva and
    Fotheringham (2016), which account for running many local tests.
"""

import contextlib
import io
from pathlib import Path

import geopandas as gpd
import numpy as np
from mgwr.gwr import GWR, MGWR
from mgwr.sel_bw import Sel_BW

ROOT = Path(__file__).resolve().parents[1]
GIS = ROOT / "data" / "processed" / "gis"
RESULTS = ROOT / "results"

X_COLS = [
    "share_no_vehicle", "income_10k", "log_hh_per_km2",      # neighborhood
    "share_frequent", "share_origin", "share_destination",  # which on-time test applies
]
NAMES = ["intercept", *X_COLS]


def load():
    g = gpd.read_file(GIS / "stops.gpkg").dropna(subset=["share_no_vehicle", "avg_median_income"])
    g["income_10k"] = g.avg_median_income / 10_000
    g["log_hh_per_km2"] = np.log1p(g.hh_per_km2)
    return g.reset_index(drop=True)


def standardize(a):
    return (a - a.mean(axis=0)) / a.std(axis=0)


def captured_summary(results):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        results.summary()
    return buf.getvalue()


def main():
    g = load()
    coords = np.column_stack([g.geometry.x, g.geometry.y])
    y = standardize(g[["on_time_rate"]].values)
    X = standardize(g[X_COLS].values)

    print("GWR: selecting bandwidth...")
    gwr_bw = Sel_BW(coords, y, X).search(criterion="AICc")
    gwr = GWR(coords, y, X, gwr_bw).fit()

    print("MGWR: selecting a bandwidth per variable (several minutes)...")
    selector = Sel_BW(coords, y, X, multi=True)
    selector.search(criterion="AICc", verbose=False)
    mgwr = MGWR(coords, y, X, selector).fit()

    RESULTS.mkdir(exist_ok=True)
    report = [
        f"Stops: {len(g):,}",
        f"Variables (standardized): {', '.join(X_COLS)}",
        f"GWR bandwidth: {gwr_bw:.0f} nearest neighbors",
        "MGWR bandwidths: " + ", ".join(f"{n} {b:.0f}" for n, b in zip(NAMES, selector.bw[0])),
        "",
        captured_summary(gwr),
        captured_summary(mgwr),
    ]
    (RESULTS / "gwr_summary.txt").write_text("\n".join(report), encoding="utf-8")

    # local results per stop, from MGWR
    sig = mgwr.filter_tvals() != 0
    per10 = (g.on_time_rate.std() / g.share_no_vehicle.std()) * 0.10 * 100  # SD units -> points per 10 points
    out = g[["stop_id", "stop_name", "time_point_id", "on_time_rate", "share_no_vehicle", "avg_median_income", "geometry"]].copy()
    for i, name in enumerate(NAMES):
        out[f"b_{name}"] = mgwr.params[:, i]
        out[f"sig_{name}"] = sig[:, i]
    out["carfree_pts_per_10"] = out.b_share_no_vehicle * per10
    out["carfree_effect"] = np.select(
        [out.sig_share_no_vehicle & (out.b_share_no_vehicle < 0), out.sig_share_no_vehicle & (out.b_share_no_vehicle > 0)],
        ["Less reliable where more households are car-free", "More reliable where more households are car-free"],
        default="No significant relationship",
    )
    out["local_r2"] = gwr.localR2.flatten()
    out.to_file(GIS / "stops_gwr.gpkg", layer="stops_gwr", driver="GPKG")

    print(f"\nGWR:  bandwidth {gwr_bw:.0f} neighbors, R2 {gwr.R2:.3f}, AICc {gwr.aicc:.1f}")
    print(f"MGWR: R2 {mgwr.R2:.3f}, AICc {mgwr.aicc:.1f}")
    for n, b in zip(NAMES, selector.bw[0]):
        print(f"  {n:18s} bandwidth {b:5.0f} neighbors  ({b / len(g):.0%} of stops)")
    print("\nCar-free share, local MGWR result:")
    print(out.carfree_effect.value_counts().to_string())
    print(f"Local effect ranges from {out.carfree_pts_per_10.min():.1f} to {out.carfree_pts_per_10.max():.1f} "
          f"points of on-time rate per 10 points of car-free share")
    print("\nWrote results/gwr_summary.txt and data/processed/gis/stops_gwr.gpkg")


if __name__ == "__main__":
    main()
