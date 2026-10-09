# MBTA Bus Reliability and Equity

Do MBTA buses serving lower income, lower car ownership neighborhoods run less reliably than buses serving wealthier areas?

This project measures bus reliability across the MBTA network using the MBTA's published arrival and departure data, joins stops to census tracts, and compares reliability across neighborhood income and vehicle access.

## Data sources

| Dataset | Source | Where it goes |
|---|---|---|
| Bus Arrival Departure Times 2025 (CC0) | [MBTA Open Data Portal](https://mbta-massdot.opendata.arcgis.com/) | `data/raw/arrival_departure/` |
| MBTA GTFS static feed (stops, routes) | https://cdn.mbta.com/MBTA_GTFS.zip | `data/raw/gtfs/` |
| ACS 2020–2024 5-year estimates: median household income (B19013) and vehicles available (B08201) by tract | [U.S. Census Bureau API](https://www.census.gov/data/developers.html) | `data/raw/acs/` |
| Census tract boundaries, Massachusetts (TIGER/Line 2024) | [Census TIGER/Line](https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html) | `data/raw/tracts/` |

Raw data is not committed to the repo because the files are large. `src/download.py` fetches all of it.

## Repo layout

```
data/raw/        downloaded source files (gitignored)
data/processed/  cleaned outputs (gitignored)
notebooks/       exploration
src/             reusable cleaning and analysis code
figures/         charts and maps for the write-up
```

## Setup

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

The Census API needs a free key ([sign up here](https://api.census.gov/data/key_signup.html)). Put it in a `.env` file at the repo root:

```
CENSUS_API_KEY=your_key_here
```

Then download the data (about 400 MB, mostly the bus file):

```
python src/download.py
```

You can also fetch one source at a time: `python src/download.py bus gtfs tracts acs`.

Then clean the bus data and score every timepoint (about 40 seconds for the full year):

```
python src/clean.py
```

## Measuring reliability

Every timepoint crossing is scored on time or not using the MBTA's own rules from the [Service Delivery Policy](https://www.mbta.com/policies/service-delivery-policy) (December 2025, pp. 19–20):

| Standard | Origin | Mid-route | Destination |
|---|---|---|---|
| Schedule (headways over 15 min) | depart 0 to 3 min late | depart 1 min early to 6 min late | arrive no more than 5 min late |
| Headway (headways of 15 min or less) | gap to previous bus ≤ scheduled gap + 3 min | same | run time ≤ 120% of scheduled |

Across 2025 the network scores **69.8%** on time, close to the MBTA's 70% bus reliability target.

### Data quirks worth knowing

- **Times aren't UTC.** They're written like `1900-01-02T04:57:00Z`, but they're Boston local time plus a fixed 5 hours all year, ignoring daylight saving. Route 1's first weekday trip is 4:37 AM in GTFS and `09:37` in the data in both January and July. `clean.py` converts them to real local timestamps.
- **The data dictionary has the headway columns backwards.** `scheduled_headway` is only filled for schedule-standard trips, not headway-standard ones. The actual `headway` column is correct, so the scheduled gap is rebuilt from the timetable.
- **About 6% of timepoints have no actual time**, either dropped trips or collection gaps. They're kept with `on_time` empty. The MBTA counts dropped trips as failures, so treating them as failures gives a lower bound.

## Status

- [x] Repo set up
- [x] Bus, GTFS and tract data downloaded
- [x] ACS data downloaded
- [x] Cleaning pipeline
- [ ] Reliability metrics by route and stop
- [ ] Census join and maps
- [ ] Regression analysis
- [ ] Public write-up
