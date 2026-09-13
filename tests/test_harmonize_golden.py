"""Golden-output tests for dataset-specific Silver harmonization semantics."""

from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

from canco2_storage.harmonize import aer_agreements, gsc_atlantic


@pytest.fixture(name="aer_source")
def make_aer_source() -> gpd.GeoDataFrame:
    """Minimal AER source with one multi-tract agreement."""

    return gpd.GeoDataFrame(
        {
            "AgreementN": ["AG-001", "AG-001"],
            "AgreementT": ["058", "058"],
            "Tract": ["0007", "0008"],
            "MINTYPE": ["PORE SPACE", "PORE SPACE"],
            "AGGROUP": ["LEASE", "LEASE"],
            "Status": ["ACTIVE", "ACTIVE"],
            "Vintage": ["2024", "2024"],
            "DesRep": ["Operator A", "Operator A"],
            "ZoneDesc": ["Basal zone", "Upper zone"],
            "ORGAREA": [10.0, 10.0],
            "AGREEAREA": [12.0, 12.0],
            "TERMDATE": ["2030-01-01", "2030-01-01"],
            "CONTDATE": [None, None],
            "CUREXPIRY": ["2031-01-01", "2031-01-01"],
            "Shape_STAr": [1.0, 1.0],
            "Shape_STLe": [4.0, 4.0],
        },
        geometry=[
            Polygon([(0, 0), (1, 0), (1, 1), (0, 0)]),
            Polygon([(2, 0), (3, 0), (3, 1), (2, 0)]),
        ],
        crs="EPSG:3400",
    )


@pytest.fixture(name="gsc_source")
def make_gsc_source() -> gpd.GeoDataFrame:
    """Minimal GSC source layer with an explicitly mapped trap COS."""

    return gpd.GeoDataFrame(
        {
            "COS_Reserv": [0.4],
            "COS_Seal": [0.8],
            "COS_Trap": [0.6],
            "TCOS_CCUS": [0.3],
        },
        geometry=[Polygon([(-60, 50), (-59, 50), (-59, 51), (-60, 50)])],
        crs="EPSG:4326",
    )


def test_aer_golden_output_preserves_tenure_grain_and_zone_semantics(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """AER output keeps tract IDs and preserves distinct zones on dissolve."""

    aer_fixture = request.getfixturevalue("aer_source")

    monkeypatch.setattr(
        aer_agreements,
        "read_source_layer",
        lambda path: (aer_fixture.copy(), []),
    )

    tracts, _, qa = aer_agreements.build_tract_layer(
        Path("CS_Agreements.shp")
    )
    agreements = aer_agreements.build_agreement_layer(tracts)

    assert tracts[
        [
            "agreement_id",
            "tract_id",
            "source_feature_uid",
            "assessment_type",
            "data_class",
            "capacity_data",
        ]
    ].to_dict("records") == [
        {
            "agreement_id": "AG-001",
            "tract_id": "0007",
            "source_feature_uid": "AG-001:0007",
            "assessment_type": "carbon_sequestration_agreement",
            "data_class": "regulatory_tenure",
            "capacity_data": False,
        },
        {
            "agreement_id": "AG-001",
            "tract_id": "0008",
            "source_feature_uid": "AG-001:0008",
            "assessment_type": "carbon_sequestration_agreement",
            "data_class": "regulatory_tenure",
            "capacity_data": False,
        },
    ]
    assert agreements[
        ["agreement_id", "tract_count", "zone_description"]
    ].to_dict("records") == [
        {
            "agreement_id": "AG-001",
            "tract_count": 2,
            "zone_description": "Basal zone | Upper zone",
        }
    ]
    assert qa["source_feature_count"] == 2
    assert qa["tract_feature_count"] == 2
    assert tracts.crs is not None
    assert agreements.crs is not None
    assert tracts.crs.to_epsg() == 3978
    assert agreements.crs.to_epsg() == 3978


def test_gsc_golden_output_preserves_prospectivity_as_non_capacity(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """GSC COS fields remain mapped prospectivity evidence, not capacity."""

    gsc_fixture = request.getfixturevalue("gsc_source")

    monkeypatch.setattr(
        gsc_atlantic,
        "read_source_layer",
        lambda path: (gsc_fixture.copy(), []),
    )

    result, qa = gsc_atlantic.harmonize_layer(
        Path("Bjarni.shp")
    )

    assert result[
        [
            "feature_id",
            "storage_unit_id",
            "reservoir_cos",
            "seal_cos",
            "trap_cos",
            "total_cos",
            "cos_components",
            "assessment_type",
            "data_class",
            "capacity_data",
            "source_feature_id",
        ]
    ].to_dict("records") == [
        {
            "feature_id": "gsc8996_bjarni_f000000",
            "storage_unit_id": "gsc8996_bjarni",
            "reservoir_cos": 0.4,
            "seal_cos": 0.8,
            "trap_cos": 0.6,
            "total_cos": 0.3,
            "cos_components": "reservoir_seal_trap",
            "assessment_type": "qualitative_chance_of_success",
            "data_class": "geological_prospectivity",
            "capacity_data": False,
            "source_feature_id": 0,
        }
    ]
    assert qa["source_feature_count"] == 1
    assert qa["silver_feature_count"] == 1
    assert result.crs is not None
    assert result.crs.to_epsg() == 3978
    assert result.geometry.is_valid.all()
