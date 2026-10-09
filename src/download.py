"""Download the raw data for the project into data/raw/.

Usage:
    python src/download.py            # everything
    python src/download.py acs tracts # just some sources

Files that already exist are skipped, so it's safe to re-run.
The ACS step needs a free Census API key in .env as CENSUS_API_KEY
(sign up at https://api.census.gov/data/key_signup.html).
"""

import os
import sys
import zipfile
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

# MBTA Open Data Portal item IDs for "MBTA Bus Arrival Departure Times <year>" (CC0)
BUS_ITEMS = {
    2025: "924df13d845f4907bb6a6c3ed380d57a",
}
GTFS_URL = "https://cdn.mbta.com/MBTA_GTFS.zip"
GTFS_ARCHIVE_INDEX = "https://cdn.mbta.com/archive/archived_feeds.txt"
# One schedule per season, so route stop lists match how each route ran in 2025
GTFS_2025_DATES = ["20250115", "20250415", "20250715", "20251015"]
TRACTS_URL = "https://www2.census.gov/geo/tiger/TIGER2024/TRACT/tl_2024_25_tract.zip"

ACS_YEAR = 2024  # 2020-2024 5-year estimates
ACS_VARS = {
    "B19013_001E": "median_hh_income",
    "B19013_001M": "median_hh_income_moe",
    "B08201_001E": "households",
    "B08201_002E": "households_no_vehicle",
    "B08201_002M": "households_no_vehicle_moe",
}
MA_FIPS = "25"


def fetch(url, dest):
    """Stream url to dest, skipping if it's already there."""
    if dest.exists():
        print(f"  exists, skipping: {dest.relative_to(ROOT)}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0))
        done = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  {done / 1e6:,.0f} / {total / 1e6:,.0f} MB", end="")
    print()
    tmp.replace(dest)
    return dest


def unzip(zip_path, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(out_dir)
    print(f"  extracted to {out_dir.relative_to(ROOT)}")


def bus():
    for year, item in BUS_ITEMS.items():
        print(f"Bus arrival/departure times {year}")
        url = f"https://www.arcgis.com/sharing/rest/content/items/{item}/data"
        z = fetch(url, RAW / "arrival_departure" / f"MBTA_Bus_Arrival_Departure_Times_{year}.zip")
        out = RAW / "arrival_departure" / str(year)
        if not out.exists():
            unzip(z, out)


def gtfs():
    print("MBTA GTFS static feed")
    z = fetch(GTFS_URL, RAW / "gtfs" / "MBTA_GTFS.zip")
    out = RAW / "gtfs" / "feed"
    if not out.exists():
        unzip(z, out)


def gtfs_2025():
    print("Archived MBTA GTFS feeds for 2025 (one per season)")
    index = pd.read_csv(GTFS_ARCHIVE_INDEX, dtype=str)
    for date in GTFS_2025_DATES:
        feed = index[(index.feed_start_date <= date) & (index.feed_end_date >= date)].iloc[0]
        print(f"  {date}: {feed.feed_version}")
        z = fetch(feed.archive_url, RAW / "gtfs_2025" / f"{date}.zip")
        out = RAW / "gtfs_2025" / date
        if not out.exists():
            unzip(z, out)


def tracts():
    print("Census tract boundaries (TIGER/Line 2024, Massachusetts)")
    fetch(TRACTS_URL, RAW / "tracts" / "tl_2024_25_tract.zip")  # geopandas reads the zip directly


def acs():
    print(f"ACS {ACS_YEAR} 5-year, Massachusetts tracts")
    dest = RAW / "acs" / f"acs5_{ACS_YEAR}_ma_tracts.csv"
    if dest.exists():
        print(f"  exists, skipping: {dest.relative_to(ROOT)}")
        return
    load_dotenv(ROOT / ".env")
    key = os.getenv("CENSUS_API_KEY")
    if not key:
        sys.exit("  CENSUS_API_KEY not set. Add it to .env (see the docstring at the top of this file).")
    r = requests.get(
        f"https://api.census.gov/data/{ACS_YEAR}/acs/acs5",
        params={
            "get": ",".join(["NAME", *ACS_VARS]),
            "for": "tract:*",
            "in": [f"state:{MA_FIPS}", "county:*"],
            "key": key,
        },
        timeout=60,
    )
    r.raise_for_status()
    header, *rows = r.json()
    df = pd.DataFrame(rows, columns=header).rename(columns=ACS_VARS)
    df["GEOID"] = df["state"] + df["county"] + df["tract"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(dest, index=False)
    print(f"  {len(df):,} tracts -> {dest.relative_to(ROOT)}")


SOURCES = {"bus": bus, "gtfs": gtfs, "gtfs_2025": gtfs_2025, "tracts": tracts, "acs": acs}

if __name__ == "__main__":
    wanted = sys.argv[1:] or list(SOURCES)
    unknown = set(wanted) - set(SOURCES)
    if unknown:
        sys.exit(f"Unknown source(s): {', '.join(sorted(unknown))}. Choose from {', '.join(SOURCES)}.")
    for name in wanted:
        SOURCES[name]()
