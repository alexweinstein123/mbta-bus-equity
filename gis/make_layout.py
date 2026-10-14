"""Build the map layouts in an ArcGIS Pro project and export them.

Run with ArcGIS Pro's Python (arcpy), not the project's .venv:
    "C:\\Program Files\\ArcGIS\\Pro\\bin\\Python\\envs\\arcgispro-py3\\python.exe" gis/make_layout.py PROJECT.aprx preview
    ... gis/make_layout.py PROJECT.aprx save            # close ArcGIS Pro first
    ... gis/make_layout.py PROJECT.aprx save hotspots   # one layout only (main or hotspots)

preview exports low-resolution PNGs to a temp folder without changing the project.
save adds the layouts to the project and exports 300 dpi PNGs and PDFs to figures/.

Both layouts share one page design: title and subtitle, the map on the left, the
legend in a right-hand column, and a source line with the basemap credits.

  main      "Bus reliability" map: timepoint stops by on-time rate over car-free
            households, with an inset of downtown Boston and Cambridge.
  carfree   "Car-free households" map: the context map of households without a car,
            with the same inset.
  hotspots  "Hot spots" map: the Hot Spot Analysis (Getis-Ord Gi*) output run in
            ArcGIS Pro on the stops layer, with labels on the main clusters.

The maps are built from the GeoPackages in data/processed/gis/ (see docs/arcgis_guide.md).
"""

import sys
import tempfile
from pathlib import Path

import arcpy

FIGURES = Path(__file__).resolve().parents[1] / "figures"

FONT = "Segoe UI"
INK = [33, 37, 41, 100]
MUTED = [95, 99, 104, 100]

# page layout, inches (11 x 8.5 landscape)
W, H, M = 11.0, 8.5, 0.4
MAIN = (M, 0.95, 7.35, 7.25)          # map frame: xmin, ymin, xmax, ymax
COL_X = 7.6                            # right column
INSET = (COL_X, 4.55, W - M, 7.25)

DATA = ("Data: MBTA Bus Arrival Departure Times 2025; MBTA GTFS, October 2025; "
        "U.S. Census Bureau ACS 2020–2024 5-year estimates. ")

# shared with the main map: orange = worse, teal = better
ORANGES = [[230, 76, 0], [242, 125, 30], [253, 174, 97]]   # 99%, 95%, 90%
TEALS = [[128, 205, 193], [53, 151, 143], [1, 102, 94]]    # 90%, 95%, 99%

LAYOUTS = {
    "main": {
        "name": "Main map - bus reliability",
        "map": "Bus reliability",
        "file": "map_bus_reliability",
        "title": "Buses run least reliably in outer, car-owning areas, not in car-free neighborhoods",
        "subtitle": "Share of 2025 bus timepoints on time, over the share of households without a car",
        "source": "On time per MBTA Service Delivery Policy standards (target: 70%). Tracts with fewer than 100 households hatched. ",
        "inset": ("Downtown Boston and Cambridge", (-71.078, 42.352), 3800),
    },
    "carfree": {
        "name": "Context map - car-free households",
        "map": "Car-free households",
        "file": "map_carfree_households",
        "title": "Car-free households are concentrated in Boston's core",
        "subtitle": "Share of households without a car by census tract, with MBTA bus routes",
        "data": "Data: U.S. Census Bureau ACS 2020–2024 5-year estimates; MBTA GTFS, October 2025. ",
        "source": "Tracts with fewer than 100 households hatched. ",
        "inset": ("Downtown Boston and Cambridge", (-71.078, 42.352), 3800),
    },
    "hotspots": {
        "name": "Hot spot map - reliability clusters",
        "map": "Hot spots",
        "file": "map_reliability_clusters",
        "title": "Unreliable buses cluster near Alewife and on the North Shore",
        "subtitle": "Statistically significant clusters of 2025 bus on-time rates (Getis-Ord Gi*)",
        "source": ("Clusters from Hot Spot Analysis (Getis-Ord Gi*) in ArcGIS Pro on the on-time rate of 1,117 timepoint stops: "
                   "8 nearest neighbors, false discovery rate correction. Replicated in Python (PySAL) with identical results. "),
        # (label, lon, lat, cluster sign, search radius in meters, label offset in inches)
        "callouts": [
            ("Alewife and North Cambridge", -71.14, 42.395, -1, 3000, (-1.55, 0.2)),
            ("Lynn and Saugus", -70.98, 42.47, -1, 4500, (0.2, 0.15)),
            ("Chelsea, East Boston and Winthrop", -71.01, 42.38, 1, 4500, (0.62, -0.05)),
        ],
        "note": ("How to read this map: each dot is a timepoint stop. Colored stops sit in a statistically "
                 "significant cluster, where nearby stops are unusually unreliable (orange) or reliable (teal) "
                 "together. Larger dots mean higher confidence. Gray stops are not part of a significant cluster."),
    },
}


def rgb(values):
    c = arcpy.cim.CreateCIMObjectFromClassName("CIMRGBColor", "V3")
    c.values = list(values) + ([100] if len(values) == 3 else [])
    return c


def text(p, lyt, x, y, s, size, style="Regular", color=INK, name=None, width=None, height=0.45, halo=False):
    if width:
        geom = arcpy.Polygon(arcpy.Array([arcpy.Point(x, y), arcpy.Point(x + width, y), arcpy.Point(x + width, y + height),
                                          arcpy.Point(x, y + height)]))
        el = p.createTextElement(lyt, geom, "POLYGON", s, size, FONT, style, name=name)
    else:
        el = p.createTextElement(lyt, arcpy.Point(x, y), "POINT", s, size, FONT, style, name=name)
    cim = el.getDefinition("V3")
    sym = cim.graphic.symbol.symbol
    sym.symbol.symbolLayers[0].color = rgb(color)
    if halo:  # white outline so labels stay legible over the map
        fill = arcpy.cim.CreateCIMObjectFromClassName("CIMSolidFill", "V3")
        fill.color, fill.enable = rgb([255, 255, 255, 100]), True
        halo_poly = arcpy.cim.CreateCIMObjectFromClassName("CIMPolygonSymbol", "V3")
        halo_poly.symbolLayers = [fill]
        sym.haloSymbol, sym.haloSize = halo_poly, 1.5
    el.setDefinition(cim)
    return el


def layer_by_source(m, suffix):
    return next(l for l in m.listLayers() if l.supports("DATASOURCE") and l.dataSource.lower().endswith(suffix.lower()))


def fit_extent(mf, layer, pad=0.02):
    ext = arcpy.Describe(layer).extent
    px, py = (ext.XMax - ext.XMin) * pad, (ext.YMax - ext.YMin) * pad
    mf.camera.setExtent(arcpy.Extent(ext.XMin - px, ext.YMin - py, ext.XMax + px, ext.YMax + py))


def to_page(mf, frame, x, y):
    """Map coordinates -> page inches inside a map frame."""
    e = mf.camera.getExtent()
    return (frame[0] + (x - e.XMin) / (e.XMax - e.XMin) * (frame[2] - frame[0]),
            frame[1] + (y - e.YMin) / (e.YMax - e.YMin) * (frame[3] - frame[1]))


def projected(m, lon, lat):
    return arcpy.PointGeometry(arcpy.Point(lon, lat), arcpy.SpatialReference(4326)).projectAs(m.spatialReference).firstPoint


def prepare_main(p, m):
    stops = layer_by_source(m, "timepoint_stops")
    stops.name = "Bus on-time rate, 2025"
    lyr = {l.name: l for l in m.listLayers()}
    # legend order: on-time classes, then car-free classes, then the hatched tracts (they never overlap on the map)
    m.moveLayer(lyr["Households without a car"], lyr["Fewer than 100 households"], "AFTER")
    return stops


def prepare_carfree(p, m):
    lyr = {l.name: l for l in m.listLayers()}
    m.moveLayer(lyr["Households without a car"], lyr["Fewer than 100 households"], "AFTER")
    routes = layer_by_source(m, "bus_routes")
    routes.transparency = 50  # context only on this map
    return routes  # frame on the bus network, like the other maps


def prepare_hotspots(p, m):
    clusters = next(l for l in m.listLayers() if l.isFeatureLayer and l.visible and "hotspots" in l.dataSource.lower())
    clusters.name = "Reliability clusters"
    colors = {-3: ORANGES[0], -2: ORANGES[1], -1: ORANGES[2], 0: [190, 190, 190], 1: TEALS[0], 2: TEALS[1], 3: TEALS[2]}
    labels = {0: "Not significant"}
    for k, conf in ((1, "90%"), (2, "95%"), (3, "99%")):
        labels[-k], labels[k] = f"Unreliable cluster, {conf} confidence", f"Reliable cluster, {conf} confidence"
    # colors through arcpy symbology, which regenerates the class labels...
    sym = clusters.symbology
    for b in sym.renderer.classBreaks:
        k = int(round(b.upperBound))
        b.symbol.color = {"RGB": colors[k] + [100]}
        b.symbol.outlineColor = {"RGB": ([255, 255, 255] if k else [190, 190, 190]) + [100]}
    clusters.symbology = sym
    # ...so labels and heading go in afterward through the layer's CIM
    cim = clusters.getDefinition("V3")
    for brk in cim.renderer.breaks:
        brk.label = labels[int(round(brk.upperBound))]
    cim.renderer.heading = "Clusters of on-time rate (Getis-Ord Gi*)"
    clusters.setDefinition(cim)
    return clusters


def build(p, key, mode):
    cfg = LAYOUTS[key]
    m = p.listMaps(cfg["map"])[0]
    data_layer = {"main": prepare_main, "carfree": prepare_carfree, "hotspots": prepare_hotspots}[key](p, m)

    for old in p.listLayouts(cfg["name"]):
        p.deleteItem(old)
    lyt = p.createLayout(W, H, "INCH", cfg["name"])
    main_mf = lyt.createMapFrame(arcpy.Extent(*MAIN), m, "Main map")
    fit_extent(main_mf, data_layer)

    legend_top = 7.25
    if "inset" in cfg:
        label, (lon, lat), half = cfg["inset"]
        inset_mf = lyt.createMapFrame(arcpy.Extent(*INSET), m, "Inset map")
        c = projected(m, lon, lat)
        inset_mf.camera.setExtent(arcpy.Extent(c.X - half, c.Y - half, c.X + half, c.Y + half))
        # box on the main map showing the inset's extent
        cim = lyt.getDefinition("V3")
        stroke = arcpy.cim.CreateCIMObjectFromClassName("CIMSolidStroke", "V3")
        stroke.width, stroke.color, stroke.enable = 1.25, rgb([20, 20, 20]), True
        poly = arcpy.cim.CreateCIMObjectFromClassName("CIMPolygonSymbol", "V3")
        poly.symbolLayers = [stroke]
        ref = arcpy.cim.CreateCIMObjectFromClassName("CIMSymbolReference", "V3")
        ref.symbol = poly
        ind = arcpy.cim.CreateCIMObjectFromClassName("CIMExtentIndicator", "V3")
        ind.sourceMapFrame, ind.symbol = "Inset map", ref
        next(e for e in cim.elements if e.name == "Main map").extentIndicators = [ind]
        lyt.setDefinition(cim)
        text(p, lyt, COL_X, INSET[3] + 0.08, label, 10, "Bold", name="Inset label")
        legend_top = INSET[1] - 0.3

    # legend: data layers only
    style = p.listStyleItems("ArcGIS 2D", "LEGEND", "Headings and Medium Text Legend")[0]
    legend = lyt.createMapSurroundElement(arcpy.Extent(COL_X, 0.95, W - M, legend_top), "LEGEND", main_mf, style, "Legend")
    legend.showTitle = False

    sb_style = p.listStyleItems("ArcGIS 2D", "SCALE_BAR", "Scale Line 1")[0]
    lyt.createMapSurroundElement(arcpy.Point(MAIN[0] + 0.2, MAIN[1] + 0.2), "SCALE_BAR", main_mf, sb_style, "Scale bar")
    na_style = p.listStyleItems("ArcGIS 2D", "NORTH_ARROW", "ArcGIS North 1")[0]
    lyt.createMapSurroundElement(arcpy.Point(MAIN[2] - 0.5, MAIN[1] + 0.3), "NORTH_ARROW", main_mf, na_style, "North arrow")

    hidden = ("MBTA bus routes", "Light Gray Base", "Light Gray Reference")
    cim = lyt.getDefinition("V3")
    for e in cim.elements:
        if e.name == "Scale bar":
            e.division, e.divisions, e.subdivisions, e.fittingStrategy = 5, 2, 1, "AdjustFrame"  # 0, 5, 10 miles
            e.labelFrequency, e.markFrequency = "Divisions", "Divisions"
        if e.name == "Legend":
            e.autoAdd, e.autoFonts, e.fittingStrategy = False, False, "AdjustFrame"
            e.itemGap, e.classGap, e.headingGap, e.patchGap, e.textGap = 9, 4, 5, 6, 6
            # only layers drawn on this map, minus basemap and routes
            visible = {l.name for l in m.listLayers() if l.visible}
            e.items = [i for i in e.items if i.name not in hidden and i.name in visible]
            for item in e.items:
                single = item.name == "Fewer than 100 households"  # single symbol: its class label is the layer name
                item.showLayerName, item.showHeading = False, not single
                for sym, size, fstyle in ((item.headingSymbol, 10, "Semibold"), (item.labelSymbol, 9, "Regular"),
                                          (item.layerNameSymbol, 9, "Regular")):
                    sym.symbol.height, sym.symbol.fontFamilyName, sym.symbol.fontStyleName = size, FONT, fstyle
                item.patchWidth, item.patchHeight = 15, 10
    lyt.setDefinition(cim)
    na = lyt.listElements("MAPSURROUND_ELEMENT", "North arrow")[0]
    na.elementHeight = 0.45
    na.elementPositionX, na.elementPositionY = MAIN[2] - 0.5, MAIN[1] + 0.3

    # labels on the main clusters, placed at the centroid of each cluster's significant stops
    for label, lon, lat, sign, radius, (dx, dy) in cfg.get("callouts", []):
        seed = projected(m, lon, lat)
        pts = [shape.firstPoint for shape, b in arcpy.da.SearchCursor(data_layer, ["SHAPE@", "Gi_Bin"])
               if b * sign > 0 and ((shape.firstPoint.X - seed.X) ** 2 + (shape.firstPoint.Y - seed.Y) ** 2) ** 0.5 <= radius]
        if not pts:
            print(f"  no significant stops near {label}; label skipped")
            continue
        cx, cy = sum(pt.X for pt in pts) / len(pts), sum(pt.Y for pt in pts) / len(pts)
        px, py = to_page(main_mf, MAIN, cx, cy)
        text(p, lyt, px + dx, py + dy, label, 9, "Semibold", name=f"Callout: {label}", halo=True)
        print(f"  {label}: {len(pts)} stops")

    if "note" in cfg:
        text(p, lyt, COL_X, 0.95, cfg["note"], 8.5, color=MUTED, name="How to read", width=W - M - COL_X, height=1.3)

    credits = f'Map: Alex Weinstein, 2026. Basemap <dyn type="layout" name="{cfg["name"]}" property="serviceLayerCredits"/>'
    text(p, lyt, M, H - M - 0.36, cfg["title"], 18, "Bold", name="Title")
    text(p, lyt, M, H - M - 0.68, cfg["subtitle"], 11.5, color=MUTED, name="Subtitle")
    text(p, lyt, M, 0.22, cfg.get("data", DATA) + cfg["source"] + credits, 7, color=MUTED, name="Source", width=W - 2 * M)

    if mode == "preview":
        out = Path(tempfile.gettempdir()) / f"{cfg['file']}_preview.png"
        lyt.exportToPNG(str(out), resolution=110)
        print(f"{key}: preview {out}")
    else:
        FIGURES.mkdir(exist_ok=True)
        lyt.exportToPNG(str(FIGURES / f"{cfg['file']}.png"), resolution=300)
        lyt.exportToPDF(str(FIGURES / f"{cfg['file']}.pdf"), resolution=300)
        print(f"{key}: exported figures/{cfg['file']}.png and .pdf")


def main(aprx, mode, keys):
    p = arcpy.mp.ArcGISProject(aprx)
    for key in keys:
        build(p, key, mode)
    if mode == "save":
        p.save()
        print("saved layouts to the project")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or (len(args) > 1 and args[1] not in ("preview", "save")) or any(k not in LAYOUTS for k in args[2:]):
        sys.exit(f"usage: make_layout.py PROJECT.aprx [preview|save] [{'|'.join(LAYOUTS)} ...]")
    main(args[0], args[1] if len(args) > 1 else "preview", args[2:] or list(LAYOUTS))
