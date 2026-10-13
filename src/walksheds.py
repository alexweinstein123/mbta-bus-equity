"""Build a street-network walkshed for every bus stop.

Usage:
    python src/walksheds.py              # all stops
    python src/walksheds.py --sample 30  # time a few stops first
    python src/walksheds.py --workers 6  # parallel processes (default 1)

Writes data/processed/stop_walksheds.gpkg with one polygon per stop: the
area reachable by walking a quarter mile (402 m) along OpenStreetMap streets
and paths. Unlike a circle, this respects rivers, highways, rail lines and
dead ends, so a stop across the Mystic River doesn't "serve" the other bank.

Method:
  1. Download the OSM walking network around all 2025 bus stops. The raw
     download and a prepared copy are cached in data/raw/osm/, so only the
     first run is slow.
  2. Snap each stop to its nearest street node; the walk to that node comes
     out of the 402 m budget.
  3. Find every street segment reachable within the remaining budget, cutting
     segments partway where the budget runs out.
  4. Buffer those segments by 50 m, roughly a lot's depth, so the walkshed
     covers the buildings that front the streets, not just the centerlines.
"""

import argparse
import pickle
import time
from multiprocessing import Pool
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd
import shapely
from shapely import Point
from shapely.ops import substring

import equity

ROOT = Path(__file__).resolve().parents[1]
GRAPH = ROOT / "data" / "raw" / "osm" / "walk_network.graphml"
PREPARED = ROOT / "data" / "raw" / "osm" / "walk_network_prepared.pkl"
OUT = ROOT / "data" / "processed" / "stop_walksheds.gpkg"

WALK_M = equity.WALK_M
FRONTAGE_M = 50
MA_METERS = equity.MA_METERS


def load_network(stops):
    """Undirected walk network plus u->v oriented edge geometries, cached after the first build."""
    if PREPARED.exists():
        with open(PREPARED, "rb") as f:
            H, geoms = pickle.load(f)
        H.graph.setdefault("crs", MA_METERS)  # OSMnx needs this to snap stops to streets
        return H, geoms
    if GRAPH.exists():
        print("Loading the saved street network (first run only, slow)...")
        G = ox.load_graphml(GRAPH)
    else:
        print("Downloading the OpenStreetMap walking network (first run only, can take 10+ minutes)...")
        area = gpd.GeoSeries([stops.buffer(800).union_all().simplify(100)], crs=MA_METERS).to_crs("EPSG:4326")
        G = ox.graph_from_polygon(area.iloc[0], network_type="walk", retain_all=True)
        G = ox.project_graph(G, to_crs=MA_METERS)
        GRAPH.parent.mkdir(parents=True, exist_ok=True)
        ox.save_graphml(G, GRAPH)
    print("Preparing the network...")
    G = ox.convert.to_undirected(G)
    geoms = edge_geometries(G)
    # keep only what the walkshed search needs, so the cache loads fast
    H = nx.MultiGraph(crs=G.graph["crs"])
    H.add_nodes_from((n, {"x": d["x"], "y": d["y"]}) for n, d in G.nodes(data=True))
    H.add_edges_from((u, v, k, {"length": d["length"]}) for u, v, k, d in G.edges(keys=True, data=True))
    with open(PREPARED, "wb") as f:
        pickle.dump((H, geoms), f, protocol=pickle.HIGHEST_PROTOCOL)
    return H, geoms


def edge_geometries(G):
    """Edge geometry oriented from u to v, keyed by (u, v, key) and (v, u, key)."""
    edges = ox.graph_to_gdfs(G, nodes=False, fill_edge_geometry=True)
    u = edges.index.get_level_values(0)
    starts = shapely.get_point(edges.geometry.values, 0)
    u_pts = shapely.points(np.array([[G.nodes[n]["x"], G.nodes[n]["y"]] for n in u]))
    flip = shapely.distance(starts, u_pts) > 1
    fwd = np.where(flip, shapely.reverse(edges.geometry.values), edges.geometry.values)
    rev = shapely.reverse(fwd)
    geoms = {}
    for (a, b, k), f, r in zip(edges.index, fwd, rev):
        geoms[(a, b, k)] = f
        geoms[(b, a, k)] = r
    return geoms


def walkshed(G, geoms, node, budget):
    dist = nx.single_source_dijkstra_path_length(G, node, cutoff=budget, weight="length")
    pieces = []
    for u, du in dist.items():
        for v, keys in G[u].items():
            dv = dist.get(v)
            for k, data in keys.items():
                if dv is not None and du + dv + data["length"] <= 2 * budget:
                    # every point on the segment is within budget from one end or the other; add it once
                    if u <= v:
                        pieces.append(geoms[(u, v, k)])
                else:
                    # the budget runs out partway along; cover what's reachable from this end
                    pieces.append(substring(geoms[(u, v, k)], 0, budget - du))
    if not pieces:
        return Point(G.nodes[node]["x"], G.nodes[node]["y"]).buffer(FRONTAGE_M)
    # buffering the pieces together lets GEOS merge polygons, which is far faster than noding the lines first
    return shapely.buffer(shapely.multilinestrings(pieces), FRONTAGE_M, quad_segs=4)


_net = None


def _init_worker():
    global _net
    _net = load_network(None)


def _walkshed_task(args):
    node, budget, fallback = args
    G, geoms = _net
    return walkshed(G, geoms, node, budget) if budget > 0 else fallback


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, help="only build this many stops and report the speed")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    rel = equity.route_reliability()
    stops = equity.route_stops(set(rel.route_id)).drop_duplicates("stop_id")[["stop_id", "geometry"]]
    if args.sample:
        stops = stops.sample(args.sample, random_state=0)
    G, geoms = load_network(stops)

    nodes, snap = ox.distance.nearest_nodes(G, stops.geometry.x, stops.geometry.y, return_dist=True)
    tasks = [
        (node, WALK_M - d, stop.buffer(FRONTAGE_M))
        for node, d, stop in zip(nodes, snap, stops.geometry)
    ]
    print(f"Building {len(tasks):,} walksheds with {args.workers} worker(s)...")
    start = time.time()
    if args.workers > 1:
        del G, geoms
        with Pool(args.workers, initializer=_init_worker) as pool:
            shapes = []
            for i, shape in enumerate(pool.imap(_walkshed_task, tasks, chunksize=20)):
                shapes.append(shape)
                if (i + 1) % 500 == 0:
                    print(f"  {i + 1:,} / {len(tasks):,} stops  ({time.time() - start:,.0f} s)")
    else:
        global _net
        _net = (G, geoms)
        shapes = []
        for i, t in enumerate(tasks):
            shapes.append(_walkshed_task(t))
            if (i + 1) % 500 == 0:
                print(f"  {i + 1:,} / {len(tasks):,} stops  ({time.time() - start:,.0f} s)")
    elapsed = time.time() - start
    print(f"Built {len(shapes):,} walksheds in {elapsed:,.1f} s ({elapsed / len(shapes):.2f} s per stop)")

    out = gpd.GeoDataFrame(
        {"stop_id": stops.stop_id.values, "snap_m": pd.Series(snap).round(1).values},
        geometry=shapes, crs=MA_METERS,
    )
    out["walkshed_km2"] = (out.area / 1e6).round(4)
    out["circle_ratio"] = (out.area / (np.pi * (WALK_M + FRONTAGE_M) ** 2)).round(3)
    print(f"Median walkshed covers {out.circle_ratio.median():.0%} of a same-radius circle; "
          f"{(out.snap_m > 100).sum()} stops are over 100 m from a mapped street")
    if args.sample:
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_file(OUT, layer="stop_walksheds", driver="GPKG")
    print(f"Wrote {OUT.relative_to(ROOT)}: {len(out):,} walksheds")


if __name__ == "__main__":
    main()
