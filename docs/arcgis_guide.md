# ArcGIS Pro and StoryMap guide

The Python pipeline produces map-ready layers. This guide covers the parts done by hand in ArcGIS: the final maps, a hot spot analysis run with ArcGIS's own tool, and the public StoryMap.

## 0. Generate the layers

From the repo root, with the virtual environment active:

```
python src/clean.py
python src/walksheds.py
python src/equity.py
python src/spatial_stats.py
```

This writes two GeoPackages to `data/processed/gis/`. Both are in Massachusetts State Plane (EPSG:26986), so distances and areas are in meters.

| File | Layer | What it is | Key fields |
|---|---|---|---|
| `routes.gpkg` | `bus_routes` | Route lines (October 2025 schedule) | `on_time_rate`, `on_time_rate_pm_peak`, `share_no_vehicle`, `avg_median_income` |
| `routes.gpkg` | `route_walksheds` | Each route's quarter-mile street-network walkshed | same as above |
| `routes.gpkg` | `tracts_acs` | Census tracts with ACS 2020–2024 data | `households`, `households_no_vehicle`, `median_hh_income` |
| `stops.gpkg` | `timepoint_stops` | The ~1,100 stops where reliability is measured | `on_time_rate`, `gi_z`, `gi_q`, `hot_spot`, `share_no_vehicle` |

## 1. Set up the project

1. Open ArcGIS Pro, sign in with your Northeastern account, and create a new project from the **Map** template. Name it `mbta-bus-equity` and save it outside the repo, for example `Documents\ArcGIS\Projects`. Pro projects are large and don't belong in Git.
2. **Map** tab → **Add Data** → browse to `data\processed\gis\` → expand each `.gpkg` and add the four layers.
3. Set the map's coordinate system: right-click **Map** in the Contents pane → **Properties** → **Coordinate Systems** → search `26986` → **NAD 1983 StatePlane Massachusetts Mainland FIPS 2001 (Meters)**.
4. Add a quiet basemap: **Map** tab → **Basemap** → **Light Gray Canvas**.

## 2. Map 1: who depends on the bus

A choropleth of car-free households, the context map.

1. In the `tracts_acs` attribute table, add a field `pct_no_vehicle` (Double) and use **Calculate Field**: `!households_no_vehicle! / !households! * 100`. Tracts with zero households will error, so select `households > 0` first.
2. **Symbology** → **Graduated Colors** on `pct_no_vehicle`, **Natural Breaks**, 5 classes, a single-hue sequential ramp.
3. Overlay `bus_routes` as thin dark gray lines.

## 3. Map 2: route reliability

1. Symbolize `bus_routes` with **Graduated Colors** on `on_time_rate`. Use **Manual Interval** with a break at **0.70**, the MBTA's own target, so routes below target stand out. Use a diverging ramp centered on 0.70.
2. Make lines thicker (2–3 pt) and put `tracts_acs` underneath at about 60% transparency.
3. Label the worst routes: **Labeling** → expression `$feature.route_id`, with an SQL query `on_time_rate < 0.55`.

## 4. Map 3: hot spot analysis (Getis-Ord Gi*)

Run it yourself with ArcGIS's tool, then check it against the Python result.

1. **Analysis** tab → **Tools** → search **Hot Spot Analysis (Getis-Ord Gi\*)**.
2. Settings:
   - Input Features: `timepoint_stops`
   - Input Field: `on_time_rate`
   - Output: `stops_hotspots` in the project geodatabase
   - Conceptualization of Spatial Relationships: **K nearest neighbors**, Number of Neighbors: **8**
   - **Apply False Discovery Rate (FDR) Correction**: checked
3. Run it. ArcGIS colors **hot spots** (clusters of high on-time rates, meaning reliable service) red and **cold spots** (clusters of poor reliability) blue. For this project the cold spots are the story.
4. **Check your work:** compare the `Gi_Bin` field in your output to the `hot_spot` field computed in Python. They use the same statistic and settings, so the significant clusters should match closely. Small differences come from ArcGIS using analytic p-values where Python uses 9,999 permutations. Mention that agreement in your write-up, since it shows the result doesn't depend on the software.

## 5. Layouts for the write-up and resume

For each map: **Insert** → **New Layout** → **Letter Landscape**, then add:

- A map frame
- A title that states the finding, for example "Bus reliability is lowest where fewest households own cars"
- A legend
- A scale bar in miles
- A north arrow
- A source line: *Data: MBTA Bus Arrival Departure Times 2025; U.S. Census ACS 2020–2024; OpenStreetMap. Map: Alex Weinstein.*

**Share** → **Export Layout** → PNG at 300 dpi into the repo's `figures/` folder, so the maps show up on GitHub.

## 6. StoryMap

1. **Publish the layers:** in Pro, right-click each finished map → **Share As Web Map**. Sharing level: **Everyone**, folder `mbta-bus-equity`. This uploads the layers to ArcGIS Online with your symbology.
2. **Create the story:** at [storymaps.arcgis.com](https://storymaps.arcgis.com), sign in with your Northeastern account → **New story** → **Start from scratch**.
3. **Suggested structure** (aim for a 5–7 minute read):
   1. **Title and hook:** one sentence on the stakes. About a third of Boston households don't own a car, so for them the bus isn't optional.
   2. **The question**, with Map 1 as an express map or embedded web map.
   3. **How reliability is measured:** the MBTA's own on-time rules, in plain language.
   4. **What the data shows:** Map 2 with a **sidecar** block, stepping through the least reliable routes and the neighborhoods they serve.
   5. **Where the problems cluster:** Map 3, the hot spots.
   6. **Does it hold up?** The spatial regression in plain terms, what it shows and what it doesn't.
   7. **What this means for policy:** two or three concrete recommendations, for example bus lanes or transit signal priority on the corridors in the cold spots.
   8. **Methods and data:** a short section linking to the GitHub repo.
4. **Publish** with sharing set to **Everyone**. Then put the link in the repo README and on your resume.

**Tip:** a StoryMap on an institutional account can disappear when the account ends, for example after graduation. Export the finished maps as PNGs into `figures/` so the GitHub repo can stand on its own.
