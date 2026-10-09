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

## Status

- [x] Repo set up
- [ ] Raw data downloaded
- [ ] Cleaning pipeline
- [ ] Reliability metrics by route and stop
- [ ] Census join and maps
- [ ] Regression analysis
- [ ] Public write-up
