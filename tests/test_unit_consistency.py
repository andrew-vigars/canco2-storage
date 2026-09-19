"""Regression tests for spatial-unit consistency across pipeline layers."""

from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import box

from canco2_storage.harmonize import gsc_atlantic, unified_atlas
from canco2_storage.harmonize.common import SILVER_CRS


def assert_two_by_three_kilometre_metrics(frame: gpd.GeoDataFrame) -> None:
    """Assert equivalent metre, kilometre, and hectare measurements."""

    area_m2 = float(frame["geometry_area_m2"].iloc[0])
    area_ha = float(frame["geometry_area_ha"].iloc[0])
    perimeter_m = float(frame["geometry_perimeter_m"].iloc[0])

    assert area_m2 == pytest.approx(6_000_000.0)
    assert area_ha == pytest.approx(600.0)
    assert area_m2 / 1_000_000.0 == pytest.approx(6.0)  # square kilometres
    assert area_m2 / 10_000.0 == pytest.approx(area_ha)
    assert perimeter_m == pytest.approx(10_000.0)
    assert perimeter_m / 1_000.0 == pytest.approx(10.0)  # kilometres


def test_atlantic_units_survive_bronze_to_silver_to_unified(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep projected spatial units consistent through both transformations."""

    # A deterministic Bronze-like feature measuring 2 km by 3 km in the
    # pipeline's metre-based projected CRS.
    bronze = gpd.GeoDataFrame(
        {
            "COS_Reserv": [0.4],
            "COS_Seal": [0.8],
            "COS_Trap": [0.6],
            "TCOS_CCUS": [0.3],
        },
        geometry=[box(0.0, 0.0, 2_000.0, 3_000.0)],
        crs=SILVER_CRS,
    )
    monkeypatch.setattr(
        gsc_atlantic,
        "read_source_layer",
        lambda path: (bronze.copy(), []),
    )

    silver, _ = gsc_atlantic.harmonize_layer(Path("Bjarni.shp"))

    assert silver.crs is not None
    assert silver.crs.to_epsg() == 3978
    assert_two_by_three_kilometre_metrics(silver)

    # Persist and reopen the Silver boundary exactly as the unified workflow
    # does, guarding against unit or type changes during GeoPackage I/O.
    silver_path = tmp_path / "atlantic_silver.gpkg"
    silver.to_file(silver_path, layer="storage_units", driver="GPKG")
    unified = unified_atlas.build_atlantic_storage_features(silver_path)

    assert unified.crs is not None
    assert unified.crs.to_epsg() == 3978
    assert_two_by_three_kilometre_metrics(unified)
    for column in (
        "geometry_area_m2",
        "geometry_area_ha",
        "geometry_perimeter_m",
    ):
        assert float(unified[column].iloc[0]) == pytest.approx(
            float(silver[column].iloc[0])
        )
