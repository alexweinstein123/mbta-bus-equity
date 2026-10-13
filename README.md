# MBTA Bus Reliability and Equity

Do MBTA buses serving lower income, lower car ownership neighborhoods run less reliably than buses serving wealthier areas?

This project scores every MBTA bus timepoint in 2025 against the MBTA's own on-time rules, links each stop to the people within a real walking distance of it, and tests whether reliability differs by neighborhood car ownership and income, using spatial statistics and passenger-weighted measures.

## Findings

The hypothesis was only partly supported.

- **Reliability is low across the network.** Buses were on time at **69.8%** of timepoints in 2025, right at the MBTA's 70% minimum. **92 of 148 routes** fell below that target, carrying about **35% of weekday riders** (115,000 of 327,000 boardings).
- **Car-free neighborhoods get better reliability, not worse, overall.** Weighted by riders, buses at stops in the most car-free quarter of neighborhoods were on time **69%** of the time, against **58%** in the least car-free quarter. Only 17% of riders on the most car-free routes ride routes below target, compared with 62% on the least car-free routes.
- **That advantage comes from location.** Car-free neighborhoods sit close to downtown (correlation −0.68), where routes are short and frequent. Comparing stops at a similar distance from downtown, more car-free households go with *slightly lower* reliability, about **1 to 1.5 points per 10 points of car-free share**. The sign depends on that control (see the table below), so this is a conditional finding, not a headline gap.
- **The on-time standard itself favors the core.** Frequent routes are judged by a spacing test, infrequent ones by a timetable test. Frequent-test stops score about 10 points higher (74% vs 63%), and accounting for test type alone removes the car-free difference.
- **The worst reliability clusters are in the outer network.** Hot spot analysis finds statistically significant clusters of poor reliability around Alewife, Lynn and Route 1 north, in areas with average car ownership.

How the car-free relationship changes as controls are added (stop level, OLS with robust standard errors, `results/carfree_sensitivity.csv`):

| Model | Effect per 10 points more car-free households | p |
|---|---|---|
| No controls | +0.6 points of on-time rate | 0.005 |
| + income | +0.8 | 0.002 |
| + distance to downtown | −0.9 | 0.007 |
| + on-time test type only | −0.3 | 0.17 |
| Full model | −1.5 | <0.001 |

## Methods

| Step | Script | What it does |
|---|---|---|
| 1. Download | `src/download.py` | Fetches all source data |
| 2. Clean and score | `src/clean.py` | Converts 28.1M timepoint records to local time and scores each one with the MBTA's on-time rules |
| 3. Walksheds | `src/walksheds.py` | Builds a quarter-mile street-network walkshed for each of 6,790 stops from OpenStreetMap |
| 4. Route equity | `src/equity.py` | Apportions Census data to each route's walkshed; exports GIS layers |
| 5. Spatial statistics | `src/spatial_stats.py` | Getis-Ord Gi\* hot spots, Moran's I, OLS with spatial diagnostics, spatial error model, sensitivity table |
| 6. GWR | `src/gwr.py` | Geographically weighted and multiscale GWR |
| 7. Ridership | `src/ridership.py` | Weights reliability by riders on board using Fall 2025 trip-level counts |

### Measuring reliability

Every timepoint crossing is scored on time or not using the MBTA's own rules from the [Service Delivery Policy](https://www.mbta.com/policies/service-delivery-policy) (December 2025, pp. 19–20):

| Standard | Origin | Mid-route | Destination |
|---|---|---|---|
| Schedule (headways over 15 min) | depart 0 to 3 min late | depart 1 min early to 6 min late | arrive no more than 5 min late |
| Headway (headways of 15 min or less) | gap to previous bus ≤ scheduled gap + 3 min | same | run time ≤ 120% of scheduled |

### Who a stop serves: street-network walksheds

Each stop's catchment is the area reachable by walking a quarter mile (402 m) along OpenStreetMap streets and paths, buffered 50 m to cover the buildings that front them. This respects rivers, highways, rail lines and dead ends. The median walkshed covers only **50%** of a quarter-mile circle. Census households, car-free households and income are apportioned from tracts to walksheds by area. All distances and areas use Massachusetts State Plane (EPSG:26986).

At the route level, walksheds and circles give nearly identical demographics (correlation 0.998), because each route crosses many tracts. Walksheds matter at the stop level, where the spatial analysis is done.

### Spatial analysis

The unit of analysis is the timepoint stop, where reliability is actually measured (1,103 stops with at least 500 scored crossings).

- **Moran's I** of on-time rate is 0.164 (p < 0.001): nearby stops have similar reliability.
- **Getis-Ord Gi\*** (8 nearest neighbors, false discovery rate correction) finds 66 stops in clusters of poor reliability and 101 in clusters of good reliability.
- **Regression.** Lagrange multiplier tests on OLS residuals favored a **spatial error model**, re-estimated with heteroskedasticity-robust errors. Controls: income, distance to downtown, housing density, number of routes, and which on-time test applies.
- **MGWR** (multiscale geographically weighted regression) lets each variable work at its own scale. Baseline reliability varies very locally (bandwidth 95 of 1,103 stops), while the car-free relationship is global (bandwidth = all stops) at about −1 point per 10. Local fit improves from R² 0.18 (global) to 0.34.

### Passenger weighting

Fall 2025 ridership counts give the average boardings, alightings and load for every trip at every stop. 96% of timepoint crossings in the Fall 2025 rating (Aug 24 to Dec 13) match a ridership trip by route, direction, trip start time, stop and day type. Each crossing is weighted by everyone on the bus at that point. Counting riders instead of buses lowers the on-time rate from 68.7% to 67.6%, since crowded trips run later.

### Data quirks worth knowing

- **Times aren't UTC.** They're written like `1900-01-02T04:57:00Z`, but they're Boston local time plus a fixed 5 hours all year, ignoring daylight saving. Route 1's first weekday trip is 4:37 AM in GTFS and `09:37` in the data in both January and July. `clean.py` converts them to real local timestamps.
- **The data dictionary has the headway columns backwards.** `scheduled_headway` is only filled for schedule-standard trips, not headway-standard ones. The actual `headway` column is correct, so the scheduled gap is rebuilt from the timetable.
- **Silver Line 3 changes ids mid-year:** `743` through early April 2025, `SL3` after.
- **About 6% of timepoints have no actual time**, either dropped trips or collection gaps. They're kept with `on_time` empty. The MBTA counts dropped trips as failures, so treating them as failures gives a lower bound.
- **The Fall 2025 ridership file** doesn't match the published data dictionary, uses different columns from earlier seasons, and stores about 2% of trip start times as fractions of a day.
- **Virtual timepoints.** 20 timepoints are on bridges, tunnels and ramps (the Tobin Bridge, the Ted Williams Tunnel, the Allston tolls) where nobody boards. They count toward route on-time rates but are left out of the stop-level analysis.

## Limitations

- **Association, not cause.** The analysis can't separate car ownership from things that travel with it, such as traffic, street design and crowding.
- **Two on-time tests.** Comparisons across neighborhoods partly reflect which test a stop is judged by, not only how buses perform.
- **Areal interpolation** assumes people are spread evenly within each census tract.
- **Ridership** is a Fall 2025 snapshot, applied to the Fall 2025 rating only.
- **Future work:** a Title VI style analysis by race and ethnicity, the framework federal transit equity analysis uses.

## Data sources

| Dataset | Source | Where it goes |
|---|---|---|
| Bus Arrival Departure Times 2025 (CC0) | [MBTA Open Data Portal](https://mbta-massdot.opendata.arcgis.com/) | `data/raw/arrival_departure/` |
| Bus Ridership by Trip, Season, Route, Line, and Stop (CC0) | [MBTA Open Data Portal](https://mbta-massdot.opendata.arcgis.com/) | `data/raw/ridership/` |
| MBTA GTFS, four 2025 schedules (January, April, July, October) | [MBTA GTFS archive](https://cdn.mbta.com/archive/archived_feeds.txt) | `data/raw/gtfs_2025/` |
| ACS 2020–2024 5-year estimates: median household income (B19013) and vehicles available (B08201) by tract | [U.S. Census Bureau API](https://www.census.gov/data/developers.html) | `data/raw/acs/` |
| Census tract boundaries, Massachusetts (TIGER/Line 2024) | [Census TIGER/Line](https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html) | `data/raw/tracts/` |
| Street and path network | [OpenStreetMap](https://www.openstreetmap.org/) via OSMnx | `data/raw/osm/` |

Raw data is not committed to the repo because the files are large. `src/download.py` fetches everything except the OpenStreetMap network, which `walksheds.py` downloads on its first run.

## Running it

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

The Census API needs a free key ([sign up here](https://api.census.gov/data/key_signup.html)). Put it in a `.env` file at the repo root:

```
CENSUS_API_KEY=your_key_here
```

Then run the pipeline in order:

```
python src/download.py       # about 500 MB
python src/clean.py          # about 40 seconds
python src/walksheds.py      # first run downloads OpenStreetMap: about 1 hour; later runs about 25 minutes
python src/equity.py
python src/spatial_stats.py
python src/gwr.py            # a few minutes
python src/ridership.py
```

Map-ready GeoPackages for ArcGIS Pro or QGIS are written to `data/processed/gis/`. See [docs/arcgis_guide.md](docs/arcgis_guide.md) for the maps.

## Repo layout

```
src/             pipeline scripts, run in the order above
results/         output tables and model summaries
docs/            ArcGIS Pro and StoryMap guide
figures/         maps and charts for the write-up
data/raw/        downloaded source files (gitignored)
data/processed/  cleaned outputs and GIS layers (gitignored)
```

## Status

- [x] Data pipeline and cleaning
- [x] Street-network walksheds
- [x] Route and stop reliability, Census join
- [x] Spatial statistics: hot spots, Moran's I, spatial regression, MGWR
- [x] Passenger-weighted reliability
- [ ] Maps in ArcGIS Pro
- [ ] StoryMap
- [ ] Public write-up
