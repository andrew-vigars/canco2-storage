"""Golden-output tests for dataset-specific Silver harmonization semantics."""

from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

from canco2_storage.harmonize import aer_agreements, gsc_atlantic
from canco2_storage.harmonize import gbc_ne_atlas, natcarb_doe


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


def test_bc_golden_output_reconciles_capacity_and_flags_anomaly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BC logical aquifers keep P10/P50/P90 semantics at unit grain."""

    source_summary = pd.DataFrame(
        [
            {
                "source_shapefile": "aquifer.shp",
                "aquifer_name_key": "Dawson Creek",
                "source_feature_count": 2,
                "source_crs": "EPSG:4326",
                "source_theoretical_storage_mt": 0.0,
                "source_p10_storage_mt": 10.0,
                "source_p50_storage_mt": 20.0,
                "source_p90_storage_mt": 30.0,
                "source_co2_phases": "supercritical",
                "source_zero_theoretical_anomaly": True,
                "source_read_warning_count": 0,
                "source_read_warnings": "",
            }
        ]
    )
    appendix = pd.DataFrame(
        [
            {
                "formation": "Formation A",
                "aquifer_name": "Dawson Creek",
                "aquifer_type": "saline",
                "thickness_range_m": "10-20",
                "pressure_range_mpa": "5-10",
                "temperature_range_c": "20-30",
                "porosity_range_pct": "10-15",
                "co2_phase": "supercritical",
                "p10_effective_storage_mt": 10.0,
                "p50_effective_storage_mt": 20.0,
                "p90_effective_storage_mt": 30.0,
            }
        ]
    )

    monkeypatch.setattr(
        gbc_ne_atlas,
        "build_aquifer_source_summary",
        lambda paths: source_summary.copy(),
    )
    monkeypatch.setattr(
        gbc_ne_atlas,
        "read_aquifer_workbook",
        lambda workbook_path: appendix.copy(),
    )

    result = gbc_ne_atlas.build_aquifer_units(
        [Path("aquifer.shp")],
        workbook_path=Path("Appendix C.xlsx"),
    )

    record = result.iloc[0]
    assert record[
        [
            "storage_unit_id",
            "p10_effective_storage_mt",
            "p50_effective_storage_mt",
            "p90_effective_storage_mt",
            "theoretical_storage_mt",
            "theoretical_storage_method",
            "source_zero_theoretical_anomaly",
            "source_storage_values_match_appendix_c",
            "capacity_data",
        ]
    ].to_dict() == {
        "storage_unit_id": "gbc_aquifer_dawson_creek",
        "p10_effective_storage_mt": 10.0,
        "p50_effective_storage_mt": 20.0,
        "p90_effective_storage_mt": 30.0,
        "theoretical_storage_mt": 1000.0,
        "theoretical_storage_method": (
            "derived_from_appendix_c_p50_divided_by_0.02"
        ),
        "source_zero_theoretical_anomaly": True,
        "source_storage_values_match_appendix_c": True,
        "capacity_data": True,
    }


def test_natcarb_golden_output_preserves_capacity_flags_and_representations() -> None:
    """NATCARB dispatch keeps capacity values and provider flags explicit."""

    common = {
        "source_fid": [7],
        "PARTNERSHIP": ["P1"],
        "ASSESSED": [1],
        "OVERLAP": [1],
        "DUPLICATE": [1],
        "CYCLE_OF_LAST_UPDATE": ["2015"],
    }
    grid_source = gpd.GeoDataFrame(
        {
            **common,
            "COL_ROW": ["1_1"],
            "RESOURCE_NAME": ["Saline A"],
            "VOL_LOW": [100.0],
            "VOL_MED": [200.0],
            "VOL_HIGH": [300.0],
            "RSC_AREA_CELL": [1000.0],
            "ARRA_PROJECT": ["ARRA-1"],
            "BASIN_NAME": ["Basin A"],
            "MED_CALCED": [1],
            "DEPTH_FT": [1000.0],
            "THICKNESS_FT": [100.0],
            "SALINITY_TDS": [1000.0],
            "PRESSURE_PSI": [100.0],
            "TEMPERATURE_F": [68.0],
            "POROSITY_PCT": [10.0],
            "PERMEABILITY_mD": [1.0],
        },
        geometry=[Polygon([(0, 0), (1, 0), (1, 1), (0, 0)])],
        crs="EPSG:4326",
    )
    extent_source = gpd.GeoDataFrame(
        {
            **common,
            "ARRA_PROJECT": ["ARRA-1"],
            "RESOURCE_NAME": ["Saline A"],
            "BASIN_NAME": ["Basin A"],
        },
        geometry=[Polygon([(0, 0), (1, 0), (1, 1), (0, 0)])],
        crs="EPSG:4326",
    )

    grid = natcarb_doe.harmonize_layer(
        grid_source,
        natcarb_doe.LAYER_SPECS[0],
    )
    extent = natcarb_doe.harmonize_layer(
        extent_source,
        natcarb_doe.LAYER_SPECS[1],
    )
    capacity_qa = natcarb_doe.build_capacity_qa(
        grid,
        "saline_resource_cells",
    ).set_index("check")["count"].to_dict()

    assert grid[
        [
            "representation",
            "storage_p10_tonnes",
            "storage_p50_tonnes",
            "storage_p90_tonnes",
            "p50_method",
            "overlap",
            "duplicate",
            "capacity_data",
        ]
    ].to_dict("records") == [
        {
            "representation": "resource_grid_cell",
            "storage_p10_tonnes": 100.0,
            "storage_p50_tonnes": 200.0,
            "storage_p90_tonnes": 300.0,
            "p50_method": "natural_log_mean",
            "overlap": True,
            "duplicate": True,
            "capacity_data": True,
        }
    ]
    assert capacity_qa["rows"] == 1
    assert capacity_qa["overlap_rows"] == 1
    assert capacity_qa["duplicate_rows"] == 1
    assert capacity_qa["p10_gt_p50"] == 0
    assert capacity_qa["p50_gt_p90"] == 0
    assert extent["representation"].tolist() == ["resource_extent"]
    assert extent["capacity_data"].tolist() == [False]
    assert len(natcarb_doe.LAYER_SPECS) == 5
    assert {spec.representation for spec in natcarb_doe.LAYER_SPECS} == {
        "resource_grid_cell",
        "resource_extent",
        "storage_resource",
    }
