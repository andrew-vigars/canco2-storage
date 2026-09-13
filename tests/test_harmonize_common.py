"""Tests for shared Silver geometry processing helpers."""

import geopandas as gpd
from shapely.geometry import Polygon

from canco2_storage.harmonize.common import (
    SILVER_CRS,
    project_and_measure,
    repair_geometries,
    validate_target_crs,
)


def test_repair_geometries_repairs_invalid_non_null_features() -> None:
    """Repair invalid geometries while preserving null geometries."""

    geometry = gpd.GeoSeries(
        [
            Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)]),
        ],
        crs=SILVER_CRS,
    ).reindex([0, 1])
    source = gpd.GeoDataFrame(
        {"name": ["bowtie", "missing"]},
        geometry=geometry,
    )

    repaired, invalid_before, invalid_after = repair_geometries(source)

    assert invalid_before == 1
    assert invalid_after == 0
    assert repaired.geometry.is_valid.iloc[0]
    assert repaired.geometry.isna().iloc[1]
    assert not source.geometry.is_valid.iloc[0]


def test_project_and_measure_returns_valid_silver_metrics() -> None:
    """Reproject features and calculate positive Silver geometry measures."""

    source = gpd.GeoDataFrame(
        geometry=[Polygon([(0, 0), (1, 0), (1, 1), (0, 0)])],
        crs="EPSG:4326",
    )

    projected, invalid_before, invalid_after = project_and_measure(source)

    validate_target_crs(projected)
    assert invalid_before == 0
    assert invalid_after == 0
    assert projected.geometry_area_m2.iloc[0] > 0
    assert projected.geometry_area_ha.iloc[0] > 0
    assert projected.geometry_perimeter_m.iloc[0] > 0
