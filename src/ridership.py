"""Weight bus reliability by the riders it affects.

Usage:
    python src/ridership.py

Needs clean.py, equity.py and spatial_stats.py to have run first. Uses the
MBTA's Fall 2025 ridership counts (average boardings, alightings and load for
every trip at every stop) to count how many riders are on each bus at each
timepoint, then reweights the on-time results by those riders. Writes:
  results/ridership_reliability.csv   passenger-weighted results by route
  results/ridership_summary.txt       headline numbers

Method:
  - Each timepoint crossing is matched to its trip in the ridership data by
    route, direction, trip start time, stop and day type (Mon-Thu, Fri, Sat, Sun).
  - Riders affected at a timepoint = passengers on board leaving the stop
    plus passengers who got off there, i.e. everyone on the bus at that point.
  - Only crossings from the Fall 2025 rating (Aug 24 to Dec 13, 2025) are
    used, so the schedule matches the ridership counts.

Quirks of the Fall 2025 ridership file (it doesn't match the published data
dictionary, and its columns differ from earlier seasons):
  - Silver Line and crosstown routes use numeric GTFS ids (743 is SL3).
  - About 2% of trip start times are stored as fractions of a day
    (0.25 = 6:00 AM, values over 1 are after midnight).
  - Mon-Thu is "Wkdy" and Friday is its own day type.
"""

from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RIDERSHIP = next((ROOT / "data" / "raw" / "ridership" / "extracted").glob("*/*Fall_2025.csv"))
TIMEPOINTS = ROOT / "data" / "processed" / "timepoints_2025.parquet"
ROUTES = ROOT / "results" / "route_equity.csv"
STOPS = ROOT / "results" / "stop_reliability.csv"
GTFS_ROUTES = ROOT / "data" / "raw" / "gtfs_2025" / "20251015" / "routes.txt"
RESULTS = ROOT / "results"

RATING_START, RATING_END = "2025-08-24", "2025-12-13"
TARGET = 0.70  # MBTA bus reliability target


def quartile_table(con, stops, col, measure, labels):
    """On-time rate by quartile of a stop's walkshed demographics, counted by bus and by rider."""
    q = stops[["stop_id", col]].copy()
    q["quartile"] = pd.qcut(q[col], 4, labels=labels).astype(str)
    q["order"] = pd.qcut(q[col], 4, labels=False)
    con.register("stop_q", q)
    out = con.execute(f"""
        SELECT quartile,
               min({col}) AS range_low, max({col}) AS range_high,
               avg(on_time::INT)                                         AS on_time_by_bus,
               sum(on_time::INT * riders_on_bus) / sum(riders_on_bus)   AS on_time_by_rider
        FROM crossings JOIN stop_q USING (stop_id)
        WHERE riders_on_bus IS NOT NULL
        GROUP BY quartile, "order" ORDER BY "order"
    """).df()
    con.unregister("stop_q")
    return out.assign(measure=measure)[["measure", "quartile", "range_low", "range_high", "on_time_by_bus", "on_time_by_rider"]]


def main():
    con = duckdb.connect()
    # GTFS id -> the route names used in the reliability data (741 -> SL1, 746 -> SLW, ...)
    routes = pd.read_csv(GTFS_ROUTES, dtype=str)
    routes = routes[routes.route_type == "3"]
    named = routes.route_short_name.str.match(r"^(SL|CT)")
    con.register("route_names", pd.DataFrame({
        "gtfs_id": routes.route_id,
        "route_id": routes.route_short_name.where(named, routes.route_id),
    }))

    con.execute(f"""
        CREATE TABLE riders AS
        SELECT
            coalesce(n.route_id, r."GTFS route_id")                     AS route_id,
            r."GTFS direction_id"::INT                                  AS direction,
            CASE WHEN regexp_matches(r."trip start time", '^\\d+:\\d\\d:\\d\\d$')
                 THEN (split_part(r."trip start time", ':', 1)::INT * 3600
                       + split_part(r."trip start time", ':', 2)::INT * 60
                       + split_part(r."trip start time", ':', 3)::INT) % 86400
                 ELSE round(r."trip start time"::DOUBLE * 86400)::INT % 86400
            END                                                          AS trip_start_s,
            r."GTFS stop_id"                                             AS stop_id,
            r."Day Type"                                                 AS day_type,
            r."Boardings"::DOUBLE                                        AS boardings,
            r."Load"::DOUBLE + r."Alightings"::DOUBLE                    AS riders_on_bus
        FROM read_csv('{RIDERSHIP.as_posix()}', all_varchar = true) r
        LEFT JOIN route_names n ON n.gtfs_id = r."GTFS route_id"
    """)

    # timepoint crossings in the Fall 2025 rating, keyed like the ridership data
    con.execute(f"""
        CREATE TABLE crossings AS
        WITH t AS (
            SELECT *, CASE direction_id WHEN 'Outbound' THEN 0 WHEN 'Inbound' THEN 1 END AS direction,
                   CASE dayofweek(service_date) WHEN 0 THEN 'Sun' WHEN 6 THEN 'Sat' WHEN 5 THEN 'Fri' ELSE 'Wkdy' END AS rday
            FROM '{TIMEPOINTS.as_posix()}'
            WHERE service_date BETWEEN DATE '{RATING_START}' AND DATE '{RATING_END}' AND on_time IS NOT NULL
        ),
        starts AS (
            SELECT service_date, half_trip_id,
                   any_value((epoch(sched) - epoch(service_date::TIMESTAMP))::INT % 86400) AS trip_start_s
            FROM t WHERE point_type = 'Startpoint' GROUP BY ALL
        )
        SELECT t.route_id, t.stop_id, t.service_date, t.rday, t.on_time, t.delay_min, r.riders_on_bus
        FROM t
        JOIN starts s USING (service_date, half_trip_id)
        LEFT JOIN riders r
          ON r.route_id = t.route_id AND r.direction = t.direction AND r.trip_start_s = s.trip_start_s
         AND r.stop_id = t.stop_id AND r.day_type = t.rday
    """)

    matched, total = con.execute("SELECT count(riders_on_bus), count(*) FROM crossings").fetchone()
    days = con.execute("SELECT rday, count(DISTINCT service_date) FROM crossings GROUP BY 1").df().set_index("rday").iloc[:, 0]

    by_route = con.execute("""
        SELECT route_id,
               count(*)                                                           AS crossings,
               avg(on_time::INT)                                                  AS on_time_rate,
               sum(on_time::INT * riders_on_bus) / sum(riders_on_bus)            AS on_time_rate_riders,
               count(riders_on_bus) / count(*)                                    AS share_matched
        FROM crossings GROUP BY 1
    """).df()
    boardings = con.execute(
        "SELECT route_id, sum(boardings) AS weekday_boardings FROM riders WHERE day_type = 'Wkdy' GROUP BY 1"
    ).df()
    eq = pd.read_csv(ROUTES, dtype={"route_id": str})[["route_id", "share_no_vehicle", "avg_median_income", "on_time_rate"]]
    eq = eq.rename(columns={"on_time_rate": "on_time_rate_2025"})
    df = by_route.merge(boardings, on="route_id", how="left").merge(eq, on="route_id", how="inner")
    df["carfree_quartile"] = pd.qcut(df.share_no_vehicle, 4, labels=["Q1 (fewest car-free)", "Q2", "Q3", "Q4 (most car-free)"])
    df["below_target"] = df.on_time_rate_2025 < TARGET
    RESULTS.mkdir(exist_ok=True)
    df.round(4).sort_values("weekday_boardings", ascending=False).to_csv(RESULTS / "ridership_reliability.csv", index=False)

    # stop-level: on-time rate by quartile of the stop walkshed's car-free share and income
    stops = pd.read_csv(STOPS, dtype={"stop_id": str})
    stops = stops[["stop_id", "share_no_vehicle", "avg_median_income"]].dropna()
    by_q = pd.concat([
        quartile_table(con, stops, "share_no_vehicle", "Car-free share", ["Fewest car-free", "Q2", "Q3", "Most car-free"]),
        quartile_table(con, stops, "avg_median_income", "Income", ["Lowest income", "Q2", "Q3", "Highest income"]),
    ])
    by_q.round(4).to_csv(RESULTS / "reliability_by_quartile.csv", index=False)

    overall = con.execute("""
        SELECT avg(on_time::INT), sum(on_time::INT * riders_on_bus) / sum(riders_on_bus)
        FROM crossings WHERE riders_on_bus IS NOT NULL
    """).fetchone()
    below = df[df.below_target]
    lines = [
        f"Fall 2025 rating ({RATING_START} to {RATING_END}); ridership from the MBTA's Fall 2025 counts",
        f"Timepoint crossings matched to a ridership trip: {matched:,} of {total:,} ({matched / total:.1%})",
        f"Days in sample: {days.to_dict()}",
        "",
        f"On-time rate, counting buses:  {overall[0]:.1%}",
        f"On-time rate, counting riders: {overall[1]:.1%}",
        "",
        f"Weekday (Mon-Thu) boardings on the {len(df)} routes analyzed: {df.weekday_boardings.sum():,.0f}",
        f"Routes below the MBTA's {TARGET:.0%} target in 2025: {len(below)} of {len(df)}, "
        f"carrying {below.weekday_boardings.sum():,.0f} weekday boardings ({below.weekday_boardings.sum() / df.weekday_boardings.sum():.0%})",
        "",
        "By route car-free quartile:",
        df.groupby("carfree_quartile", observed=True).apply(
            lambda g: pd.Series({
                "routes": len(g),
                "weekday_boardings": g.weekday_boardings.sum(),
                "share_of_boardings_below_target": g.weekday_boardings[g.below_target].sum() / g.weekday_boardings.sum(),
            }),
            include_groups=False,
        ).round(3).to_string(),
        "",
        "On-time rate by stop walkshed quartile (results/reliability_by_quartile.csv):",
        by_q.round(4).to_string(index=False),
    ]
    (RESULTS / "ridership_summary.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
