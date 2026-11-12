"""Generate lightweight SVG maps for the documentation from the unified atlas.

The script intentionally uses only project runtime dependencies.  It dissolves
and simplifies geometries before writing SVG so the checked-in illustrations
remain small and readable rather than becoming exports of every source vertex.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Iterable

import geopandas as gpd
import pandas as pd
from shapely import union_all
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UNIFIED_DIR = PROJECT_ROOT / "data" / "processed" / "unified_storage"
BC_DIR = PROJECT_ROOT / "data" / "processed" / "gbc_ne_atlas"
NATCARB_DIR = PROJECT_ROOT / "data" / "processed" / "natcarb_doe"
GSC_DIR = PROJECT_ROOT / "data" / "processed" / "gsc_atlantic"
AER_DIR = PROJECT_ROOT / "data" / "processed" / "aer_agreements"
ANALYTICAL_BOUNDARY = (
    PROJECT_ROOT / "data" / "raw" / "basemaps" / "digital" / "lpr_000a21a_e.shp"
)
CARTOGRAPHIC_BOUNDARY = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "basemaps"
    / "cartographic"
    / "lpr_000b21a_e.shp"
)
OUTPUT_DIR = PROJECT_ROOT / "docs" / "images"

INK = "#18312b"
MUTED = "#587069"
LAND = "#eef1ec"
WATER = "#dcecf4"
GRID = "#d9e2de"
BOUNDARY_STROKE = "#9baea7"


@dataclass(frozen=True)
class MapLayer:
    """One styled geometry collection in a documentation map."""

    label: str
    geometries: Iterable
    fill: str
    stroke: str
    opacity: float = 0.76


def newest_package() -> Path:
    """Return the newest dated v2 unified GeoPackage."""

    packages = sorted(
        UNIFIED_DIR.glob("*_13_CanadaGeologicalStorageUnified_AV_v2.gpkg")
    )
    if not packages:
        raise FileNotFoundError(
            f"No unified GeoPackage found under {UNIFIED_DIR}. "
            "Run canco2-build-unified first."
        )
    return packages[-1]


def newest_bc_package() -> Path:
    """Return the newest dated Northeast BC daughter GeoPackage."""

    packages = sorted(BC_DIR.glob("*_13_BCStorageAtlas_AV.gpkg"))
    if not packages:
        raise FileNotFoundError(
            f"No Northeast BC GeoPackage found under {BC_DIR}. "
            "Run the BC Silver workflow first."
        )
    return packages[-1]


def newest_natcarb_package() -> Path:
    """Return the newest dated NATCARB daughter GeoPackage."""

    packages = sorted(NATCARB_DIR.glob("*_13_NATCARBStorage_AV.gpkg"))
    if not packages:
        raise FileNotFoundError(
            f"No NATCARB GeoPackage found under {NATCARB_DIR}. "
            "Run the NATCARB Silver workflow first."
        )
    return packages[-1]


def newest_gsc_package() -> Path:
    """Return the newest dated GSC Atlantic daughter GeoPackage."""

    packages = sorted(GSC_DIR.glob("*_13_AtlanticStorageCOS_AV.gpkg"))
    if not packages:
        raise FileNotFoundError(
            f"No GSC Atlantic GeoPackage found under {GSC_DIR}. "
            "Run the GSC Atlantic Silver workflow first."
        )
    return packages[-1]


def newest_aer_package() -> Path:
    """Return the newest dated AER daughter GeoPackage."""

    packages = sorted(
        AER_DIR.glob("*_13_AERCarbonSequestrationAgreements_AV.gpkg")
    )
    if not packages:
        raise FileNotFoundError(
            f"No AER GeoPackage found under {AER_DIR}. "
            "Run the AER Silver workflow first."
        )
    return packages[-1]


def _polygon_parts(geometry):
    if geometry is None or geometry.is_empty:
        return
    if isinstance(geometry, Polygon):
        yield geometry
    elif isinstance(geometry, MultiPolygon):
        yield from geometry.geoms
    elif isinstance(geometry, GeometryCollection):
        for part in geometry.geoms:
            yield from _polygon_parts(part)


def _path_data(geometry, transform) -> str:
    commands: list[str] = []
    for polygon in _polygon_parts(geometry):
        rings = [polygon.exterior, *polygon.interiors]
        for ring in rings:
            coordinates = list(ring.coords)
            if len(coordinates) < 3:
                continue
            x0, y0 = transform(*coordinates[0])
            commands.append(f"M{x0:.1f},{y0:.1f}")
            commands.extend(
                f"L{x:.1f},{y:.1f}"
                for x, y in (transform(*coordinate) for coordinate in coordinates[1:])
            )
            commands.append("Z")
    return "".join(commands)


def _dissolve(frame: gpd.GeoDataFrame, tolerance: float):
    geometry = frame.geometry.make_valid().union_all(grid_size=1)
    return geometry.simplify(tolerance, preserve_topology=True)


def _basemap_geometries(
    boundary: gpd.GeoDataFrame,
    clip,
    tolerance: float,
):
    """Return cartographic land and undissolved province outlines."""

    clipped = [
        geometry.simplify(tolerance, preserve_topology=False).intersection(clip)
        for geometry in boundary.geometry
        if geometry is not None and not geometry.is_empty
    ]
    clipped = [geometry for geometry in clipped if not geometry.is_empty]
    provinces = GeometryCollection(clipped)
    land = union_all(clipped)
    return land, provinces


def _map_svg(
    title: str,
    subtitle: str,
    boundary: gpd.GeoDataFrame,
    layers: list[MapLayer],
    bounds: tuple[float, float, float, float],
    width: int = 960,
    height: int = 600,
    legend_width: int = 250,
) -> str:
    margin_left, margin_top, margin_right, margin_bottom = (
        42,
        100,
        legend_width,
        42,
    )
    map_width = width - margin_left - margin_right
    map_height = height - margin_top - margin_bottom
    minx, miny, maxx, maxy = bounds
    span_x = max(maxx - minx, 1)
    span_y = max(maxy - miny, 1)
    scale = min(map_width / span_x, map_height / span_y)
    draw_width, draw_height = span_x * scale, span_y * scale
    origin_x = margin_left + (map_width - draw_width) / 2
    origin_y = margin_top + (map_height - draw_height) / 2

    def transform(x: float, y: float) -> tuple[float, float]:
        return origin_x + (x - minx) * scale, origin_y + (maxy - y) * scale

    clip = box(minx, miny, maxx, maxy)
    land, province_outlines = _basemap_geometries(
        boundary,
        clip,
        max(span_x, span_y) / 1200,
    )
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{escape(title)}</title>',
        f'<desc id="desc">{escape(subtitle)}</desc>',
        f'<rect width="{width}" height="{height}" rx="18" fill="{WATER}"/>',
        f'<text x="42" y="44" font-family="Segoe UI,Arial,sans-serif" '
        f'font-size="25" font-weight="700" fill="{INK}">{escape(title)}</text>',
        f'<text x="42" y="70" font-family="Segoe UI,Arial,sans-serif" '
        f'font-size="14" fill="{MUTED}">{escape(subtitle)}</text>',
        f'<rect x="{margin_left}" y="{margin_top}" width="{map_width}" '
        f'height="{map_height}" rx="8" fill="{WATER}" stroke="{GRID}"/>',
        f'<path d="{_path_data(land, transform)}" fill="{LAND}" '
        f'stroke="{BOUNDARY_STROKE}" '
        'stroke-width="0.8" fill-rule="evenodd"/>',
        f'<path d="{_path_data(province_outlines, transform)}" fill="none" '
        f'stroke="{BOUNDARY_STROKE}" stroke-width="0.65"/>',
    ]
    for layer in layers:
        geometry = GeometryCollection(
            [item for item in layer.geometries if item is not None and not item.is_empty]
        )
        svg.append(
            f'<path d="{_path_data(geometry, transform)}" fill="{layer.fill}" '
            f'stroke="{layer.stroke}" stroke-width="0.8" opacity="{layer.opacity}" '
            'fill-rule="evenodd"/>'
        )

    legend_x = width - margin_right + 28
    legend_y = margin_top + 10
    svg.append(
        f'<text x="{legend_x}" y="{legend_y}" font-family="Segoe UI,Arial,sans-serif" '
        f'font-size="13" font-weight="700" fill="{INK}">LAYERS</text>'
    )
    for index, layer in enumerate(layers):
        y = legend_y + 30 + index * 38
        svg.extend(
            [
                f'<rect x="{legend_x}" y="{y - 13}" width="18" height="18" rx="3" '
                f'fill="{layer.fill}" stroke="{layer.stroke}" opacity="{layer.opacity}"/>',
                f'<text x="{legend_x + 29}" y="{y + 1}" '
                f'font-family="Segoe UI,Arial,sans-serif" font-size="13" '
                f'fill="{INK}">{escape(layer.label)}</text>',
            ]
        )
    svg.append(
        f'<text x="{legend_x}" y="{height - 52}" font-family="Segoe UI,Arial,sans-serif" '
        f'font-size="11" fill="{MUTED}">EPSG:3978 · schematic overview</text>'
    )
    svg.append("</svg>")
    return "\n".join(svg)


def _padded_bounds(frame: gpd.GeoDataFrame, fraction: float = 0.08):
    minx, miny, maxx, maxy = frame.total_bounds
    pad_x = max((maxx - minx) * fraction, 10_000)
    pad_y = max((maxy - miny) * fraction, 10_000)
    return minx - pad_x, miny - pad_y, maxx + pad_x, maxy + pad_y


def _atlantic_small_multiples_svg(
    title: str,
    subtitle: str,
    boundary: gpd.GeoDataFrame,
    frames: list[tuple[str, str, gpd.GeoDataFrame]],
    *,
    columns: int = 3,
) -> str:
    """Render Atlantic source units with a shared total-COS color scale."""

    width = 1200
    panel_width = 368
    panel_height = 250
    gap = 18
    left = 30
    top = 145
    rows = math.ceil(len(frames) / columns)
    height = top + rows * panel_height + max(rows - 1, 0) * gap + 35
    bins = [0, 0.05, 0.10, 0.20, 0.40, 1.000001]
    specs = [
        ("0–<0.05", "#eff3ff", "#b6c8e5"),
        ("0.05–<0.10", "#c6dbef", "#8caeca"),
        ("0.10–<0.20", "#9ecae1", "#6496b5"),
        ("0.20–<0.40", "#4292c6", "#276b96"),
        ("0.40–1.00", "#08519c", "#05366a"),
    ]
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}" role="img" '
        'aria-labelledby="title desc">',
        f'<title id="title">{escape(title)}</title>',
        f'<desc id="desc">{escape(subtitle)}</desc>',
        f'<rect width="{width}" height="{height}" rx="18" fill="{WATER}"/>',
        f'<text x="30" y="42" font-family="Segoe UI,Arial,sans-serif" '
        f'font-size="25" font-weight="700" fill="{INK}">{escape(title)}</text>',
        f'<text x="30" y="68" font-family="Segoe UI,Arial,sans-serif" '
        f'font-size="14" fill="{MUTED}">{escape(subtitle)}</text>',
        f'<text x="30" y="102" font-family="Segoe UI,Arial,sans-serif" '
        f'font-size="12" font-weight="700" fill="{INK}">TOTAL COS</text>',
    ]
    legend_x = 118
    for index, (label, fill, stroke) in enumerate(specs):
        x = legend_x + index * 165
        svg.extend(
            [
                f'<rect x="{x}" y="88" width="18" height="18" rx="3" '
                f'fill="{fill}" stroke="{stroke}"/>',
                f'<text x="{x + 27}" y="102" '
                'font-family="Segoe UI,Arial,sans-serif" font-size="12" '
                f'fill="{INK}">{escape(label)}</text>',
            ]
        )

    for index, (unit_name, assessment_area, frame) in enumerate(frames):
        row, column = divmod(index, columns)
        panel_x = left + column * (panel_width + gap)
        panel_y = top + row * (panel_height + gap)
        map_x, map_y = panel_x + 10, panel_y + 54
        map_width, map_height = panel_width - 20, panel_height - 68
        minx, miny, maxx, maxy = _padded_bounds(frame, 0.06)
        span_x = max(maxx - minx, 1)
        span_y = max(maxy - miny, 1)
        scale = min(map_width / span_x, map_height / span_y)
        draw_width, draw_height = span_x * scale, span_y * scale
        origin_x = map_x + (map_width - draw_width) / 2
        origin_y = map_y + (map_height - draw_height) / 2

        def transform(x: float, y: float) -> tuple[float, float]:
            return (
                origin_x + (x - minx) * scale,
                origin_y + (maxy - y) * scale,
            )

        clip = box(minx, miny, maxx, maxy)
        land, province_outlines = _basemap_geometries(
            boundary,
            clip,
            max(span_x, span_y) / 900,
        )
        svg.extend(
            [
                f'<rect x="{panel_x}" y="{panel_y}" width="{panel_width}" '
                f'height="{panel_height}" rx="9" fill="{WATER}" stroke="{GRID}"/>',
                f'<text x="{panel_x + 12}" y="{panel_y + 23}" '
                'font-family="Segoe UI,Arial,sans-serif" font-size="14" '
                f'font-weight="700" fill="{INK}">{escape(unit_name)}</text>',
                f'<text x="{panel_x + 12}" y="{panel_y + 43}" '
                'font-family="Segoe UI,Arial,sans-serif" font-size="11" '
                f'fill="{MUTED}">{escape(assessment_area)} · '
                f'{len(frame):,} features</text>',
                f'<path d="{_path_data(land, transform)}" fill="{LAND}" '
                f'stroke="{BOUNDARY_STROKE}" stroke-width="0.7" '
                'fill-rule="evenodd"/>',
                f'<path d="{_path_data(province_outlines, transform)}" fill="none" '
                f'stroke="{BOUNDARY_STROKE}" stroke-width="0.55"/>',
            ]
        )
        categories = pd.cut(
            frame["total_cos"],
            bins=bins,
            labels=False,
            include_lowest=True,
            right=False,
        )
        tolerance = max(span_x, span_y) / 1200
        for category, (_, fill, stroke) in enumerate(specs):
            subset = frame.loc[categories.eq(category)]
            if subset.empty:
                continue
            geometry = _dissolve(subset, tolerance)
            svg.append(
                f'<path d="{_path_data(geometry, transform)}" fill="{fill}" '
                f'stroke="{stroke}" stroke-width="0.65" opacity="0.88" '
                'fill-rule="evenodd"/>'
            )

    svg.append("</svg>")
    return "\n".join(svg)


def generate(package: Path, output_dir: Path) -> None:
    """Create the checked-in source and layer maps."""

    output_dir.mkdir(parents=True, exist_ok=True)
    features = gpd.read_file(package, layer="storage_features").to_crs(3978)
    units = gpd.read_file(package, layer="storage_units", ignore_geometry=True)
    admin = gpd.read_file(package, layer="administrative_features").to_crs(3978)
    boundary = gpd.read_file(CARTOGRAPHIC_BOUNDARY).to_crs(3978)
    canada_context = gpd.GeoDataFrame(
        pd.concat(
            [
                boundary[["geometry"]],
                features[["geometry"]],
                admin[["geometry"]],
            ],
            ignore_index=True,
        ),
        geometry="geometry",
        crs=features.crs,
    )
    canada_bounds = _padded_bounds(canada_context, 0.015)

    sources = [
        ("NATCARB", "NATCARB", "#df8f2d", "#9f5e12"),
        ("BC atlas", "BC_STORAGE_ATLAS", "#2d9d78", "#17664e"),
        ("Atlantic COS", "ATLANTIC_COS", "#427bbd", "#24558e"),
    ]
    overview_layers = [
        MapLayer(
            label,
            [_dissolve(features.loc[features.source_dataset.eq(key)], 7_500)],
            fill,
            stroke,
        )
        for label, key, fill, stroke in sources
    ]
    overview_layers.append(
        MapLayer(
            "AER agreements",
            [_dissolve(admin.loc[admin.source_layer.eq("aer_agreements")], 2_500)],
            "#ad5f9d",
            "#743969",
        )
    )
    (output_dir / "unified-atlas-overview.svg").write_text(
        _map_svg(
            "Unified atlas: source coverage",
            "Four source datasets remain distinguishable in the canonical GeoPackage.",
            boundary,
            overview_layers,
            canada_bounds,
        ),
        encoding="utf-8",
    )

    natcarb = features.loc[features.source_dataset.eq("NATCARB")]
    natcarb_specs = [
        ("Saline grid cells", "saline_resource_cells", "#3182bd", "#175a87"),
        ("Coal grid cells", "coal_resource_cells", "#7b6a58", "#514537"),
        ("Oil and gas polygons", "oil_gas_resources", "#e08c3b", "#a05b18"),
    ]
    natcarb_layers = [
        MapLayer(
            label,
            [_dissolve(natcarb.loc[natcarb.source_layer.eq(key)], 6_000)],
            fill,
            stroke,
        )
        for label, key, fill, stroke in natcarb_specs
    ]
    (output_dir / "natcarb-layers.svg").write_text(
        _map_svg(
            "NATCARB decomposition",
            "Canadian subset of the three representations carried into the unified atlas.",
            boundary,
            natcarb_layers,
            canada_bounds,
        ),
        encoding="utf-8",
    )

    bc = features.loc[features.source_dataset.eq("BC_STORAGE_ATLAS")]
    bc_layers = [
        MapLayer(
            "Pool extents",
            [_dissolve(bc.loc[bc.source_layer.eq("pool_features")], 600)],
            "#50a57e",
            "#1f6f50",
        ),
        MapLayer(
            "Aquifer extents",
            [_dissolve(bc.loc[bc.source_layer.eq("aquifer_features")], 600)],
            "#3b80bd",
            "#205b8a",
            0.62,
        ),
    ]
    (output_dir / "bc-atlas-layers.svg").write_text(
        _map_svg(
            "Northeast BC atlas decomposition",
            "Published pool and aquifer spatial representations; capacity lives at unit grain.",
            boundary,
            bc_layers,
            _padded_bounds(bc),
        ),
        encoding="utf-8",
    )

    atlantic = features.loc[features.source_dataset.eq("ATLANTIC_COS")].merge(
        units[["storage_unit_id", "geological_group"]],
        on="storage_unit_id",
        how="left",
        validate="many_to_one",
    )
    atlantic = gpd.GeoDataFrame(atlantic, geometry="geometry", crs=features.crs)
    atlantic_layers = [
        MapLayer(
            "Mesozoic–Cenozoic",
            [_dissolve(atlantic.loc[atlantic.geological_group.eq("Mesozoic-Cenozoic")], 2_000)],
            "#447db9",
            "#275784",
        ),
        MapLayer(
            "Upper Paleozoic",
            [_dissolve(atlantic.loc[atlantic.geological_group.eq("Upper Paleozoic")], 2_000)],
            "#72a85b",
            "#456f34",
        ),
    ]
    (output_dir / "atlantic-cos-layers.svg").write_text(
        _map_svg(
            "Atlantic COS decomposition",
            "Fifteen storage units grouped into the two source geological packages.",
            boundary,
            atlantic_layers,
            _padded_bounds(atlantic),
        ),
        encoding="utf-8",
    )

    agreements = admin.loc[admin.source_layer.eq("aer_agreements")]
    tracts = admin.loc[admin.source_layer.eq("aer_agreement_tracts")]
    aer_layers = [
        MapLayer(
            "Tenure agreements",
            [_dissolve(agreements, 500)],
            "#ad5f9d",
            "#6e3563",
        ),
    ]
    (output_dir / "aer-agreement-layers.svg").write_text(
        _map_svg(
            "AER carbon-sequestration tenure",
            (
                f"{len(agreements):,} dissolved agreements; "
                f"{len(tracts):,} source tracts are retained in the dataset."
            ),
            boundary,
            aer_layers,
            _padded_bounds(admin),
        ),
        encoding="utf-8",
    )


def generate_bc_details(package: Path, output_dir: Path) -> None:
    """Create detailed Northeast BC daughter-package documentation maps."""

    output_dir.mkdir(parents=True, exist_ok=True)
    boundary = gpd.read_file(CARTOGRAPHIC_BOUNDARY).to_crs(3978)

    pool_features = gpd.read_file(package, layer="pool_features").to_crs(3978)
    pool_units = gpd.read_file(package, layer="pool_units", ignore_geometry=True)
    pools = pool_features.merge(
        pool_units[
            [
                "storage_unit_id",
                "pool_class",
                "map_group",
                "effective_storage_mt",
            ]
        ],
        on="storage_unit_id",
        how="left",
        validate="many_to_one",
    )
    pools = gpd.GeoDataFrame(pools, geometry="geometry", crs=pool_features.crs)

    aquifer_features = gpd.read_file(package, layer="aquifer_features").to_crs(3978)
    aquifer_units = gpd.read_file(
        package,
        layer="aquifer_units",
        ignore_geometry=True,
    )
    aquifers = aquifer_features.merge(
        aquifer_units[
            [
                "storage_unit_id",
                "formation",
                "p50_effective_storage_mt",
            ]
        ],
        on="storage_unit_id",
        how="left",
        validate="many_to_one",
    )
    aquifers = gpd.GeoDataFrame(
        aquifers,
        geometry="geometry",
        crs=aquifer_features.crs,
    )

    pool_bounds = _padded_bounds(pools)
    aquifer_bounds = _padded_bounds(aquifers)

    class_specs = [
        ("current_candidate", "Current candidates", "#278f75", "#17604f"),
        ("future_candidate", "Future candidates", "#e4a83b", "#9b6914"),
        ("co2_eor_candidate", "CO2-EOR candidates", "#8b64a8", "#5e3e78"),
    ]
    class_counts = pool_units["pool_class"].value_counts().to_dict()
    class_layers = [
        MapLayer(
            f"{label} ({class_counts.get(key, 0):,})",
            [_dissolve(pools.loc[pools.pool_class.eq(key)], 400)],
            fill,
            stroke,
        )
        for key, label, fill, stroke in class_specs
    ]
    (output_dir / "bc-pool-screening-classes.svg").write_text(
        _map_svg(
            "Northeast BC pools by screening class",
            "Appendix C classifies 1,238 logical pools; values remain unit-scoped.",
            boundary,
            class_layers,
            pool_bounds,
            width=1020,
            legend_width=300,
        ),
        encoding="utf-8",
    )

    categorical_palette = [
        ("#3f7cac", "#285678"),
        ("#65a96e", "#407548"),
        ("#d9903d", "#965c1c"),
        ("#9b6fb0", "#68487a"),
        ("#d35f5f", "#923c3c"),
        ("#46a5a5", "#2b7070"),
        ("#c4a33f", "#846b20"),
        ("#747fb4", "#4d567c"),
        ("#8b9d58", "#5c6c36"),
        ("#c4779b", "#884e69"),
        ("#5e9ac6", "#3b6888"),
        ("#a07a57", "#6d5037"),
        ("#6ea38d", "#486f60"),
        ("#b784bc", "#7a5680"),
        ("#d07852", "#904d30"),
        ("#7998a1", "#50676e"),
        ("#a4a653", "#70722f"),
    ]
    group_counts = pool_units["map_group"].value_counts().to_dict()
    group_names = sorted(group_counts)
    group_layers = [
        MapLayer(
            f"{group} ({group_counts[group]:,})",
            [_dissolve(pools.loc[pools.map_group.eq(group)], 400)],
            *categorical_palette[index],
        )
        for index, group in enumerate(group_names)
    ]
    (output_dir / "bc-pool-map-groups.svg").write_text(
        _map_svg(
            "Northeast BC pools by map group",
            "Seventeen source-reported Appendix C map groups; colours are categorical.",
            boundary,
            group_layers,
            pool_bounds,
            width=1200,
            height=880,
            legend_width=380,
        ),
        encoding="utf-8",
    )

    formation_counts = aquifer_units["formation"].value_counts().to_dict()
    formation_names = sorted(formation_counts)
    formation_layers = [
        MapLayer(
            f"{formation} ({formation_counts[formation]:,})",
            [_dissolve(aquifers.loc[aquifers.formation.eq(formation)], 350)],
            *categorical_palette[index],
        )
        for index, formation in enumerate(formation_names)
    ]
    (output_dir / "bc-aquifer-formations.svg").write_text(
        _map_svg(
            "Northeast BC aquifers by formation",
            "Twenty-five logical aquifers represented by 29 source geometries.",
            boundary,
            formation_layers,
            aquifer_bounds,
            width=1120,
            height=650,
            legend_width=370,
        ),
        encoding="utf-8",
    )

    named_palette = categorical_palette + [
        ("#e19c67", "#9b663d"),
        ("#5c8f78", "#3b6251"),
        ("#aa70a5", "#744a70"),
        ("#7694c7", "#4d668d"),
        ("#c59447", "#876426"),
        ("#68a6b4", "#42737e"),
        ("#b87979", "#7e4e4e"),
        ("#899f61", "#5c6d3e"),
    ]
    named_units = (
        aquifer_units[["formation", "aquifer_name"]]
        .sort_values(["formation", "aquifer_name"])
        .reset_index(drop=True)
    )
    named_layers = [
        MapLayer(
            f"{row.formation} — {row.aquifer_name}",
            [_dissolve(aquifers.loc[aquifers.aquifer_name.eq(row.aquifer_name)], 350)],
            *named_palette[index],
        )
        for index, row in named_units.iterrows()
    ]
    (output_dir / "bc-named-aquifers.svg").write_text(
        _map_svg(
            "Northeast BC named aquifers",
            "Twenty-five Appendix C aquifers; colours distinguish logical units.",
            boundary,
            named_layers,
            aquifer_bounds,
            width=1400,
            height=1180,
            legend_width=600,
        ),
        encoding="utf-8",
    )

    pools["capacity_bin"] = pd.cut(
        pools["effective_storage_mt"],
        bins=[0, 0.05, 0.2, 1, 5, float("inf")],
        labels=["0–<0.05", "0.05–<0.2", "0.2–<1", "1–<5", "5 or more"],
        include_lowest=True,
        right=False,
    )
    pool_units = pool_units.copy()
    pool_units["capacity_bin"] = pd.cut(
        pool_units["effective_storage_mt"],
        bins=[0, 0.05, 0.2, 1, 5, float("inf")],
        labels=["0–<0.05", "0.05–<0.2", "0.2–<1", "1–<5", "5 or more"],
        include_lowest=True,
        right=False,
    )
    pool_capacity_specs = [
        ("0–<0.05", "#edf8e9", "#a7c99f"),
        ("0.05–<0.2", "#bae4b3", "#75aa70"),
        ("0.2–<1", "#74c476", "#438b49"),
        ("1–<5", "#31a354", "#1e7138"),
        ("5 or more", "#006d2c", "#00451d"),
    ]
    pool_capacity_counts = pool_units["capacity_bin"].value_counts().to_dict()
    pool_capacity_layers = [
        MapLayer(
            f"{label} Mt ({pool_capacity_counts.get(label, 0):,} units)",
            [_dissolve(pools.loc[pools.capacity_bin.eq(label)], 400)],
            fill,
            stroke,
        )
        for label, fill, stroke in pool_capacity_specs
    ]
    (output_dir / "bc-pool-effective-storage.svg").write_text(
        _map_svg(
            "Northeast BC pool effective storage potential",
            "Appendix C unit values mapped across associated features; do not sum polygons.",
            boundary,
            pool_capacity_layers,
            pool_bounds,
            width=1080,
            legend_width=360,
        ),
        encoding="utf-8",
    )

    aquifers["capacity_bin"] = pd.cut(
        aquifers["p50_effective_storage_mt"],
        bins=[0, 25, 50, 100, 250, float("inf")],
        labels=["0–<25", "25–<50", "50–<100", "100–<250", "250 or more"],
        include_lowest=True,
        right=False,
    )
    aquifer_units = aquifer_units.copy()
    aquifer_units["capacity_bin"] = pd.cut(
        aquifer_units["p50_effective_storage_mt"],
        bins=[0, 25, 50, 100, 250, float("inf")],
        labels=["0–<25", "25–<50", "50–<100", "100–<250", "250 or more"],
        include_lowest=True,
        right=False,
    )
    aquifer_capacity_specs = [
        ("0–<25", "#eff3ff", "#a9bfe5"),
        ("25–<50", "#bdd7e7", "#7ea8c6"),
        ("50–<100", "#6baed6", "#3e7fa5"),
        ("100–<250", "#3182bd", "#1d5c8a"),
        ("250 or more", "#08519c", "#05366a"),
    ]
    aquifer_capacity_counts = (
        aquifer_units["capacity_bin"].value_counts().to_dict()
    )
    aquifer_capacity_layers = [
        MapLayer(
            f"{label} Mt ({aquifer_capacity_counts.get(label, 0):,} units)",
            [_dissolve(aquifers.loc[aquifers.capacity_bin.eq(label)], 350)],
            fill,
            stroke,
        )
        for label, fill, stroke in aquifer_capacity_specs
    ]
    (output_dir / "bc-aquifer-p50-storage.svg").write_text(
        _map_svg(
            "Northeast BC aquifer P50 effective storage",
            "Appendix C P50 values at 2% efficiency; values remain unit-scoped.",
            boundary,
            aquifer_capacity_layers,
            aquifer_bounds,
            width=1080,
            legend_width=360,
        ),
        encoding="utf-8",
    )


def generate_gsc_details(package: Path, output_dir: Path) -> None:
    """Create detailed GSC Atlantic source-unit and total-COS maps."""

    output_dir.mkdir(parents=True, exist_ok=True)
    boundary = gpd.read_file(CARTOGRAPHIC_BOUNDARY).to_crs(3978)
    atlantic = gpd.read_file(package, layer="storage_units").to_crs(3978)

    def unit_frames(group: str) -> list[tuple[str, str, gpd.GeoDataFrame]]:
        group_frame = atlantic.loc[atlantic.geological_group.eq(group)]
        records = (
            group_frame[
                ["storage_unit_id", "storage_unit_name", "assessment_area"]
            ]
            .drop_duplicates()
            .sort_values(["assessment_area", "storage_unit_name"])
        )
        return [
            (
                row.storage_unit_name,
                row.assessment_area,
                group_frame.loc[
                    group_frame.storage_unit_id.eq(row.storage_unit_id)
                ].copy(),
            )
            for row in records.itertuples(index=False)
        ]

    mesozoic = unit_frames("Mesozoic-Cenozoic")
    paleozoic = unit_frames("Upper Paleozoic")
    (output_dir / "atlantic-mesozoic-cos.svg").write_text(
        _atlantic_small_multiples_svg(
            "Atlantic Mesozoic–Cenozoic storage units",
            "Ten source layers; total COS uses one scale, while panel extents vary.",
            boundary,
            mesozoic,
        ),
        encoding="utf-8",
    )
    (output_dir / "atlantic-paleozoic-cos.svg").write_text(
        _atlantic_small_multiples_svg(
            "Atlantic Upper Paleozoic storage units",
            "Five source layers; total COS uses one scale, while panel extents vary.",
            boundary,
            paleozoic,
        ),
        encoding="utf-8",
    )


def generate_aer_details(package: Path, output_dir: Path) -> None:
    """Create detailed AER agreement-group and tract-hierarchy maps."""

    output_dir.mkdir(parents=True, exist_ok=True)
    boundary = gpd.read_file(CARTOGRAPHIC_BOUNDARY).to_crs(3978)
    agreements = gpd.read_file(package, layer="aer_agreements").to_crs(3978)
    tracts = gpd.read_file(package, layer="aer_agreement_tracts").to_crs(3978)
    bounds = _padded_bounds(agreements)

    group_specs = [
        ("APP", "Applications", "#d9a441", "#906817"),
        ("PERMIT", "Permits", "#4a89bd", "#2b6089"),
        ("LEASE", "Leases", "#4f9c72", "#2f6b4c"),
    ]
    group_counts = agreements["agreement_group"].value_counts().to_dict()
    group_layers = [
        MapLayer(
            f"{label} ({group_counts.get(key, 0):,})",
            [_dissolve(agreements.loc[agreements.agreement_group.eq(key)], 500)],
            fill,
            stroke,
        )
        for key, label, fill, stroke in group_specs
    ]
    (output_dir / "aer-agreement-groups.svg").write_text(
        _map_svg(
            "AER carbon-sequestration agreement groups",
            "One dissolved feature per agreement; all current records are active pore-space tenure.",
            boundary,
            group_layers,
            bounds,
            width=1050,
            legend_width=330,
        ),
        encoding="utf-8",
    )

    multi = sorted(
        agreements.loc[agreements.tract_count.gt(1), "agreement_id"].tolist()
    )
    if len(multi) != 2:
        raise ValueError(
            "Expected two multi-tract AER agreements in the reference build, "
            f"found {len(multi)}."
        )
    single = agreements.loc[agreements.tract_count.eq(1)]
    hierarchy_specs = [
        (
            f"Single-tract agreements ({len(single):,})",
            single,
            "#d8dedb",
            "#87938e",
            0.68,
        ),
        (
            f"Agreement {multi[0]} (2 tracts)",
            tracts.loc[tracts.agreement_id.eq(multi[0])],
            "#dda64b",
            "#946b1c",
            0.86,
        ),
        (
            f"Agreement {multi[1]} (2 tracts)",
            tracts.loc[tracts.agreement_id.eq(multi[1])],
            "#936cb1",
            "#62467b",
            0.86,
        ),
    ]
    hierarchy_layers = [
        MapLayer(label, [_dissolve(frame, 350)], fill, stroke, opacity)
        for label, frame, fill, stroke, opacity in hierarchy_specs
    ]
    (output_dir / "aer-tract-hierarchy.svg").write_text(
        _map_svg(
            "AER agreement and source-tract hierarchy",
            "Most agreements contain one tract; the four colored source tracts form two agreements.",
            boundary,
            hierarchy_layers,
            bounds,
            width=1080,
            legend_width=390,
        ),
        encoding="utf-8",
    )


def generate_natcarb_details(
    package: Path,
    unified_package: Path,
    output_dir: Path,
) -> None:
    """Create detailed NATCARB daughter and Canadian-subset maps."""

    output_dir.mkdir(parents=True, exist_ok=True)
    boundary = gpd.read_file(CARTOGRAPHIC_BOUNDARY).to_crs(3978)
    analytical_boundary = gpd.read_file(ANALYTICAL_BOUNDARY).to_crs(3978)
    canada_mask = analytical_boundary[["geometry"]].dissolve()

    saline_cells = gpd.read_file(
        package,
        layer="saline_resource_cells",
        mask=canada_mask,
    ).to_crs(3978)
    saline_areas = gpd.read_file(
        package,
        layer="saline_resource_areas",
        mask=canada_mask,
    ).to_crs(3978)
    coal_cells = gpd.read_file(
        package,
        layer="coal_resource_cells",
        mask=canada_mask,
    ).to_crs(3978)
    coal_areas = gpd.read_file(
        package,
        layer="coal_resource_areas",
        mask=canada_mask,
    ).to_crs(3978)

    saline_context = gpd.GeoDataFrame(
        pd.concat(
            [saline_cells[["geometry"]], saline_areas[["geometry"]]],
            ignore_index=True,
        ),
        geometry="geometry",
        crs=saline_cells.crs,
    )
    saline_representation_layers = [
        MapLayer(
            f"Resource areas ({len(saline_areas):,})",
            [_dissolve(saline_areas, 8_000)],
            "#e59a45",
            "#9b601e",
            0.48,
        ),
        MapLayer(
            f"10 km resource cells ({len(saline_cells):,})",
            [_dissolve(saline_cells, 5_000)],
            "#3c8dc1",
            "#245f88",
            0.72,
        ),
    ]
    (output_dir / "natcarb-saline-representations.svg").write_text(
        _map_svg(
            "NATCARB saline source representations",
            "Canadian-intersecting daughter features; areas and cells are independent products.",
            boundary,
            saline_representation_layers,
            _padded_bounds(saline_context),
            width=1080,
            legend_width=360,
        ),
        encoding="utf-8",
    )

    coal_context = gpd.GeoDataFrame(
        pd.concat(
            [coal_cells[["geometry"]], coal_areas[["geometry"]]],
            ignore_index=True,
        ),
        geometry="geometry",
        crs=coal_cells.crs,
    )
    coal_representation_layers = [
        MapLayer(
            f"Resource areas ({len(coal_areas):,})",
            [_dissolve(coal_areas, 8_000)],
            "#c18b57",
            "#80562f",
            0.48,
        ),
        MapLayer(
            f"10 km resource cells ({len(coal_cells):,})",
            [_dissolve(coal_cells, 5_000)],
            "#70665b",
            "#493f36",
            0.74,
        ),
    ]
    (output_dir / "natcarb-coal-representations.svg").write_text(
        _map_svg(
            "NATCARB coal source representations",
            "Canadian-intersecting daughter features; only grid cells enter the unified atlas.",
            boundary,
            coal_representation_layers,
            _padded_bounds(coal_context),
            width=1080,
            legend_width=360,
        ),
        encoding="utf-8",
    )

    features = gpd.read_file(unified_package, layer="storage_features").to_crs(3978)
    features = features.loc[features.source_dataset.eq("NATCARB")].copy()
    assessments = gpd.read_file(
        unified_package,
        layer="storage_assessments",
        ignore_geometry=True,
    )
    assessments = assessments.loc[
        assessments.source_dataset.eq("NATCARB"),
        ["storage_feature_id", "storage_p50_tonnes"],
    ]
    features = features.merge(
        assessments,
        on="storage_feature_id",
        how="left",
        validate="one_to_one",
    )
    features = gpd.GeoDataFrame(features, geometry="geometry", crs=3978)

    unit_subtypes = gpd.read_file(
        unified_package,
        layer="storage_units",
        ignore_geometry=True,
    )
    unit_subtypes = unit_subtypes.loc[
        unit_subtypes.source_dataset.eq("NATCARB"),
        ["storage_unit_id", "storage_subtype"],
    ].rename(columns={"storage_subtype": "unit_storage_subtype"})

    sequential_specs = [
        ("No P50 reported", "#d8dedb", "#929d98"),
        ("bin_1", "#eff3ff", "#a9bfe5"),
        ("bin_2", "#bdd7e7", "#7ea8c6"),
        ("bin_3", "#6baed6", "#3e7fa5"),
        ("bin_4", "#3182bd", "#1d5c8a"),
        ("bin_5", "#08519c", "#05366a"),
    ]

    def write_capacity_map(
        *,
        source_layer: str,
        title: str,
        subtitle: str,
        filename: str,
        divisor: float,
        bins: list[float],
        labels: list[str],
        tolerance: float,
    ) -> None:
        frame = features.loc[features.source_layer.eq(source_layer)].copy()
        frame["display_value"] = frame["storage_p50_tonnes"] / divisor
        frame["capacity_bin"] = pd.cut(
            frame["display_value"],
            bins=bins,
            labels=[f"bin_{index}" for index in range(1, 6)],
            include_lowest=True,
            right=False,
        ).astype("string")
        frame.loc[frame.storage_p50_tonnes.isna(), "capacity_bin"] = (
            "No P50 reported"
        )
        counts = frame["capacity_bin"].value_counts().to_dict()
        legend_labels = {
            "No P50 reported": "No P50 reported",
            **{
                f"bin_{index}": label
                for index, label in enumerate(labels, start=1)
            },
        }
        layers = [
            MapLayer(
                f"{legend_labels[key]} ({counts.get(key, 0):,})",
                [_dissolve(frame.loc[frame.capacity_bin.eq(key)], tolerance)],
                fill,
                stroke,
            )
            for key, fill, stroke in sequential_specs
            if counts.get(key, 0)
        ]
        (output_dir / filename).write_text(
            _map_svg(
                title,
                subtitle,
                boundary,
                layers,
                _padded_bounds(frame),
                width=1100,
                legend_width=380,
            ),
            encoding="utf-8",
        )

    write_capacity_map(
        source_layer="saline_resource_cells",
        title="Canadian NATCARB saline P50 storage resource",
        subtitle="Feature-scoped estimates in Mt CO2; grey cells have no reported P50.",
        filename="natcarb-saline-p50-storage.svg",
        divisor=1_000_000,
        bins=[0, 1, 5, 25, 100, float("inf")],
        labels=["0–<1 Mt", "1–<5 Mt", "5–<25 Mt", "25–<100 Mt", "100 Mt or more"],
        tolerance=5_000,
    )
    write_capacity_map(
        source_layer="coal_resource_cells",
        title="Canadian NATCARB coal P50 storage resource",
        subtitle="Feature-scoped estimates in kt CO2; grey cells have no reported P50.",
        filename="natcarb-coal-p50-storage.svg",
        divisor=1_000,
        bins=[0, 75, 125, 200, 300, float("inf")],
        labels=["0–<75 kt", "75–<125 kt", "125–<200 kt", "200–<300 kt", "300 kt or more"],
        tolerance=5_000,
    )
    write_capacity_map(
        source_layer="oil_gas_resources",
        title="Canadian NATCARB oil/gas P50 storage resource",
        subtitle="Feature-scoped estimates in Mt CO2; grey polygons have no reported P50.",
        filename="natcarb-oil-gas-p50-storage.svg",
        divisor=1_000_000,
        bins=[0, 0.25, 1, 5, 25, float("inf")],
        labels=["0–<0.25 Mt", "0.25–<1 Mt", "1–<5 Mt", "5–<25 Mt", "25 Mt or more"],
        tolerance=2_500,
    )

    oil_gas = features.loc[
        features.source_layer.eq("oil_gas_resources")
    ].merge(
        unit_subtypes,
        on="storage_unit_id",
        how="left",
        validate="many_to_one",
    )
    oil_gas = gpd.GeoDataFrame(oil_gas, geometry="geometry", crs=features.crs)
    subtype_specs = [
        ("gas_reservoir", "Gas reservoirs", "#4b88b6", "#2d6289"),
        ("oil_reservoir", "Oil reservoirs", "#4a9b72", "#2d6c4d"),
        (
            "oil_and_gas_reservoir",
            "Oil and gas reservoirs",
            "#d58a45",
            "#945820",
        ),
    ]
    subtype_counts = oil_gas["unit_storage_subtype"].value_counts().to_dict()
    subtype_layers = [
        MapLayer(
            f"{label} ({subtype_counts.get(key, 0):,})",
            [
                _dissolve(
                    oil_gas.loc[oil_gas.unit_storage_subtype.eq(key)],
                    2_500,
                )
            ],
            fill,
            stroke,
        )
        for key, label, fill, stroke in subtype_specs
    ]
    (output_dir / "natcarb-oil-gas-subtypes.svg").write_text(
        _map_svg(
            "Canadian NATCARB oil/gas reservoir subtype",
            "Source field type standardized for the 1,358 Canadian resource polygons.",
            boundary,
            subtype_layers,
            _padded_bounds(oil_gas),
            width=1080,
            legend_width=360,
        ),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=None)
    parser.add_argument("--bc-package", type=Path, default=None)
    parser.add_argument("--natcarb-package", type=Path, default=None)
    parser.add_argument("--gsc-package", type=Path, default=None)
    parser.add_argument("--aer-package", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument(
        "--only",
        choices=(
            "all",
            "aer-details",
            "bc-details",
            "gsc-details",
            "natcarb-details",
        ),
        default="all",
        help="Generate overview maps or one dataset's detailed maps.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.only == "aer-details":
        generate_aer_details(
            args.aer_package or newest_aer_package(),
            args.output_dir,
        )
    elif args.only == "bc-details":
        generate_bc_details(
            args.bc_package or newest_bc_package(),
            args.output_dir,
        )
    elif args.only == "natcarb-details":
        generate_natcarb_details(
            args.natcarb_package or newest_natcarb_package(),
            args.package or newest_package(),
            args.output_dir,
        )
    elif args.only == "gsc-details":
        generate_gsc_details(
            args.gsc_package or newest_gsc_package(),
            args.output_dir,
        )
    else:
        generate(args.package or newest_package(), args.output_dir)
    print(f"Documentation maps written to {args.output_dir}")


if __name__ == "__main__":
    main()
