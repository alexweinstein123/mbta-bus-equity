"""Build the main reliability map layout in an ArcGIS Pro project and export it.

Run with ArcGIS Pro's Python (arcpy), not the project's .venv:
    "C:\\Program Files\\ArcGIS\\Pro\\bin\\Python\\envs\\arcgispro-py3\\python.exe" gis/make_layout.py PROJECT.aprx preview
    ... gis/make_layout.py PROJECT.aprx save   # close ArcGIS Pro first

preview exports a low-resolution PNG to a temp folder without changing the project.
save adds the layout to the project and exports figures/map_bus_reliability.png (300 dpi) and .pdf.

Expects a map containing the timepoint_stops layer (symbolized by on-time rate), the
"Households without a car" and "Fewer than 100 households" tract layers, MBTA bus routes and
the Esri Light Gray Canvas basemap, built from the GeoPackages in data/processed/gis/.
"""

import sys
import tempfile
from pathlib import Path

import arcpy

FIGURES = Path(__file__).resolve().parents[1] / "figures"
PREVIEW = Path(tempfile.gettempdir()) / "map_bus_reliability_preview.png"
LAYOUT_NAME = "Main map - bus reliability"

TITLE = "Buses run least reliably in outer, car-owning areas, not in car-free neighborhoods"
SUBTITLE = "Share of 2025 bus timepoints on time, over the share of households without a car"
INSET_LABEL = "Downtown Boston and Cambridge"
SOURCE = (
    "Data: MBTA Bus Arrival Departure Times 2025; MBTA GTFS, October 2025; U.S. Census Bureau ACS 2020–2024 5-year estimates. "
    "On time per MBTA Service Delivery Policy standards (target: 70%). Tracts with fewer than 100 households hatched. "
    # service layer credits as dynamic text: ArcGIS then stops stamping credits inside the map frames
    f'Map: Alex Weinstein, 2026. Basemap <dyn type="layout" name="{LAYOUT_NAME}" property="serviceLayerCredits"/>'
)

FONT = "Segoe UI"
INK = [33, 37, 41, 100]
MUTED = [95, 99, 104, 100]

# page layout, inches (11 x 8.5 landscape)
W, H, M = 11.0, 8.5, 0.4
MAIN = (M, 0.95, 7.35, 7.25)          # xmin, ymin, xmax, ymax
COL_X = 7.6                            # right column
INSET = (COL_X, 4.55, W - M, 7.25)
LEGEND = (COL_X, 0.95, W - M, 4.25)


def rgb(values):
    c = arcpy.cim.CreateCIMObjectFromClassName("CIMRGBColor", "V3")
    c.values = values
    return c


def text(p, lyt, x, y, s, size, style="Regular", color=INK, name=None, width=None):
    if width:
        geom = arcpy.Polygon(arcpy.Array([arcpy.Point(x, y), arcpy.Point(x + width, y), arcpy.Point(x + width, y + 0.45),
                                          arcpy.Point(x, y + 0.45)]))
        el = p.createTextElement(lyt, geom, "POLYGON", s, size, FONT, style, name=name)
    else:
        el = p.createTextElement(lyt, arcpy.Point(x, y), "POINT", s, size, FONT, style, name=name)
    cim = el.getDefinition("V3")
    cim.graphic.symbol.symbol.symbol.symbolLayers[0].color = rgb(color)
    el.setDefinition(cim)
    return el


def find_layer(m, suffix):
    return next(l for l in m.listLayers() if l.supports("DATASOURCE") and l.dataSource.lower().endswith(suffix))


def main(aprx, mode):
    p = arcpy.mp.ArcGISProject(aprx)
    m = next(mp for mp in p.listMaps()
             if any(l.supports("DATASOURCE") and l.dataSource.lower().endswith("timepoint_stops") for l in mp.listLayers()))
    stops = find_layer(m, "timepoint_stops")
    stops.name = "Bus on-time rate, 2025"
    m.name = "Bus reliability"

    # legend order: on-time classes, then car-free classes, then the hatched tracts (they never overlap on the map)
    lyr = {l.name: l for l in m.listLayers()}
    m.moveLayer(lyr["Households without a car"], lyr["Fewer than 100 households"], "AFTER")

    for old in p.listLayouts(LAYOUT_NAME):
        p.deleteItem(old)
    lyt = p.createLayout(W, H, "INCH", LAYOUT_NAME)

    # main map: the whole network
    main_mf = lyt.createMapFrame(arcpy.Extent(*MAIN), m, "Main map")
    ext = arcpy.Describe(stops).extent
    pad_x, pad_y = (ext.XMax - ext.XMin) * 0.02, (ext.YMax - ext.YMin) * 0.02
    main_mf.camera.setExtent(arcpy.Extent(ext.XMin - pad_x, ext.YMin - pad_y, ext.XMax + pad_x, ext.YMax + pad_y))

    # inset: downtown Boston and Cambridge
    inset_mf = lyt.createMapFrame(arcpy.Extent(*INSET), m, "Inset map")
    c = arcpy.PointGeometry(arcpy.Point(-71.078, 42.352), arcpy.SpatialReference(4326)).projectAs(m.spatialReference).firstPoint
    half = 3800  # meters
    inset_mf.camera.setExtent(arcpy.Extent(c.X - half, c.Y - half, c.X + half, c.Y + half))

    # box on the main map showing the inset's extent
    cim = lyt.getDefinition("V3")
    stroke = arcpy.cim.CreateCIMObjectFromClassName("CIMSolidStroke", "V3")
    stroke.width, stroke.color, stroke.enable = 1.25, rgb([20, 20, 20, 100]), True
    poly = arcpy.cim.CreateCIMObjectFromClassName("CIMPolygonSymbol", "V3")
    poly.symbolLayers = [stroke]
    ref = arcpy.cim.CreateCIMObjectFromClassName("CIMSymbolReference", "V3")
    ref.symbol = poly
    ind = arcpy.cim.CreateCIMObjectFromClassName("CIMExtentIndicator", "V3")
    ind.sourceMapFrame, ind.symbol = "Inset map", ref
    next(e for e in cim.elements if e.name == "Main map").extentIndicators = [ind]
    lyt.setDefinition(cim)

    # legend: data layers only
    style = p.listStyleItems("ArcGIS 2D", "LEGEND", "Headings and Medium Text Legend")[0]
    legend = lyt.createMapSurroundElement(arcpy.Extent(*LEGEND), "LEGEND", main_mf, style, "Legend")
    for item in list(legend.items):
        if item.name in ("Light Gray Base", "Light Gray Reference", "MBTA bus routes"):
            legend.removeItem(item)
    legend.title, legend.showTitle = "Legend", False

    # scale bar and north arrow, inside the main map's lower left
    sb_style = p.listStyleItems("ArcGIS 2D", "SCALE_BAR", "Scale Line 1")[0]
    sb = lyt.createMapSurroundElement(arcpy.Point(MAIN[0] + 0.2, MAIN[1] + 0.2), "SCALE_BAR", main_mf, sb_style, "Scale bar")
    na_style = p.listStyleItems("ArcGIS 2D", "NORTH_ARROW", "ArcGIS North 1")[0]
    na = lyt.createMapSurroundElement(arcpy.Point(MAIN[0] + 0.25, MAIN[1] + 0.75), "NORTH_ARROW", main_mf, na_style, "North arrow")

    cim = lyt.getDefinition("V3")
    for e in cim.elements:
        if e.name == "Scale bar":
            e.division, e.divisions, e.subdivisions, e.fittingStrategy = 5, 2, 1, "AdjustFrame"  # 0, 5, 10 miles
            e.labelFrequency, e.markFrequency = "Divisions", "Divisions"  # no midpoint label
        if e.name == "Legend":
            e.autoAdd, e.autoFonts, e.fittingStrategy = False, False, "AdjustFrame"
            e.itemGap, e.classGap, e.headingGap, e.patchGap, e.textGap = 9, 4, 5, 6, 6
            e.items = [i for i in e.items if i.name not in ("MBTA bus routes", "Light Gray Base", "Light Gray Reference")]
            for item in e.items:
                single = item.name == "Fewer than 100 households"  # single symbol: its class label is the layer name
                item.showLayerName, item.showHeading = False, not single
                for sym, size, style in ((item.headingSymbol, 10, "Semibold"), (item.labelSymbol, 9, "Regular"),
                                         (item.layerNameSymbol, 9, "Regular")):
                    sym.symbol.height, sym.symbol.fontFamilyName, sym.symbol.fontStyleName = size, FONT, style
                item.patchWidth, item.patchHeight = 15, 10
    lyt.setDefinition(cim)
    # north arrow in the main map's lower right, clear of the scale bar
    na = lyt.listElements("MAPSURROUND_ELEMENT", "North arrow")[0]
    na.elementHeight = 0.45
    na.elementPositionX, na.elementPositionY = MAIN[2] - 0.5, MAIN[1] + 0.3

    # text
    text(p, lyt, M, H - M - 0.36, TITLE, 18, "Bold", name="Title")
    text(p, lyt, M, H - M - 0.68, SUBTITLE, 11.5, color=MUTED, name="Subtitle")
    text(p, lyt, COL_X, INSET[3] + 0.08, INSET_LABEL, 10, "Bold", name="Inset label")
    text(p, lyt, M, 0.22, SOURCE, 7, color=MUTED, name="Source", width=W - 2 * M)

    if mode == "preview":
        lyt.exportToPNG(str(PREVIEW), resolution=110)
        print(f"preview: {PREVIEW}")
        print("legend items:", [i.name for i in legend.items])
        print("main scale 1:%d, inset scale 1:%d" % (main_mf.camera.scale, inset_mf.camera.scale))
    else:
        FIGURES.mkdir(exist_ok=True)
        lyt.exportToPNG(str(FIGURES / "map_bus_reliability.png"), resolution=300)
        lyt.exportToPDF(str(FIGURES / "map_bus_reliability.pdf"), resolution=300)
        p.save()
        print("saved layout to project and exported PNG and PDF to figures/")


if __name__ == "__main__":
    if len(sys.argv) < 2 or (len(sys.argv) > 2 and sys.argv[2] not in ("preview", "save")):
        sys.exit("usage: make_layout.py PROJECT.aprx [preview|save]")
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "preview")
