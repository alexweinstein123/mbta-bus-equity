"""Link each bus route to the neighborhoods it serves and compare reliability.

Usage:
    python src/equity.py

Needs clean.py to have run first. Writes results/route_equity.csv, one row
per route with its 2025 reliability and the demographics of its catchment.

Method:
  - A route's stops are every stop its trips served in four seasonal 2025
    GTFS schedules (January, April, July, October).
  - Its catchment is the union of quarter-mile (402 m) circles around those
    stops, the standard planning assumption for walking to a bus.
  - Census counts (households, households with no vehicle) are apportioned
    from tracts to the catchment by area. Income is the household-weighted
    average of tract median incomes, which approximates the typical income
    of the catchment rather than a true median.
"""

from pathlib import Path

import duckdb
import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
TIMEPOINTS = ROOT / "data" / "processed" / "timepoints_2025.parquet"
OUT = ROOT / "results" / "route_equity.csv"

WALK_M = 402.336  # quarter mile
MA_METERS = "EPSG:26986"  # Massachusetts State Plane, meters


def route_reliability():
    return duckdb.sql(f"""
        SELECT
            route_id,
            count(*)                                            AS timepoints,
            count(on_time)                                      AS timepoints_scored,
            avg(on_time::INT)                                   AS on_time_rate,
            -- lower bound: count missing timepoints (dropped trips or data gaps) as late
            avg(coalesce(on_time, false)::INT)                  AS on_time_rate_lower,
            avg(on_time::INT) FILTER (day_type = 'Weekday' AND time_period = 'PM Peak') AS on_time_rate_pm_peak,
            avg((standard_type = 'Headway')::INT)               AS share_frequent
        FROM '{TIMEPOINTS.as_posix()}'
        GROUP BY route_id
    """).df()


def route_stops(data_routes):
    """Every (route_id, stop) pair served in the 2025 schedules, keyed by the bus data's route_id."""
    pairs, stops = [], []
    for feed in sorted((RAW / "gtfs_2025").glob("2025????")):
        routes = pd.read_csv(feed / "routes.txt", dtype=str)
        routes = routes[routes.route_type == "3"]
        # The bus data mostly uses GTFS route_ids, but uses names for the Silver Line
        # and crosstown routes ("SL1" is 741 in GTFS)
        key = {}
        for r in routes.itertuples():
            for candidate in (r.route_id, r.route_short_name):
                if candidate in data_routes:
                    key[r.route_id] = candidate
                    break
        trips = pd.read_csv(feed / "trips.txt", dtype=str, usecols=["route_id", "trip_id"])
        trips = trips[trips.route_id.isin(key)]
        st = pd.read_csv(feed / "stop_times.txt", dtype=str, usecols=["trip_id", "stop_id"])
        st = st[st.trip_id.isin(trips.trip_id)].merge(trips, on="trip_id")
        st["route_id"] = st.route_id.map(key)
        pairs.append(st[["route_id", "stop_id"]].drop_duplicates())
        stops.append(pd.read_csv(feed / "stops.txt", dtype=str, usecols=["stop_id", "stop_lat", "stop_lon"]))

    pairs = pd.concat(pairs).drop_duplicates()
    stops = pd.concat(stops).drop_duplicates("stop_id", keep="last")
    df = pairs.merge(stops, on="stop_id")
    return gpd.GeoDataFrame(
        df, geometry=gpd.points_from_xy(df.stop_lon.astype(float), df.stop_lat.astype(float)), crs="EPSG:4326"
    ).to_crs(MA_METERS)


def tracts_with_acs():
    tracts = gpd.read_file(RAW / "tracts" / "tl_2024_25_tract.zip")[["GEOID", "geometry"]].to_crs(MA_METERS)
    acs = pd.read_csv(RAW / "acs" / "acs5_2024_ma_tracts.csv", dtype={"GEOID": str})
    for col in ["median_hh_income", "households", "households_no_vehicle"]:
        acs[col] = pd.to_numeric(acs[col]).where(lambda s: s >= 0)  # Census uses large negatives for "no data"
    tracts = tracts.merge(acs[["GEOID", "median_hh_income", "households", "households_no_vehicle"]], on="GEOID")
    tracts["tract_area"] = tracts.area
    return tracts


def catchment_demographics(stops, tracts):
    catchments = stops.assign(geometry=stops.buffer(WALK_M)).dissolve(by="route_id")[["geometry"]].reset_index()
    pieces = gpd.overlay(catchments, tracts, how="intersection")
    share = pieces.area / pieces.tract_area
    pieces["hh"] = pieces.households * share
    pieces["hh_no_vehicle"] = pieces.households_no_vehicle * share
    pieces["hh_with_income"] = pieces.hh.where(pieces.median_hh_income.notna())
    pieces["income_x_hh"] = pieces.median_hh_income * pieces.hh_with_income

    out = pieces.groupby("route_id").agg(
        catchment_households=("hh", "sum"),
        catchment_hh_no_vehicle=("hh_no_vehicle", "sum"),
        income_x_hh=("income_x_hh", "sum"),
        hh_with_income=("hh_with_income", "sum"),
    )
    out["share_no_vehicle"] = out.catchment_hh_no_vehicle / out.catchment_households
    out["avg_median_income"] = out.income_x_hh / out.hh_with_income
    out["stops"] = stops.groupby("route_id").size()
    return out.drop(columns=["income_x_hh", "hh_with_income"]).reset_index()


def main():
    rel = route_reliability()
    stops = route_stops(set(rel.route_id))
    demo = catchment_demographics(stops, tracts_with_acs())

    df = rel.merge(demo, on="route_id", how="inner")
    dropped = sorted(set(rel.route_id) - set(df.route_id))
    print(f"{len(df)} routes matched to 2025 schedules; set aside {len(dropped)} special/shuttle routes: {', '.join(dropped)}")

    OUT.parent.mkdir(exist_ok=True)
    df.sort_values("on_time_rate").round(4).to_csv(OUT, index=False)
    print(f"Wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
