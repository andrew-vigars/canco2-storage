"""Regression coverage for validation of written Atlantic storage layers."""

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

from canco2_storage.harmonize import gsc_atlantic


@pytest.mark.parametrize("invalid", [False, True])
def test_written_layer_validation(tmp_path, monkeypatch, invalid):
    """Read back a real GeoPackage, repairing invalid geometry when needed."""
    path = tmp_path / "atlantic.gpkg"
    monkeypatch.setattr(gsc_atlantic, "SILVER_GPKG_PATH", path)
    coordinates = (
        [(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)]
        if invalid
        else [(0, 0), (2, 0), (2, 2), (0, 0)]
    )
    expected = gpd.GeoDataFrame(
        {"feature_id": ["test_001"], "source_file": ["Bjarni.shp"]},
        geometry=[Polygon(coordinates)],
        crs=gsc_atlantic.TARGET_CRS,
    )
    expected.to_file(path, layer="storage_units", driver="GPKG")

    written, qa = gsc_atlantic.validate_written_storage_layer(expected)

    assert written.feature_id.tolist() == expected.feature_id.tolist()
    assert written.crs.to_epsg() == 3978
    assert written.geometry.is_valid.all()
    assert qa.post_export_invalid_before_repair.tolist() == [int(invalid)]
    assert qa.post_export_invalid_after_repair.tolist() == [0]


def test_written_layer_rejects_wrong_crs(tmp_path, monkeypatch):
    """Reject a serialized layer that is not in the target CRS."""
    path = tmp_path / "atlantic.gpkg"
    monkeypatch.setattr(gsc_atlantic, "SILVER_GPKG_PATH", path)
    expected = gpd.GeoDataFrame(
        {"feature_id": ["test_001"], "source_file": ["Bjarni.shp"]},
        geometry=[Polygon([(0, 0), (1, 0), (1, 1), (0, 0)])],
        crs="EPSG:4326",
    )
    expected.to_file(path, layer="storage_units", driver="GPKG")

    with pytest.raises(ValueError, match="Expected Silver CRS"):
        gsc_atlantic.validate_written_storage_layer(expected)
