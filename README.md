\# MBTA Bus Reliability and Equity



Do MBTA buses serving lower income, lower car ownership neighborhoods run less reliably than buses serving wealthier areas?



This project measures bus reliability across the MBTA network using the MBTA's published arrival and departure data, joins stops to census tracts, and compares reliability across neighborhood income and vehicle access.



\## Data sources



| Dataset | Source | Where it goes |

|---|---|---|

| Bus Arrival Departure Times 2025 | MBTA Blue Book Open Data Portal (mbta-massdot.opendata.arcgis.com) | `data/raw/arrival\_departure/` |

| MBTA GTFS static feed (stops, routes) | https://cdn.mbta.com/MBTA\_GTFS.zip | `data/raw/gtfs/` |

| ACS 5-year estimates, household income (B19013) and vehicles available (B08201) by tract | U.S. Census Bureau API | `data/raw/acs/` |

| Census tract boundaries, Massachusetts | Census TIGER/Line | `data/raw/tracts/` |



Raw data is not committed to the repo because the files are large.



\## Repo layout



```

data/raw/        downloaded source files (gitignored)

data/processed/  cleaned outputs (gitignored)

notebooks/       exploration

src/             reusable cleaning and analysis code

figures/         charts and maps for the write-up

```



\## Setup



```

python -m venv .venv

.venv\\Scripts\\activate

pip install -r requirements.txt

```



\## Status



\- \[x] Repo set up

\- \[ ] Raw data downloaded

\- \[ ] Cleaning pipeline

\- \[ ] Reliability metrics by route and stop

\- \[ ] Census join and maps

\- \[ ] Regression analysis

\- \[ ] Public write-up

