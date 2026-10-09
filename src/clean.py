"""Clean the 2025 bus arrival/departure data and score every timepoint as on time or not.

Usage:
    python src/clean.py

Reads data/raw/arrival_departure/2025/ and writes
data/processed/timepoints_2025.parquet, one row per timepoint crossing.

Quirks of the raw data, found while profiling it:

1. Times are written like "1900-01-02T04:57:00Z". The date part is just an
   offset from the service date (1900-01-02 means after midnight), and despite
   the "Z" they are not UTC. They are Boston local time plus a fixed 5 hours,
   all year, with no daylight saving shift. (Route 1's first weekday trip is
   04:37 in GTFS and 09:37 in the data, in both January and July.)
2. The data dictionary says scheduled_headway is filled for headway-standard
   trips. In the 2025 file it's the opposite: it's only filled for
   schedule-standard trips. The `headway` column (actual gap to the previous
   bus) is correct, so we derive the scheduled gap from the timetable.
3. About 6% of timepoints have no actual time. The data notes collection
   gaps, so these can be dropped trips or missing data. We keep them with
   on_time = NULL and leave the choice to the analysis.

On-time rules follow the MBTA Service Delivery Policy (December 2025, pp. 19-20):

  Schedule standard (headways > 15 min)
    origin       depart 0 min early to 3 min late
    mid-route    depart 1 min early to 6 min late
    destination  arrive no more than 5 min late
  Headway standard (headways <= 15 min, and all Frequent Routes)
    origin/mid   actual headway <= scheduled headway + 3 min
    destination  actual run time <= 120% of scheduled run time
  The first trip of the day has no leading headway, so it's scored on the
  schedule standard.
"""

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "arrival_departure" / "2025"
OUT = ROOT / "data" / "processed" / "timepoints_2025.parquet"

LOCAL_OFFSET = "INTERVAL 5 HOUR"

SQL = f"""
CREATE TEMP TABLE raw AS
SELECT
    service_date::DATE                                   AS service_date,
    regexp_replace(route_id, '^0+(\\d)', '\\1')          AS route_id,  -- "01" -> "1" to match GTFS
    direction_id,
    half_trip_id::BIGINT                                 AS half_trip_id,
    stop_id,
    time_point_id,
    time_point_order::INT                                AS time_point_order,
    point_type,
    standard_type,
    service_date::DATE + (scheduled::TIMESTAMP - TIMESTAMP '1900-01-01') - {LOCAL_OFFSET} AS sched,
    service_date::DATE + (actual::TIMESTAMP    - TIMESTAMP '1900-01-01') - {LOCAL_OFFSET} AS actual,
    headway::INT                                         AS actual_headway_s
FROM read_csv('{RAW.as_posix()}/*/*.csv', all_varchar = true, header = true);

CREATE TEMP TABLE enriched AS
SELECT
    r.*,
    datediff('second', r.sched, r.actual) / 60.0 AS delay_min,
    -- scheduled gap to the previous trip at this timepoint (missing from the raw file for headway trips)
    datediff('second', lag(r.sched) OVER w, r.sched) AS sched_headway_s,
    datediff('second', o.sched,  r.sched)  AS sched_runtime_s,
    datediff('second', o.actual, r.actual) AS actual_runtime_s
FROM raw r
LEFT JOIN (
    SELECT service_date, half_trip_id, any_value(sched) AS sched, any_value(actual) AS actual
    FROM raw WHERE point_type = 'Startpoint' GROUP BY ALL
) o USING (service_date, half_trip_id)
WINDOW w AS (PARTITION BY r.service_date, r.route_id, r.direction_id, r.time_point_id ORDER BY r.sched);

COPY (
    SELECT
        *,
        CASE dayofweek(service_date) WHEN 0 THEN 'Sunday' WHEN 6 THEN 'Saturday' ELSE 'Weekday' END AS day_type,
        -- MBTA time periods (Service Delivery Policy, Table 1), by scheduled local time
        CASE
            WHEN hour(sched) <  3 THEN 'Night'
            WHEN hour(sched) <  6 THEN 'Sunrise'
            WHEN hour(sched) <  7 THEN 'Early AM'
            WHEN hour(sched) <  9 THEN 'AM Peak'
            WHEN sched::TIME < TIME '13:30' THEN 'Midday Base'
            WHEN hour(sched) < 16 THEN 'Midday School'
            WHEN sched::TIME < TIME '18:30' THEN 'PM Peak'
            WHEN hour(sched) < 22 THEN 'Evening'
            ELSE 'Late Evening'
        END AS time_period,
        CASE
            WHEN actual IS NULL THEN NULL
            -- headway standard
            WHEN standard_type = 'Headway' AND point_type = 'Endpoint'
                THEN actual_runtime_s <= 1.2 * sched_runtime_s
            WHEN standard_type = 'Headway' AND actual_headway_s IS NOT NULL AND sched_headway_s IS NOT NULL
                THEN actual_headway_s <= sched_headway_s + 180
            -- schedule standard (and first trips of the day on headway routes)
            WHEN point_type = 'Startpoint' THEN delay_min BETWEEN 0 AND 3
            WHEN point_type = 'Midpoint'   THEN delay_min BETWEEN -1 AND 6
            WHEN point_type = 'Endpoint'   THEN delay_min <= 5
        END AS on_time
    FROM enriched
    ORDER BY service_date, route_id, half_trip_id, time_point_order
) TO '{OUT.as_posix()}' (FORMAT parquet, COMPRESSION zstd);
"""


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET preserve_insertion_order = false")
    con.execute(SQL)
    n, routes, scored, otp = con.execute(
        f"SELECT count(*), count(DISTINCT route_id), count(on_time), avg(on_time::INT) FROM '{OUT.as_posix()}'"
    ).fetchone()
    print(f"Wrote {OUT.relative_to(ROOT)}: {n:,} timepoints, {routes} routes")
    print(f"Scored {scored:,} ({scored / n:.1%}); system-wide on-time rate {otp:.1%}")


if __name__ == "__main__":
    main()
