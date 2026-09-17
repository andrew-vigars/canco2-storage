"""Harmonize the Northeast BC Geological Carbon Capture and Storage Atlas.

The Bronze source consists of two complementary products from Geoscience BC
Report 2023-04:

- Appendix C — Pool Storage Database & Aquifer Storage Summary workbook
- Appendix E — Additional Maps and Shapefiles archive

This module converts those Bronze products into a standardized Silver package.

Workflow
--------
1. Discover and inventory the Appendix E shapefiles and Appendix C worksheets.
2. Classify the published Appendix E source layers.
3. Reconcile Appendix C pool records to the canonical master pool shapefile.
4. Build one logical pool-unit table and one pool-feature spatial layer.
5. Build one logical aquifer-unit table and one aquifer-feature spatial layer.
6. Preserve raw source values and explicit source-quality flags.
7. Repair invalid geometries when required and reproject spatial outputs to
   EPSG:3978 to match the existing CANCO2-Storage Silver packages.
8. Export logical-unit tables, spatial layers, dataset metadata, and QA into
   one GeoPackage.
9. Export the standardized Silver sidecars: source schema, source metadata,
   QA summary, and one combined field dictionary.
10. Keep workbook-schema and pool-reconciliation diagnostics in an inspection
    subdirectory when ``--inspect-only`` is requested.
11. Reopen and validate the persisted GeoPackage artifact.

No README is generated here. Dataset-level metadata remains stored inside the
GeoPackage so a later metadata module can generate the README from the
persisted artifact.

Bronze source files are never modified.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd

from canco2_storage.harmonize.common import (
    SILVER_CRS,
    project_and_measure,
    read_source_layer,
    repair_geometries,
    validate_registered_tables,
    validate_written_spatial_layer,
    write_registered_attribute_table,
)
from canco2_storage.metadata.common import (
    CANCO2RE_SUBMISSION,
    build_submission_stem,
)
from canco2_storage.paths import find_project_root


# =============================================================================
# Project paths and package naming
# =============================================================================

PROJECT_ROOT = find_project_root()

RAW_STORAGE = PROJECT_ROOT / "data" / "raw"
RAW_GBC_NE_ATLAS = RAW_STORAGE / "gbc_ne_atlas"

APPENDIX_C_PATH = (
    RAW_GBC_NE_ATLAS
    / "Appendix C - Pool Storage Database & Aquifer Storage Summary.xlsx"
)

APPENDIX_E_ROOT = (
    RAW_GBC_NE_ATLAS
    / "source"
)

PROCESSED_STORAGE = PROJECT_ROOT / "data" / "processed"
PROCESSED_GBC_NE_ATLAS = PROCESSED_STORAGE / "gbc_ne_atlas"

CREATED_DATE = date.today()

DATA_TYPE = "BCStorageAtlas"

SUBMISSION_STEM = build_submission_stem(
    data_type=DATA_TYPE,
    created_date=CREATED_DATE,
)

SILVER_GPKG_PATH = (
    PROCESSED_GBC_NE_ATLAS
    / f"{SUBMISSION_STEM}.gpkg"
)

SCHEMA_INVENTORY_PATH = (
    PROCESSED_GBC_NE_ATLAS
    / (
        f"{CREATED_DATE:%Y%m%d}_"
        f"{CANCO2RE_SUBMISSION.activity_code}_"
        f"{DATA_TYPE}SourceSchema_"
        f"{CANCO2RE_SUBMISSION.creator_initials}.csv"
    )
)

SOURCE_METADATA_PATH = (
    PROCESSED_GBC_NE_ATLAS
    / (
        f"{CREATED_DATE:%Y%m%d}_"
        f"{CANCO2RE_SUBMISSION.activity_code}_"
        f"{DATA_TYPE}SourceMetadata_"
        f"{CANCO2RE_SUBMISSION.creator_initials}.csv"
    )
)

QA_SUMMARY_PATH = (
    PROCESSED_GBC_NE_ATLAS
    / (
        f"{CREATED_DATE:%Y%m%d}_"
        f"{CANCO2RE_SUBMISSION.activity_code}_"
        f"{DATA_TYPE}QASummary_"
        f"{CANCO2RE_SUBMISSION.creator_initials}.csv"
    )
)

FIELD_DICTIONARY_PATH = (
    PROCESSED_GBC_NE_ATLAS
    / (
        f"{CREATED_DATE:%Y%m%d}_"
        f"{CANCO2RE_SUBMISSION.activity_code}_"
        f"{DATA_TYPE}FieldDictionary_"
        f"{CANCO2RE_SUBMISSION.creator_initials}.csv"
    )
)

INSPECTION_DIR = (
    PROCESSED_GBC_NE_ATLAS
    / "inspection"
)

WORKBOOK_INVENTORY_PATH = (
    INSPECTION_DIR
    / (
        f"{CREATED_DATE:%Y%m%d}_"
        f"{CANCO2RE_SUBMISSION.activity_code}_"
        f"{DATA_TYPE}WorkbookSchema_"
        f"{CANCO2RE_SUBMISSION.creator_initials}.csv"
    )
)

POOL_RECONCILIATION_PATH = (
    INSPECTION_DIR
    / (
        f"{CREATED_DATE:%Y%m%d}_"
        f"{CANCO2RE_SUBMISSION.activity_code}_"
        f"{DATA_TYPE}PoolReconciliation_"
        f"{CANCO2RE_SUBMISSION.creator_initials}.csv"
    )
)

TARGET_CRS = SILVER_CRS


# =============================================================================
# Source metadata
# =============================================================================

DATASET_ID = "gbc_ne_atlas"

SOURCE_ORGANIZATION = "Geoscience BC"
SOURCE_PREPARER = "Canadian Discovery Ltd."

SOURCE_TITLE = (
    "Northeast BC Geological Carbon Capture and Storage Atlas"
)

SOURCE_PUBLICATION = "Geoscience BC Report 2023-04"
SOURCE_YEAR = 2023

SOURCE_PROJECT_URL = "https://www.geosciencebc.com/projects/2022-001/"

SOURCE_PARENT_URL = (
    "https://www2.gov.bc.ca/gov/content/industry/"
    "natural-gas-oil/responsible-oil-gas-development/"
    "carbon-capture-storage/geological-potential"
)

ASSESSMENT_TYPE = "quantitative_geological_storage_screening"
DATA_CLASS = "geological_storage_capacity"
CAPACITY_DATA = True
INJECTIVITY_STATUS = "not_quantitatively_assessed"


# =============================================================================
# Published source relationships
# =============================================================================

POOL_MASTER_FILENAME = (
    "BCOGC_POOLS_CO2_STORAGE_CDL_83UTM10_PG.shp"
)

POOL_LINK_FIELD = "LINK_CODE"
POOL_WORKBOOK_LINK_FIELD = "Code for Link to Shapefile"

POOL_WORKBOOK_SHEETS = (
    "Current CO2 Storage Candidates",
    "Future CO2 Storage Candidates",
    "Oil Pools for CO2-EOR Eval",
)

POOL_CLASS_BY_SHEET = {
    "Current CO2 Storage Candidates": "current_candidate",
    "Future CO2 Storage Candidates": "future_candidate",
    "Oil Pools for CO2-EOR Eval": "co2_eor_candidate",
}

AQUIFER_WORKBOOK_SHEET = "Aquifer Storage Summary"

AQUIFER_NAME_MAP = {
    "GBCS_PEACE_RIVER_AQUIFER_DAWSON_83UTM10_PG.shp":
        "Dawson Creek",
    "GBCS_BLUESKY_AQUIFER_CO2_STORAGE_CHINCHAGA_DAHL_83UTM10_PG.shp":
        "Chinchaga-Dahl",
    "GBCS_BLUESKY_AQUIFER_CO2_STORAGE_DOE_AIRPORT_83UTM10_PG.shp":
        "Doe-Airport",
    "GBCS_CADOMIN_AQUIFER_PARKLAND_MUSKRAT_83UTM10_PG.shp":
        "Parkland-Muskrat",
    "GBCS_CADOMIN_AQUIFER_STODDART_WEST_83UTM10_PG.shp":
        "Stoddart West",
    "GBCS_CADOMIN_AQUIFER_SUNRISE_DOE_83UTM10_PG.shp":
        "Sunrise-Doe",
    "GBCS_NIKANASSIN_AQUIFER_BEG_SIPHON_83UTM10_PG.shp":
        "Beg-Siphon",
    "GBCS_NIKANASSIN_AQUIFER_BLUEBERRY_TWO_RIVERS_83UTM10_PG.shp":
        "Blueberry-Two Rivers",
    "GBCS_NIKANASSIN_AQUIFER_BRASSEY_CUTBANK_83UTM10_PG.shp":
        "Brassey-Cutbank",
    "GBCS_BALDONNEL_AQUIFER_BOUNDARY_LAKE_OSPREY_83UTM10_PG.shp":
        "Boundary Lake-Osprey",
    "GBCS_BALDONNEL_AQUIFER_DAWSON_83UTM10_PG.shp":
        "Dawson",
    "GBCS_BALDONNEL_AQUIFER_MONIAS_BEG_83UTM10_PG.shp":
        "Monias-Beg",
    "GBCS_BALDONNEL_AQUIFER_PARKLAND_STODDART_83UTM10_PG.shp":
        "Parkland-Stoddart",
    "GBCS_HALFWAY_AQUIFER_FLATROCK_MONIAS_83UTM10_PG.shp":
        "Flatrock-Monias",
    "GBCS_HALFWAY_AQUIFER_PEEJAY_WEASEL_83UTM10_PG.shp":
        "Peejay-Weasel",
    "GBCS_HALFWAY_AQUIFER_WEST_FIREWEED_83UTM10_PG.shp":
        "Fireweed-Martin",
    "GBCS_BELLOY_AQUIFER_BOUNDARY_LAKE_83UTM10_PG.shp":
        "Boundary Lake",
    "GBCS_BELLOY_AQUIFER_DOE_STODDART_83UTM10_PG.shp":
        "Doe-Stoddart",
    "GBCS_BELLOY_AQUIFER_LADYFERN_RING_83UTM10_PG.shp":
        "Ladyfern-Ring",
    "GBCS_DEBOLT_AQUIFER_NORTH_OSBORN_RING_83UTM83_PG.shp":
        "Osborn-Ring",
    "GBCS_DEBOLT_AQUIFER_WEST_BLUEBERRY_83UTM83_PG.shp":
        "Blueberry-Buick",
    "GBCS_SLVPT_AQUIFER_NORTH_10UTM83_PG.shp":
        "North",
    "GBCS_SLVPT_AQUIFER_CENTRAL_10UTM83_PG.shp":
        "Central",
    "GBCS_SLVPT_AQUIFER_SOUTH_10UTM83_PG.shp":
        "South",
    "GBCS_SLVPT_AQUIFER_SOUTH_MUSKEG_10UTM83_PG.shp":
        "South Muskeg",
}

AQUIFER_FIELD_VARIANTS = {
    "source_theoretical_storage_mt": (
        "Th_SCap_MT",
        "TH_SCap_MT",
    ),
    "source_p10_storage_mt": (
        "Eff_SCap_h",
    ),
    "source_p50_storage_mt": (
        "Eff_SCap_2",
        "Eff_Scap_2",
    ),
    "source_p90_storage_mt": (
        "Eff_SCap_5",
        "Eff_Scap_5",
    ),
    "source_co2_phase": (
        "CO2_PHASE",
        "CO2_Phase",
    ),
    "source_shape_length": (
        "SHAPE_Leng",
        "Shape_Leng",
    ),
    "source_shape_area": (
        "SHAPE_Area",
        "Shape_Area",
    ),
}


# =============================================================================
# Canonical output columns
# =============================================================================

POOL_UNIT_COLUMNS = [
    "storage_unit_id",
    "storage_unit_type",
    "formation",
    "pool_class",
    "pool_name",
    "field_code",
    "pool_code",
    "pool_sequence",
    "pool_type",
    "map_group",
    "well_count",
    "initial_pressure_kpa",
    "temperature_c",
    "porosity_fraction",
    "pool_datum_tvd_m",
    "approx_pool_elevation_msl",
    "co2_phase",
    "theoretical_storage_mt",
    "effective_storage_mt",
    "potentially_commingled",
    "cumulative_gas_production_e3m3",
    "cumulative_condensate_production_m3",
    "cumulative_oil_production_m3",
    "cumulative_water_production_m3",
    "cumulative_gas_injection_e3m3",
    "cumulative_water_injection_m3",
    "cumulative_gas_disposal_e3m3",
    "cumulative_water_disposal_m3",
    "recovery_factor",
    "inactive_5plus_years",
    "discovery_well",
    "discovery_well_latitude",
    "discovery_well_longitude",
    "within_disturbed_belt",
    "source_link_code",
    "source_sheet",
    "source_dataset",
    "assessment_type",
    "data_class",
    "capacity_data",
]

POOL_FEATURE_COLUMNS = [
    "storage_feature_id",
    "storage_unit_id",
    "source_feature_order",
    "source_feature_count",
    "source_link_code",
    "source_pool_uid",
    "source_pool_name",
    "source_formation_name",
    "source_fluid_type",
    "source_theoretical_storage_mt",
    "source_effective_storage_mt",
    "source_co2_phase",
    "source_candidate_flag",
    "source_cdl_candidate_flag",
    "source_pool_area_ha",
    "source_file",
    "source_crs",
    "geometry_area_m2",
    "geometry_area_ha",
    "geometry_perimeter_m",
    "geometry",
]

AQUIFER_UNIT_COLUMNS = [
    "storage_unit_id",
    "storage_unit_type",
    "formation",
    "aquifer_name",
    "aquifer_type",
    "thickness_range_m",
    "pressure_range_mpa",
    "temperature_range_c",
    "porosity_range_pct",
    "co2_phase",
    "p10_effective_storage_mt",
    "p50_effective_storage_mt",
    "p90_effective_storage_mt",
    "theoretical_storage_mt",
    "theoretical_storage_method",
    "source_shapefile",
    "source_feature_count",
    "source_theoretical_storage_mt",
    "source_p10_storage_mt",
    "source_p50_storage_mt",
    "source_p90_storage_mt",
    "source_co2_phases",
    "source_zero_theoretical_anomaly",
    "source_storage_values_match_appendix_c",
    "source_dataset",
    "source_sheet",
    "assessment_type",
    "data_class",
    "capacity_data",
]

AQUIFER_FEATURE_COLUMNS = [
    "storage_feature_id",
    "storage_unit_id",
    "aquifer_name",
    "source_feature_order",
    "source_feature_count",
    "source_file",
    "source_crs",
    "source_name",
    "source_rec_id",
    "source_theoretical_storage_mt",
    "source_p10_storage_mt",
    "source_p50_storage_mt",
    "source_p90_storage_mt",
    "source_co2_phase",
    "source_shape_length",
    "source_shape_area",
    "geometry_area_m2",
    "geometry_area_ha",
    "geometry_perimeter_m",
    "geometry",
]


# =============================================================================
# Bronze discovery and inspection
# =============================================================================

def discover_shapefiles(
    appendix_e_root: Path = APPENDIX_E_ROOT,
) -> list[Path]:
    """Return all Bronze Appendix E shapefiles."""

    if not appendix_e_root.is_dir():
        raise FileNotFoundError(
            f"Appendix E source directory not found: {appendix_e_root}"
        )

    shapefiles = sorted(
        appendix_e_root.rglob("*.shp")
    )

    if not shapefiles:
        raise FileNotFoundError(
            f"No shapefiles found under {appendix_e_root}"
        )

    return shapefiles



def inspect_shapefile(
    path: Path,
    *,
    appendix_e_root: Path = APPENDIX_E_ROOT,
) -> dict[str, object]:
    """Inspect one Bronze shapefile without modifying source data."""

    gdf, warning_messages = read_source_layer(path)

    crs = gdf.crs

    if crs is None:
        raise ValueError(
            f"Source shapefile has no CRS: {path}"
        )

    geometry_types = sorted(
        str(value)
        for value in gdf.geometry.geom_type.dropna().unique()
    )

    relative_path = path.relative_to(
        appendix_e_root
    )

    return {
        "source_file": path.name,
        "relative_path": str(relative_path),
        "parent_directory": path.parent.name,
        "feature_count": len(gdf),
        "source_crs": crs.to_string(),
        "source_epsg": crs.to_epsg(),
        "geometry_types": ", ".join(geometry_types),
        "column_count": len(gdf.columns),
        "columns": ", ".join(
            str(column)
            for column in gdf.columns
        ),
        "null_geometry_count": int(
            gdf.geometry.isna().sum()
        ),
        "invalid_geometry_count": int(
            (~gdf.geometry.is_valid).sum()
        ),
        "read_warnings": " | ".join(
            warning_messages
        ),
    }


def build_shapefile_inventory(
    shapefiles: list[Path],
) -> pd.DataFrame:
    """Build a schema, geometry, and classification inventory for Appendix E."""

    inventory = pd.DataFrame(
        [
            inspect_shapefile(path)
            for path in shapefiles
        ]
    )

    inventory["source_class"] = (
        inventory["source_file"]
        .map(classify_source_layer)
    )

    return (
        inventory
        .sort_values(
            by=[
                "source_class",
                "relative_path",
                "source_file",
            ]
        )
        .reset_index(drop=True)
    )


def inspect_workbook(
    path: Path = APPENDIX_C_PATH,
) -> pd.DataFrame:
    """Inventory Appendix C worksheets and source columns."""

    if not path.is_file():
        raise FileNotFoundError(
            f"Appendix C workbook not found: {path}"
        )

    workbook = pd.ExcelFile(
        path,
        engine="openpyxl",
    )

    records: list[dict[str, object]] = []

    for sheet_name in workbook.sheet_names:
        dataframe = pd.read_excel(
            workbook,
            sheet_name=sheet_name,
        )

        records.append(
            {
                "sheet_name": str(sheet_name),
                "row_count": len(dataframe),
                "column_count": len(dataframe.columns),
                "columns": ", ".join(
                    str(column)
                    for column in dataframe.columns
                ),
            }
        )

    return pd.DataFrame(records)


# =============================================================================
# Source-layer classification
# =============================================================================

def classify_source_layer(source_file: str) -> str:
    """Classify one Appendix E shapefile by its published filename."""

    name = source_file.upper()

    if "BCOGC_POOLS_CO2_STORAGE_CDL" in name:
        return "pool_master"

    if "COMMINGLED" in name:
        return "pool_commingled_support"

    if (
        "POOL_NON_CANDIDATE" in name
        or "POOL_NON_CANDIDATES" in name
    ):
        return "pool_non_candidate"

    if (
        "POOL_CANDIDATE" in name
        or "POOL_CANDIDATES" in name
    ):
        return "pool_candidate"

    if "_AQUIFER_" in name:
        return "aquifer_storage"

    if (
        "POOL_NET_RES" in name
        or "POOL_NET_RESERVOIR" in name
    ):
        return "pool_net_reservoir_support"

    if "POOL_CONTOUR" in name:
        return "pool_contour_support"

    if "NET_RES" in name:
        return "net_reservoir_support"

    if "STRUCTURE_ELEV" in name:
        return "structure_support"

    if "ABSOL_PRESSURE" in name:
        return "pressure_support"

    if "ISOTHERM" in name:
        return "temperature_support"

    if "TVD_800" in name:
        return "depth_support"

    if "GHG_EMISS" in name:
        return "emissions_reference"

    return "other_support"


# =============================================================================
# Generic helpers
# =============================================================================

def slugify_identifier(value: object) -> str:
    """Convert a source label into a stable lowercase identifier fragment."""

    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def first_existing_series(
    gdf: gpd.GeoDataFrame,
    candidates: tuple[str, ...],
) -> pd.Series:
    """Return the first existing source field, or an all-null Series."""

    for field in candidates:
        if field in gdf.columns:
            return gdf[field]

    return pd.Series(
        pd.NA,
        index=gdf.index,
        dtype="object",
    )


def unique_numeric_value(
    gdf: gpd.GeoDataFrame,
    candidates: tuple[str, ...],
) -> float | None:
    """Return one logical numeric aquifer value from repeated source features.

    For multi-feature aquifers, zero values may coexist with one repeated
    nonzero storage estimate. In that case, preserve the nonzero value as the
    logical source value. Multiple distinct nonzero values remain an error.
    """

    series = pd.to_numeric(
        first_existing_series(
            gdf,
            candidates,
        ),
        errors="coerce",
    ).dropna()

    if series.empty:
        return None

    nonzero = (
        series[
            series != 0
        ]
        .drop_duplicates()
    )

    if len(nonzero) == 1:
        return float(
            nonzero.iloc[0]
        )

    if len(nonzero) > 1:
        raise ValueError(
            "Expected at most one distinct nonzero aquifer value "
            f"across source features, found {nonzero.tolist()}."
        )

    zero_values = (
        series
        .drop_duplicates()
    )

    if len(zero_values) == 1:
        return float(
            zero_values.iloc[0]
        )

    raise ValueError(
        "Could not resolve a single logical aquifer value from "
        f"source values {zero_values.tolist()}."
    )



# =============================================================================
# Pool-source reconciliation
# =============================================================================

def find_pool_master(
    shapefiles: list[Path],
) -> Path:
    """Return the canonical Appendix E master pool shapefile."""

    matches = [
        path
        for path in shapefiles
        if path.name == POOL_MASTER_FILENAME
    ]

    if len(matches) != 1:
        raise ValueError(
            "Expected exactly one master pool shapefile, "
            f"found {len(matches)}."
        )

    return matches[0]


def find_pool_candidate_layers(
    shapefiles: list[Path],
) -> list[Path]:
    """Return formation-specific pool candidate shapefiles."""

    return sorted(
        path
        for path in shapefiles
        if classify_source_layer(path.name) == "pool_candidate"
    )


def reconcile_pool_sources(
    shapefiles: list[Path],
    workbook_path: Path = APPENDIX_C_PATH,
) -> pd.DataFrame:
    """Compare pool identifiers across Appendix C and Appendix E."""

    master_path = find_pool_master(shapefiles)
    candidate_paths = find_pool_candidate_layers(shapefiles)

    master, _ = read_source_layer(master_path)

    if POOL_LINK_FIELD not in master.columns:
        raise ValueError(
            f"{master_path.name} is missing {POOL_LINK_FIELD}."
        )

    master_codes = set(
        master[POOL_LINK_FIELD]
        .dropna()
        .astype(str)
        .str.strip()
    )

    records: list[dict[str, object]] = []

    for path in candidate_paths:
        gdf, _ = read_source_layer(path)

        if POOL_LINK_FIELD not in gdf.columns:
            raise ValueError(
                f"{path.name} is missing {POOL_LINK_FIELD}."
            )

        codes = (
            gdf[POOL_LINK_FIELD]
            .dropna()
            .astype(str)
            .str.strip()
        )

        unique_codes = set(codes)

        records.append(
            {
                "source_type": "candidate_shapefile",
                "source_name": path.name,
                "row_count": len(gdf),
                "unique_link_codes": len(unique_codes),
                "duplicate_link_code_rows": int(
                    codes.duplicated().sum()
                ),
                "matched_to_master": len(
                    unique_codes & master_codes
                ),
                "unmatched_to_master": len(
                    unique_codes - master_codes
                ),
            }
        )

    for sheet_name in POOL_WORKBOOK_SHEETS:
        dataframe = pd.read_excel(
            workbook_path,
            sheet_name=sheet_name,
            engine="openpyxl",
        )

        if POOL_WORKBOOK_LINK_FIELD not in dataframe.columns:
            raise ValueError(
                f"{sheet_name} is missing "
                f"{POOL_WORKBOOK_LINK_FIELD}."
            )

        codes = (
            dataframe[POOL_WORKBOOK_LINK_FIELD]
            .dropna()
            .astype(str)
            .str.strip()
        )

        unique_codes = set(codes)

        records.append(
            {
                "source_type": "workbook_sheet",
                "source_name": sheet_name,
                "row_count": len(dataframe),
                "unique_link_codes": len(unique_codes),
                "duplicate_link_code_rows": int(
                    codes.duplicated().sum()
                ),
                "matched_to_master": len(
                    unique_codes & master_codes
                ),
                "unmatched_to_master": len(
                    unique_codes - master_codes
                ),
            }
        )

    return pd.DataFrame(records)


# =============================================================================
# Pool harmonization
# =============================================================================

POOL_COLUMN_MAP = {
    "Pool Name": "pool_name",
    "Field Code": "field_code",
    "Pool Code": "pool_code",
    "Pool Sequence": "pool_sequence",
    "Pool Type": "pool_type",
    "Map Group": "map_group",
    "Well Count": "well_count",
    "Initial Pressure (kPa)": "initial_pressure_kpa",
    "Temperature (⁰C)": "temperature_c",
    "Porosity (frac)": "porosity_fraction",
    "Pool Datum TVD (m)": "pool_datum_tvd_m",
    "Approximate Pool  Elevation (mSL)": "approx_pool_elevation_msl",
    "CO2 Phase": "co2_phase",
    "Theoretical Storage Potential (Mt)": "theoretical_storage_mt",
    "Effective Storage Potential (Mt)": "effective_storage_mt",
    "Potentially Commingled?": "potentially_commingled",
    "Cumulative Gas Production (e3m3)":
        "cumulative_gas_production_e3m3",
    "Cumulative Condensate Production (m3)":
        "cumulative_condensate_production_m3",
    "Cumulative Oil Production (m3)":
        "cumulative_oil_production_m3",
    "Cumulative Water Production (m3)":
        "cumulative_water_production_m3",
    "Cumulative Gas Injection (e3m3)":
        "cumulative_gas_injection_e3m3",
    "Cumulative Water Injection (m3)":
        "cumulative_water_injection_m3",
    "Cumulative Gas Disposal (e3m3)":
        "cumulative_gas_disposal_e3m3",
    "Cumulative Water Disposal (m3)":
        "cumulative_water_disposal_m3",
    "Inactive for 5+ years": "inactive_5plus_years",
    "Discovery Well": "discovery_well",
    "Discovery Well Latitude (NAD 83)": "discovery_well_latitude",
    "Discovery Well Longitude (NAD 83)": "discovery_well_longitude",
    "Within Disturbed Belt (Additional Evaluation Required)":
        "within_disturbed_belt",
    POOL_WORKBOOK_LINK_FIELD: "source_link_code",
}


def read_pool_workbook(
    workbook_path: Path = APPENDIX_C_PATH,
) -> pd.DataFrame:
    """Read and combine the three Appendix C pool-storage worksheets."""

    frames: list[pd.DataFrame] = []

    for sheet_name, pool_class in POOL_CLASS_BY_SHEET.items():
        dataframe = pd.read_excel(
            workbook_path,
            sheet_name=sheet_name,
            engine="openpyxl",
        ).copy()

        if POOL_WORKBOOK_LINK_FIELD not in dataframe.columns:
            raise ValueError(
                f"{sheet_name} is missing "
                f"{POOL_WORKBOOK_LINK_FIELD}."
            )

        gas_recovery = dataframe.get(
            "Gas Recovery Factor",
            pd.Series(pd.NA, index=dataframe.index),
        )
        oil_recovery = dataframe.get(
            "Oil Recovery Factor",
            pd.Series(pd.NA, index=dataframe.index),
        )

        dataframe["recovery_factor"] = (
            gas_recovery.combine_first(oil_recovery)
        )

        dataframe = dataframe.rename(
            columns=POOL_COLUMN_MAP
        )

        dataframe["source_sheet"] = sheet_name
        dataframe["pool_class"] = pool_class

        frames.append(dataframe)

    pools = pd.concat(
        frames,
        ignore_index=True,
    )

    pools["source_link_code"] = (
        pools["source_link_code"]
        .astype("string")
        .str.strip()
    )

    return pools


def build_pool_units(
    workbook_path: Path = APPENDIX_C_PATH,
) -> pd.DataFrame:
    """Build one logical storage-unit record per Appendix C pool."""

    pools = read_pool_workbook(
        workbook_path
    ).copy()

    if pools.empty:
        raise ValueError(
            "Combined Appendix C pool table is empty."
        )

    if pools["source_link_code"].isna().any():
        raise ValueError(
            "Appendix C pool table contains null link codes."
        )

    if pools["source_link_code"].duplicated().any():
        duplicate_values = (
            pools.loc[
                pools["source_link_code"].duplicated(keep=False),
                "source_link_code",
            ]
            .unique()
            .tolist()
        )
        raise ValueError(
            "Appendix C pool table contains duplicate logical "
            f"link codes: {duplicate_values}"
        )

    pools["storage_unit_id"] = (
        "gbc_pool_"
        + pools["source_link_code"]
    )
    pools["storage_unit_type"] = "depleted_or_near_depleted_pool"
    pools["source_dataset"] = DATASET_ID
    pools["assessment_type"] = ASSESSMENT_TYPE
    pools["data_class"] = DATA_CLASS
    pools["capacity_data"] = CAPACITY_DATA

    return pools[POOL_UNIT_COLUMNS].copy()


def read_pool_master(
    shapefiles: list[Path],
) -> tuple[gpd.GeoDataFrame, list[str], Path]:
    """Read the canonical Appendix E master pool geometry layer."""

    master_path = find_pool_master(
        shapefiles
    )

    master, warning_messages = read_source_layer(
        master_path
    )

    if POOL_LINK_FIELD not in master.columns:
        raise ValueError(
            f"{master_path.name} is missing "
            f"{POOL_LINK_FIELD}."
        )

    master = master.copy()

    master[POOL_LINK_FIELD] = (
        master[POOL_LINK_FIELD]
        .astype("string")
        .str.strip()
    )

    return master, warning_messages, master_path

def build_pool_features(
    shapefiles: list[Path],
    pool_units: pd.DataFrame,
) -> tuple[gpd.GeoDataFrame, dict[str, object]]:
    """Build spatial pool features linked to logical Appendix C pool units."""

    master, warning_messages, master_path = (
        read_pool_master(shapefiles)
    )

    master_crs = master.crs

    if master_crs is None:
        raise ValueError(
            f"Master pool layer has no CRS: {master_path}"
        )

    source_crs = master_crs.to_string()

    native, invalid_native_before, invalid_native_after = (
        repair_geometries(master)
    )

    if invalid_native_after:
        raise ValueError(
            "Master pool layer still contains invalid geometries "
            "after native-CRS repair."
        )

    required_source_fields = {
        POOL_LINK_FIELD,
        "POOL_UID",
        "POOL_NAME",
        "FORM_NAME",
        "FLUID_TYPE",
        "TSTOR_MT",
        "ESTOR_MT",
        "CO2_PHASE",
        "CANDIDATE",
        "CDL_CAND",
        "PL_AREA_HA",
    }

    missing_source_fields = (
        required_source_fields
        - set(native.columns)
    )

    if missing_source_fields:
        raise ValueError(
            "Master pool layer is missing required fields: "
            f"{sorted(missing_source_fields)}"
        )

    lookup = (
        pool_units[
            [
                "source_link_code",
                "storage_unit_id",
            ]
        ]
        .rename(
            columns={
                "source_link_code": POOL_LINK_FIELD,
            }
        )
    )

    selected = native.merge(
        lookup,
        on=POOL_LINK_FIELD,
        how="inner",
        validate="many_to_one",
    )

    selected["source_feature_order"] = (
        selected
        .groupby(
            "storage_unit_id",
            sort=False,
        )
        .cumcount()
        + 1
    )

    selected["source_feature_count"] = (
        selected
        .groupby(
            "storage_unit_id"
        )["storage_unit_id"]
        .transform("size")
    )

    selected["storage_feature_id"] = (
        selected["storage_unit_id"]
        + "_f"
        + selected["source_feature_order"]
        .astype("string")
        .str.zfill(3)
    )

    selected["source_link_code"] = (
        selected[POOL_LINK_FIELD]
    )

    selected["source_pool_uid"] = (
        selected["POOL_UID"]
    )

    selected["source_pool_name"] = (
        selected["POOL_NAME"]
    )

    selected["source_formation_name"] = (
        selected["FORM_NAME"]
    )

    selected["source_fluid_type"] = (
        selected["FLUID_TYPE"]
    )

    selected["source_theoretical_storage_mt"] = (
        pd.to_numeric(
            selected["TSTOR_MT"],
            errors="coerce",
        )
    )

    selected["source_effective_storage_mt"] = (
        pd.to_numeric(
            selected["ESTOR_MT"],
            errors="coerce",
        )
    )

    selected["source_co2_phase"] = (
        selected["CO2_PHASE"]
    )

    selected["source_candidate_flag"] = (
        selected["CANDIDATE"]
    )

    selected["source_cdl_candidate_flag"] = (
        selected["CDL_CAND"]
    )

    selected["source_pool_area_ha"] = (
        pd.to_numeric(
            selected["PL_AREA_HA"],
            errors="coerce",
        )
    )

    selected["source_file"] = (
        master_path.name
    )

    selected["source_crs"] = (
        source_crs
    )

    selected = gpd.GeoDataFrame(
        selected,
        geometry="geometry",
        crs=master_crs,
    )

    silver, invalid_projected_before, invalid_projected_after = (
        project_and_measure(selected)
    )

    final = silver[
        POOL_FEATURE_COLUMNS
    ].copy()

    logical_ids = set(
        pool_units["storage_unit_id"]
    )

    spatial_ids = set(
        final["storage_unit_id"]
    )

    missing = logical_ids - spatial_ids

    if missing:
        raise ValueError(
            "Logical pool units are missing spatial geometry: "
            f"{sorted(missing)}"
        )

    if final["storage_feature_id"].duplicated().any():
        raise ValueError(
            "Pool feature IDs are not unique."
        )

    qa = {
        "pool_master_source_file":
            master_path.name,
        "pool_master_source_crs":
            source_crs,
        "pool_master_source_feature_count":
            len(master),
        "pool_selected_feature_count":
            len(final),
        "pool_logical_unit_count":
            len(pool_units),
        "pool_multi_feature_unit_count":
            int(
                (
                    final[
                        [
                            "storage_unit_id",
                            "source_feature_count",
                        ]
                    ]
                    .drop_duplicates()
                    ["source_feature_count"]
                    > 1
                ).sum()
            ),
        "pool_invalid_native_before_repair":
            invalid_native_before,
        "pool_invalid_native_after_repair":
            invalid_native_after,
        "pool_invalid_projected_before_repair":
            invalid_projected_before,
        "pool_invalid_projected_after_repair":
            invalid_projected_after,
        "pool_read_warning_count":
            len(warning_messages),
        "pool_read_warnings":
            " | ".join(warning_messages),
    }

    return final, qa



def propagate_pool_formations(
    pool_units: pd.DataFrame,
    pool_features: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """Propagate consensus Appendix E formation names to logical pool units."""

    def consensus_formation(values: pd.Series) -> str | None:
        """Return one formation when all populated feature values agree."""

        cleaned = (
            values.dropna()
            .astype("string")
            .str.strip()
        )

        unique_values = (
            cleaned.loc[cleaned.ne("")]
            .unique()
            .tolist()
        )

        if len(unique_values) == 1:
            return str(unique_values[0])

        return None

    formation_lookup = (
        pool_features
        .groupby("storage_unit_id")["source_formation_name"]
        .agg(consensus_formation)
    )

    output = pool_units.copy()

    output["formation"] = (
        output["storage_unit_id"]
        .map(formation_lookup)
    )

    return output

# =============================================================================
# Aquifer harmonization
# =============================================================================

AQUIFER_COLUMN_MAP = {
    "Formation": "formation",
    "Aquifer Name": "aquifer_name",
    "Type": "aquifer_type",
    "Thickness Range (m)": "thickness_range_m",
    "Pressure Range (MPa)": "pressure_range_mpa",
    "Temperature Range (C)": "temperature_range_c",
    "Porosity Range (%)": "porosity_range_pct",
    "CO2 Phase": "co2_phase",
    "P10 Effective Storage Potential at 0.5% (Mt)":
        "p10_effective_storage_mt",
    "P50 Effective Storage Potential at 2% (Mt)":
        "p50_effective_storage_mt",
    "P90 Effective Storage Potential at 5.4% (Mt)":
        "p90_effective_storage_mt",
}


def find_aquifer_layers(
    shapefiles: list[Path],
) -> list[Path]:
    """Return the 25 published aquifer storage shapefiles."""

    paths = sorted(
        path
        for path in shapefiles
        if classify_source_layer(path.name) == "aquifer_storage"
    )

    discovered = {path.name for path in paths}
    mapped = set(AQUIFER_NAME_MAP)

    missing_mappings = discovered - mapped
    stale_mappings = mapped - discovered

    if missing_mappings or stale_mappings:
        raise ValueError(
            "Aquifer filename registry does not match the Bronze dataset. "
            f"Unmapped files: {sorted(missing_mappings)}; "
            f"mapped but missing files: {sorted(stale_mappings)}."
        )

    return paths


def read_aquifer_workbook(
    workbook_path: Path = APPENDIX_C_PATH,
) -> pd.DataFrame:
    """Read and standardize the Appendix C aquifer summary."""

    aquifers = pd.read_excel(
        workbook_path,
        sheet_name=AQUIFER_WORKBOOK_SHEET,
        engine="openpyxl",
    ).rename(
        columns=AQUIFER_COLUMN_MAP
    )

    required = set(
        AQUIFER_COLUMN_MAP.values()
    )

    missing = required - set(aquifers.columns)

    if missing:
        raise ValueError(
            "Aquifer workbook sheet is missing required harmonized "
            f"fields: {sorted(missing)}"
        )

    aquifers = aquifers.copy()

    aquifers["aquifer_name"] = (
        aquifers["aquifer_name"]
        .astype("string")
        .str.strip()
    )

    if aquifers["aquifer_name"].duplicated().any():
        raise ValueError(
            "Appendix C aquifer names are not unique after trimming."
        )

    return aquifers


def build_aquifer_source_summary(
    aquifer_paths: list[Path],
) -> pd.DataFrame:
    """Build one source-summary record per logical aquifer shapefile."""

    records: list[dict[str, object]] = []

    for path in aquifer_paths:
        gdf, warning_messages = read_source_layer(path)

        source_crs = gdf.crs

        if source_crs is None:
            raise ValueError(
                f"Aquifer source layer has no CRS: {path}"
            )

        mapped_name = AQUIFER_NAME_MAP[path.name].strip()

        theoretical = unique_numeric_value(
            gdf,
            AQUIFER_FIELD_VARIANTS[
                "source_theoretical_storage_mt"
            ],
        )

        p10 = unique_numeric_value(
            gdf,
            AQUIFER_FIELD_VARIANTS[
                "source_p10_storage_mt"
            ],
        )

        p50 = unique_numeric_value(
            gdf,
            AQUIFER_FIELD_VARIANTS[
                "source_p50_storage_mt"
            ],
        )

        p90 = unique_numeric_value(
            gdf,
            AQUIFER_FIELD_VARIANTS[
                "source_p90_storage_mt"
            ],
        )

        phase_series = (
            first_existing_series(
                gdf,
                AQUIFER_FIELD_VARIANTS[
                    "source_co2_phase"
                ],
            )
            .dropna()
            .astype(str)
            .str.strip()
        )

        phases = sorted(
            value
            for value in phase_series.unique()
            if value
        )

        zero_theoretical_anomaly = bool(
            theoretical is not None
            and theoretical == 0
            and p50 is not None
            and p50 > 0
        )

        records.append(
            {
                "source_shapefile":
                    path.name,
                "aquifer_name_key":
                    mapped_name,
                "source_feature_count":
                    len(gdf),
                "source_crs":
                    source_crs.to_string(),
                "source_theoretical_storage_mt":
                    theoretical,
                "source_p10_storage_mt":
                    p10,
                "source_p50_storage_mt":
                    p50,
                "source_p90_storage_mt":
                    p90,
                "source_co2_phases":
                    " | ".join(phases),
                "source_zero_theoretical_anomaly":
                    zero_theoretical_anomaly,
                "source_read_warning_count":
                    len(warning_messages),
                "source_read_warnings":
                    " | ".join(warning_messages),
            }
        )

    return pd.DataFrame(records)


def build_aquifer_units(
    aquifer_paths: list[Path],
    workbook_path: Path = APPENDIX_C_PATH,
) -> pd.DataFrame:
    """Build one logical storage-unit record per Appendix C aquifer."""

    appendix = read_aquifer_workbook(
        workbook_path
    ).copy()

    appendix["aquifer_name_key"] = (
        appendix["aquifer_name"]
        .astype("string")
        .str.strip()
    )

    source_summary = build_aquifer_source_summary(
        aquifer_paths
    )

    combined = source_summary.merge(
        appendix,
        on="aquifer_name_key",
        how="left",
        validate="one_to_one",
    )

    if combined["aquifer_name"].isna().any():
        missing = combined.loc[
            combined["aquifer_name"].isna(),
            "aquifer_name_key",
        ].tolist()

        raise ValueError(
            "Aquifer shapefiles are missing Appendix C matches: "
            f"{missing}"
        )

    if len(combined) != len(appendix):
        raise ValueError(
            "Aquifer reconciliation did not preserve all Appendix C "
            f"records: {len(combined)} != {len(appendix)}."
        )

    tolerance = 0.11

    match_flags = []

    for _, row in combined.iterrows():
        row_matches = []

        for source_field, appendix_field in (
            (
                "source_p10_storage_mt",
                "p10_effective_storage_mt",
            ),
            (
                "source_p50_storage_mt",
                "p50_effective_storage_mt",
            ),
            (
                "source_p90_storage_mt",
                "p90_effective_storage_mt",
            ),
        ):
            left = row[source_field]
            right = row[appendix_field]

            if pd.isna(left) and pd.isna(right):
                row_matches.append(True)
            elif pd.isna(left) or pd.isna(right):
                row_matches.append(False)
            else:
                row_matches.append(
                    abs(float(left) - float(right))
                    < tolerance
                )

        match_flags.append(
            all(row_matches)
        )

    combined["source_storage_values_match_appendix_c"] = (
        match_flags
    )

    combined["theoretical_storage_mt"] = (
        pd.to_numeric(
            combined["p50_effective_storage_mt"],
            errors="coerce",
        )
        / 0.02
    )

    combined["theoretical_storage_method"] = (
        "derived_from_appendix_c_p50_divided_by_0.02"
    )

    combined["storage_unit_id"] = (
        "gbc_aquifer_"
        + combined["aquifer_name"]
        .map(slugify_identifier)
    )
    combined["storage_unit_type"] = "saline_aquifer"
    combined["source_dataset"] = DATASET_ID
    combined["source_sheet"] = AQUIFER_WORKBOOK_SHEET
    combined["assessment_type"] = ASSESSMENT_TYPE
    combined["data_class"] = DATA_CLASS
    combined["capacity_data"] = CAPACITY_DATA

    if combined["storage_unit_id"].duplicated().any():
        raise ValueError(
            "Generated aquifer storage_unit_id values are not unique."
        )

    return combined[AQUIFER_UNIT_COLUMNS].copy()


def build_aquifer_features(
    aquifer_paths: list[Path],
    aquifer_units: pd.DataFrame,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Build source-feature aquifer geometry with raw source values preserved."""

    frames: list[gpd.GeoDataFrame] = []
    qa_rows: list[dict[str, object]] = []

    unit_lookup = (
        aquifer_units[
            [
                "storage_unit_id",
                "aquifer_name",
            ]
        ]
        .set_index("aquifer_name")
        ["storage_unit_id"]
        .to_dict()
    )

    for path in aquifer_paths:
        source, warning_messages = read_source_layer(path)

        source_crs_object = source.crs

        if source_crs_object is None:
            raise ValueError(
                f"Aquifer source layer has no CRS: {path}"
            )

        mapped_name = AQUIFER_NAME_MAP[path.name].strip()

        if mapped_name not in unit_lookup:
            raise ValueError(
                f"{path.name} has no logical aquifer unit."
            )

        source_crs = source_crs_object.to_string()

        source = source.copy()

        source, invalid_native_before, invalid_native_after = (
            repair_geometries(source)
        )

        if invalid_native_after:
            raise ValueError(
                f"{path.name} remains invalid after native repair."
            )

        feature_count = len(source)

        features = gpd.GeoDataFrame(
            {
                "storage_unit_id":
                    unit_lookup[mapped_name],
                "aquifer_name":
                    mapped_name,
                "source_feature_order":
                    range(1, feature_count + 1),
                "source_feature_count":
                    feature_count,
                "source_file":
                    path.name,
                "source_crs":
                    source_crs,
                "source_name":
                    source.get(
                        "NAME",
                        pd.Series(
                            None,
                            index=source.index,
                            dtype="object",
                        ),
                    ),
                "source_rec_id":
                    source.get(
                        "REC_ID",
                        pd.Series(
                            None,
                            index=source.index,
                            dtype="object",
                        ),
                    ),
                "source_theoretical_storage_mt":
                    pd.to_numeric(
                        first_existing_series(
                            source,
                            AQUIFER_FIELD_VARIANTS[
                                "source_theoretical_storage_mt"
                            ],
                        ),
                        errors="coerce",
                    ),
                "source_p10_storage_mt":
                    pd.to_numeric(
                        first_existing_series(
                            source,
                            AQUIFER_FIELD_VARIANTS[
                                "source_p10_storage_mt"
                            ],
                        ),
                        errors="coerce",
                    ),
                "source_p50_storage_mt":
                    pd.to_numeric(
                        first_existing_series(
                            source,
                            AQUIFER_FIELD_VARIANTS[
                                "source_p50_storage_mt"
                            ],
                        ),
                        errors="coerce",
                    ),
                "source_p90_storage_mt":
                    pd.to_numeric(
                        first_existing_series(
                            source,
                            AQUIFER_FIELD_VARIANTS[
                                "source_p90_storage_mt"
                            ],
                        ),
                        errors="coerce",
                    ),
                "source_co2_phase":
                    first_existing_series(
                        source,
                        AQUIFER_FIELD_VARIANTS[
                            "source_co2_phase"
                        ],
                    ),
                "source_shape_length":
                    pd.to_numeric(
                        first_existing_series(
                            source,
                            AQUIFER_FIELD_VARIANTS[
                                "source_shape_length"
                            ],
                        ),
                        errors="coerce",
                    ),
                "source_shape_area":
                    pd.to_numeric(
                        first_existing_series(
                            source,
                            AQUIFER_FIELD_VARIANTS[
                                "source_shape_area"
                            ],
                        ),
                        errors="coerce",
                    ),
            },
            geometry=source.geometry,
            crs=source_crs_object,
        )

        features["storage_feature_id"] = (
            features["storage_unit_id"]
            + "_f"
            + features["source_feature_order"]
            .astype("string")
            .str.zfill(3)
        )

        silver, invalid_projected_before, invalid_projected_after = (
            project_and_measure(features)
        )

        silver = silver[
            AQUIFER_FEATURE_COLUMNS
        ].copy()

        if silver["storage_feature_id"].duplicated().any():
            raise ValueError(
                f"{path.name} generated duplicate aquifer feature IDs."
            )

        frames.append(silver)

        qa_rows.append(
            {
                "source_file":
                    path.name,
                "aquifer_name":
                    mapped_name,
                "source_feature_count":
                    len(source),
                "source_crs":
                    source_crs,
                "invalid_native_before_repair":
                    invalid_native_before,
                "invalid_native_after_repair":
                    invalid_native_after,
                "invalid_projected_before_repair":
                    invalid_projected_before,
                "invalid_projected_after_repair":
                    invalid_projected_after,
                "read_warning_count":
                    len(warning_messages),
                "read_warnings":
                    " | ".join(warning_messages),
            }
        )

    combined = gpd.GeoDataFrame(
        pd.concat(
            frames,
            ignore_index=True,
        ),
        geometry="geometry",
        crs=TARGET_CRS,
    )

    if combined["storage_feature_id"].duplicated().any():
        raise ValueError(
            "Combined aquifer layer contains duplicate feature IDs."
        )

    logical_ids = set(
        aquifer_units["storage_unit_id"]
    )

    spatial_ids = set(
        combined["storage_unit_id"]
    )

    if logical_ids != spatial_ids:
        raise ValueError(
            "Aquifer logical-unit and spatial-feature identifiers "
            "do not reconcile exactly."
        )

    qa = (
        pd.DataFrame(qa_rows)
        .sort_values("source_file")
        .reset_index(drop=True)
    )

    return combined, qa


# =============================================================================
# Metadata and QA
# =============================================================================

def build_metadata_table(
    *,
    pool_units: pd.DataFrame,
    aquifer_units: pd.DataFrame,
    shapefile_inventory: pd.DataFrame,
) -> pd.DataFrame:
    """Build dataset-level provenance and interpretation metadata."""

    source_epsg_values = sorted(
        {
            str(int(value))
            for value in shapefile_inventory[
                "source_epsg"
            ].dropna()
        }
    )

    records = [
        (
            "title",
            "Northeast BC Geological Carbon Capture and Storage Atlas",
        ),
        (
            "who",
            (
                f"{CANCO2RE_SUBMISSION.creator_name}, "
                f"CanCO2Re Activity "
                f"{CANCO2RE_SUBMISSION.activity_code}"
            ),
        ),
        ("when", CREATED_DATE.isoformat()),
        ("submission_filename", SILVER_GPKG_PATH.name),
        (
            "activity_code",
            CANCO2RE_SUBMISSION.activity_code,
        ),
        (
            "creator_initials",
            CANCO2RE_SUBMISSION.creator_initials,
        ),
        ("dataset_id", DATASET_ID),
        ("data_class", DATA_CLASS),
        ("assessment_type", ASSESSMENT_TYPE),
        ("capacity_data", str(CAPACITY_DATA)),
        ("injectivity_status", INJECTIVITY_STATUS),
        ("source_title", SOURCE_TITLE),
        ("source_organization", SOURCE_ORGANIZATION),
        ("source_preparer", SOURCE_PREPARER),
        ("source_publication", SOURCE_PUBLICATION),
        ("source_year", str(SOURCE_YEAR)),
        ("source_url", SOURCE_PROJECT_URL),
        ("source_parent_url", SOURCE_PARENT_URL),
        (
            "what",
            "Harmonized Northeast British Columbia geological CO2 "
            "storage screening dataset containing depleted or "
            "near-depleted pools and saline aquifers with published "
            "storage-potential estimates."
        ),
        (
            "where",
            "Northeast British Columbia, Canada. Bronze spatial data "
            f"include source EPSG codes {', '.join(source_epsg_values)}; "
            f"Silver spatial layers use {TARGET_CRS}."
        ),
        (
            "how",
            "Pool classifications and logical pool attributes are "
            "derived from Appendix C and linked to the Appendix E "
            "master pool geometry using the published link code. "
            "Aquifer logical attributes and standardized storage "
            "estimates are derived from Appendix C and linked one-to-one "
            "to the 25 published aquifer shapefiles using the source-name "
            "mapping established during exploration. Multiple source "
            "geometries per logical storage object are preserved. "
            "Invalid source geometries are repaired where required and "
            f"all spatial layers are reprojected to {TARGET_CRS}."
        ),
        (
            "use_limitations",
            "Storage values are regional screening estimates and must not "
            "be interpreted as permitted injection capacity, demonstrated "
            "injectivity, project-ready capacity, or a substitute for "
            "site-specific geological characterization. Appendix C is "
            "used as the preferred aquifer tabular source because the "
            "published aquifer shapefiles contain schema variation and "
            "known source-quality anomalies."
        ),
        (
            "keywords",
            "carbon storage; CO2 storage; CCUS; geological storage; "
            "saline aquifer; depleted pool; British Columbia; "
            "Geoscience BC"
        ),
        ("silver_crs", TARGET_CRS),
        (
            "bronze_shapefile_count",
            str(len(shapefile_inventory)),
        ),
        (
            "pool_logical_unit_count",
            str(len(pool_units)),
        ),
        (
            "aquifer_logical_unit_count",
            str(len(aquifer_units)),
        ),
    ]

    return pd.DataFrame(
        records,
        columns=["key", "value"],
    )


def build_qa_table(
    *,
    pool_units: pd.DataFrame,
    pool_features: gpd.GeoDataFrame,
    pool_qa: dict[str, object],
    aquifer_units: pd.DataFrame,
    aquifer_features: gpd.GeoDataFrame,
    aquifer_source_qa: pd.DataFrame,
    pool_reconciliation: pd.DataFrame,
) -> pd.DataFrame:
    """Build dataset-level QA checks for the complete Silver artifact."""

    unmatched_pool_codes = int(
        pool_reconciliation[
            "unmatched_to_master"
        ].sum()
    )

    records = [
        (
            "pool_logical_unit_count",
            int(len(pool_units)),
        ),
        (
            "pool_spatial_feature_count",
            int(len(pool_features)),
        ),
        (
            "pool_multi_feature_unit_count",
            pool_qa["pool_multi_feature_unit_count"],
        ),
        (
            "pool_unmatched_link_code_count",
            unmatched_pool_codes,
        ),
        (
            "pool_invalid_native_before_repair",
            pool_qa[
                "pool_invalid_native_before_repair"
            ],
        ),
        (
            "pool_invalid_native_after_repair",
            pool_qa[
                "pool_invalid_native_after_repair"
            ],
        ),
        (
            "pool_invalid_projected_after_repair",
            pool_qa[
                "pool_invalid_projected_after_repair"
            ],
        ),
        (
            "aquifer_logical_unit_count",
            int(len(aquifer_units)),
        ),
        (
            "aquifer_spatial_feature_count",
            int(len(aquifer_features)),
        ),
        (
            "aquifer_multi_feature_unit_count",
            int(
                (
                    aquifer_units[
                        "source_feature_count"
                    ]
                    > 1
                ).sum()
            ),
        ),
        (
            "aquifer_zero_theoretical_anomaly_count",
            int(
                aquifer_units[
                    "source_zero_theoretical_anomaly"
                ].sum()
            ),
        ),
        (
            "aquifer_source_storage_mismatch_count",
            int(
                (
                    ~aquifer_units[
                        "source_storage_values_match_appendix_c"
                    ]
                ).sum()
            ),
        ),
        (
            "aquifer_invalid_native_before_repair",
            int(
                aquifer_source_qa[
                    "invalid_native_before_repair"
                ].sum()
            ),
        ),
        (
            "aquifer_invalid_native_after_repair",
            int(
                aquifer_source_qa[
                    "invalid_native_after_repair"
                ].sum()
            ),
        ),
        (
            "aquifer_invalid_projected_after_repair",
            int(
                aquifer_source_qa[
                    "invalid_projected_after_repair"
                ].sum()
            ),
        ),
        (
            "aquifer_read_warning_count",
            int(
                aquifer_source_qa[
                    "read_warning_count"
                ].sum()
            ),
        ),
        (
            "silver_crs",
            TARGET_CRS,
        ),
        (
            "pool_null_geometry_count",
            int(pool_features.geometry.isna().sum()),
        ),
        (
            "aquifer_null_geometry_count",
            int(aquifer_features.geometry.isna().sum()),
        ),
        (
            "pool_final_invalid_geometry_count",
            int((~pool_features.geometry.is_valid).sum()),
        ),
        (
            "aquifer_final_invalid_geometry_count",
            int((~aquifer_features.geometry.is_valid).sum()),
        ),
    ]

    return pd.DataFrame(
        records,
        columns=["check", "value"],
    )


# =============================================================================
# Field dictionaries
# =============================================================================

def build_field_dictionary(
    *,
    fields: list[str],
    definitions: dict[str, tuple[str, str, str, str]],
) -> pd.DataFrame:
    """Build one standardized field dictionary."""

    records = []

    for field in fields:
        if field == "geometry":
            continue

        definition, units, origin, notes = definitions.get(
            field,
            (
                field.replace("_", " ").capitalize(),
                "text",
                "harmonized",
                "",
            ),
        )

        records.append(
            {
                "field": field,
                "definition": definition,
                "units": units,
                "origin": origin,
                "notes": notes,
            }
        )

    return pd.DataFrame(records)


COMMON_DICTIONARY = {
    "storage_unit_id": (
        "Stable identifier for one logical storage object.",
        "identifier",
        "derived",
        "Logical identity is kept separate from individual spatial features.",
    ),
    "storage_feature_id": (
        "Stable identifier for one Silver spatial feature.",
        "identifier",
        "derived",
        "One logical storage unit may have more than one spatial feature.",
    ),
    "storage_unit_type": (
        "Broad geological storage-object type.",
        "text",
        "harmonized",
        "",
    ),
    "source_feature_order": (
        "Sequential feature number within one logical storage unit.",
        "integer",
        "derived",
        "",
    ),
    "source_feature_count": (
        "Number of source spatial features representing the logical storage unit.",
        "integer",
        "derived",
        "Storage capacities are not multiplied by this count.",
    ),
    "geometry_area_m2": (
        "Area calculated from the harmonized geometry.",
        "m^2",
        "derived spatial",
        f"Calculated in {TARGET_CRS}.",
    ),
    "geometry_area_ha": (
        "Area calculated from the harmonized geometry.",
        "ha",
        "derived spatial",
        "geometry_area_m2 divided by 10,000.",
    ),
    "geometry_perimeter_m": (
        "Boundary length calculated from the harmonized geometry.",
        "m",
        "derived spatial",
        f"Calculated in {TARGET_CRS}.",
    ),
    "source_dataset": (
        "Source dataset identifier.",
        "text",
        "provenance",
        "",
    ),
    "source_file": (
        "Bronze shapefile from which the spatial feature was derived.",
        "filename",
        "provenance",
        "",
    ),
    "source_crs": (
        "Coordinate reference system reported by the Bronze source layer.",
        "CRS",
        "provenance",
        "",
    ),
    "assessment_type": (
        "Broad analytical assessment represented by the dataset.",
        "text",
        "classification",
        "",
    ),
    "data_class": (
        "Broad standardized data class.",
        "text",
        "classification",
        "",
    ),
    "capacity_data": (
        "Whether quantitative storage-capacity data are represented.",
        "boolean",
        "classification",
        "",
    ),
}

POOL_UNIT_DICTIONARY = {
    **COMMON_DICTIONARY,
    "formation": (
        "Formation name propagated from Appendix E pool features when all "
        "non-null source formation names associated with the logical pool agree.",
        "text",
        "Appendix E",
        "Null when no formation is reported or when associated pool features "
        "contain conflicting formation names.",
    ),
    "pool_class": (
        "Appendix C screening class assigned to the pool.",
        "text",
        "Appendix C",
        "current_candidate, future_candidate, or co2_eor_candidate.",
    ),
    "pool_name": (
        "Published pool name.",
        "text",
        "Appendix C",
        "",
    ),
    "field_code": (
        "Published field code.",
        "code",
        "Appendix C",
        "",
    ),
    "pool_code": (
        "Published pool code.",
        "code",
        "Appendix C",
        "",
    ),
    "pool_sequence": (
        "Published pool sequence.",
        "identifier",
        "Appendix C",
        "",
    ),
    "pool_type": (
        "Published pool type.",
        "text",
        "Appendix C",
        "",
    ),
    "map_group": (
        "Published map group.",
        "text",
        "Appendix C",
        "",
    ),
    "well_count": (
        "Number of wells associated with the pool.",
        "count",
        "Appendix C",
        "",
    ),
    "initial_pressure_kpa": (
        "Initial pool pressure.",
        "kPa",
        "Appendix C",
        "",
    ),
    "temperature_c": (
        "Published pool temperature.",
        "degC",
        "Appendix C",
        "",
    ),
    "porosity_fraction": (
        "Published pool porosity.",
        "fraction",
        "Appendix C",
        "",
    ),
    "pool_datum_tvd_m": (
        "Pool datum true vertical depth.",
        "m",
        "Appendix C",
        "",
    ),
    "approx_pool_elevation_msl": (
        "Approximate pool elevation relative to mean sea level.",
        "m",
        "Appendix C",
        "",
    ),
    "co2_phase": (
        "Published CO2 phase classification.",
        "text",
        "Appendix C",
        "",
    ),
    "theoretical_storage_mt": (
        "Published theoretical CO2 storage potential.",
        "Mt CO2",
        "Appendix C",
        "",
    ),
    "effective_storage_mt": (
        "Published effective CO2 storage potential.",
        "Mt CO2",
        "Appendix C",
        "",
    ),
    "potentially_commingled": (
        "Published indicator that the pool may be commingled.",
        "boolean/text",
        "Appendix C",
        "",
    ),
    "recovery_factor": (
        "Published gas or oil recovery factor, depending on source worksheet.",
        "fraction",
        "Appendix C",
        "",
    ),
    "source_link_code": (
        "Published key linking Appendix C pool records to Appendix E geometry.",
        "identifier",
        "Appendix C / Appendix E",
        "",
    ),
    "source_sheet": (
        "Appendix C worksheet from which the logical pool was derived.",
        "text",
        "provenance",
        "",
    ),
}

POOL_FEATURE_DICTIONARY = {
    **COMMON_DICTIONARY,
    "source_link_code": (
        "Published pool linkage key.",
        "identifier",
        "Appendix E",
        "Corresponds to LINK_CODE in the master pool shapefile.",
    ),
    "source_pool_uid": (
        "Source pool unique identifier from the master shapefile.",
        "identifier",
        "Appendix E",
        "",
    ),
    "source_pool_name": (
        "Source-native pool name.",
        "text",
        "Appendix E",
        "",
    ),
    "source_formation_name": (
        "Source-native formation name.",
        "text",
        "Appendix E",
        "",
    ),
    "source_fluid_type": (
        "Source-native fluid type.",
        "text",
        "Appendix E",
        "",
    ),
    "source_theoretical_storage_mt": (
        "Raw theoretical storage value from the master pool shapefile.",
        "Mt CO2",
        "Appendix E",
        "Preserved separately from Appendix C logical-unit values.",
    ),
    "source_effective_storage_mt": (
        "Raw effective storage value from the master pool shapefile.",
        "Mt CO2",
        "Appendix E",
        "Preserved separately from Appendix C logical-unit values.",
    ),
    "source_co2_phase": (
        "Raw CO2 phase from the master pool shapefile.",
        "text",
        "Appendix E",
        "",
    ),
    "source_candidate_flag": (
        "Raw candidate flag from the master pool shapefile.",
        "source value",
        "Appendix E",
        "",
    ),
    "source_cdl_candidate_flag": (
        "Raw Canadian Discovery Ltd. candidate flag.",
        "source value",
        "Appendix E",
        "",
    ),
    "source_pool_area_ha": (
        "Raw pool area from the master pool shapefile.",
        "ha",
        "Appendix E",
        "",
    ),
}

AQUIFER_UNIT_DICTIONARY = {
    **COMMON_DICTIONARY,
    "formation": (
        "Published formation associated with the aquifer.",
        "text",
        "Appendix C",
        "",
    ),
    "aquifer_name": (
        "Published logical aquifer name.",
        "text",
        "Appendix C",
        "",
    ),
    "aquifer_type": (
        "Published storage-object type.",
        "text",
        "Appendix C",
        "",
    ),
    "thickness_range_m": (
        "Published aquifer thickness range.",
        "m",
        "Appendix C",
        "",
    ),
    "pressure_range_mpa": (
        "Published aquifer pressure range.",
        "MPa",
        "Appendix C",
        "",
    ),
    "temperature_range_c": (
        "Published aquifer temperature range.",
        "degC",
        "Appendix C",
        "",
    ),
    "porosity_range_pct": (
        "Published aquifer porosity range.",
        "percent",
        "Appendix C",
        "",
    ),
    "co2_phase": (
        "Published logical-aquifer CO2 phase classification.",
        "text",
        "Appendix C",
        "",
    ),
    "p10_effective_storage_mt": (
        "P10 effective storage potential at 0.5 percent efficiency.",
        "Mt CO2",
        "Appendix C",
        "",
    ),
    "p50_effective_storage_mt": (
        "P50 effective storage potential at 2 percent efficiency.",
        "Mt CO2",
        "Appendix C",
        "",
    ),
    "p90_effective_storage_mt": (
        "P90 effective storage potential at 5.4 percent efficiency.",
        "Mt CO2",
        "Appendix C",
        "",
    ),
    "theoretical_storage_mt": (
        "Standardized theoretical storage potential derived from Appendix C P50.",
        "Mt CO2",
        "derived from Appendix C",
        "Calculated as P50 / 0.02.",
    ),
    "theoretical_storage_method": (
        "Method used to obtain standardized theoretical storage.",
        "text",
        "derived",
        "",
    ),
    "source_shapefile": (
        "Published aquifer shapefile associated one-to-one with the logical aquifer.",
        "filename",
        "provenance",
        "",
    ),
    "source_theoretical_storage_mt": (
        "Raw theoretical-storage value from the aquifer shapefile.",
        "Mt CO2",
        "Appendix E",
        "A source value of zero is flagged when effective storage is nonzero.",
    ),
    "source_p10_storage_mt": (
        "Raw P10 effective-storage value from the aquifer shapefile.",
        "Mt CO2",
        "Appendix E",
        "",
    ),
    "source_p50_storage_mt": (
        "Raw P50 effective-storage value from the aquifer shapefile.",
        "Mt CO2",
        "Appendix E",
        "",
    ),
    "source_p90_storage_mt": (
        "Raw P90 effective-storage value from the aquifer shapefile.",
        "Mt CO2",
        "Appendix E",
        "",
    ),
    "source_co2_phases": (
        "Distinct source-native CO2 phases represented across aquifer features.",
        "text",
        "Appendix E",
        "",
    ),
    "source_zero_theoretical_anomaly": (
        "Flags zero source theoretical storage with nonzero effective storage.",
        "boolean",
        "QA derived",
        "Known source anomaly identified during exploratory reconciliation.",
    ),
    "source_storage_values_match_appendix_c": (
        "Whether SHP P10/P50/P90 values match Appendix C within 0.11 Mt.",
        "boolean",
        "QA derived",
        "",
    ),
    "source_sheet": (
        "Appendix C worksheet from which the logical aquifer was derived.",
        "text",
        "provenance",
        "",
    ),
}

AQUIFER_FEATURE_DICTIONARY = {
    **COMMON_DICTIONARY,
    "aquifer_name": (
        "Logical aquifer name linked to this spatial feature.",
        "text",
        "harmonized",
        "",
    ),
    "source_name": (
        "Optional source NAME field where supplied.",
        "text",
        "Appendix E",
        "Present only in a subset of aquifer shapefiles.",
    ),
    "source_rec_id": (
        "Optional source REC_ID field where supplied.",
        "identifier",
        "Appendix E",
        "Present only in one source schema.",
    ),
    "source_theoretical_storage_mt": (
        "Raw feature-level theoretical storage value.",
        "Mt CO2",
        "Appendix E",
        "Repeated source values are not additive across spatial components.",
    ),
    "source_p10_storage_mt": (
        "Raw feature-level P10 effective storage value.",
        "Mt CO2",
        "Appendix E",
        "Repeated source values are not additive across spatial components.",
    ),
    "source_p50_storage_mt": (
        "Raw feature-level P50 effective storage value.",
        "Mt CO2",
        "Appendix E",
        "Repeated source values are not additive across spatial components.",
    ),
    "source_p90_storage_mt": (
        "Raw feature-level P90 effective storage value.",
        "Mt CO2",
        "Appendix E",
        "Repeated source values are not additive across spatial components.",
    ),
    "source_co2_phase": (
        "Raw feature-level CO2 phase.",
        "text",
        "Appendix E",
        "Can vary between spatial components of one logical aquifer.",
    ),
    "source_shape_length": (
        "Raw provider geometry-length attribute where supplied.",
        "source units",
        "Appendix E",
        "",
    ),
    "source_shape_area": (
        "Raw provider geometry-area attribute where supplied.",
        "source units",
        "Appendix E",
        "",
    ),
}


def build_field_dictionaries() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    """Build all logical-unit and spatial-feature field dictionaries."""

    return (
        build_field_dictionary(
            fields=POOL_UNIT_COLUMNS,
            definitions=POOL_UNIT_DICTIONARY,
        ),
        build_field_dictionary(
            fields=POOL_FEATURE_COLUMNS,
            definitions=POOL_FEATURE_DICTIONARY,
        ),
        build_field_dictionary(
            fields=AQUIFER_UNIT_COLUMNS,
            definitions=AQUIFER_UNIT_DICTIONARY,
        ),
        build_field_dictionary(
            fields=AQUIFER_FEATURE_COLUMNS,
            definitions=AQUIFER_FEATURE_DICTIONARY,
        ),
    )


def combine_field_dictionaries(
    *,
    pool_units_dictionary: pd.DataFrame,
    pool_features_dictionary: pd.DataFrame,
    aquifer_units_dictionary: pd.DataFrame,
    aquifer_features_dictionary: pd.DataFrame,
) -> pd.DataFrame:
    """Combine table-specific dictionaries into one standardized sidecar."""

    frames = []

    for table_name, dictionary in (
        ("pool_units", pool_units_dictionary),
        ("pool_features", pool_features_dictionary),
        ("aquifer_units", aquifer_units_dictionary),
        ("aquifer_features", aquifer_features_dictionary),
    ):
        table_dictionary = dictionary.copy()
        table_dictionary.insert(
            0,
            "table_name",
            table_name,
        )
        frames.append(table_dictionary)

    return pd.concat(
        frames,
        ignore_index=True,
    )


# =============================================================================
# Persisted-artifact contract
# =============================================================================

# Keep the CANCO2Re package contract explicit in the dataset harmonizer.
# Shared code validates this contract but does not define dataset-specific
# layer or metadata-table names.
EXPECTED_GPKG_CONTENTS = {
    "pool_features": "features",
    "aquifer_features": "features",
    "pool_units": "attributes",
    "aquifer_units": "attributes",
    "metadata_gbc_ne_atlas": "attributes",
    "qa_gbc_ne_atlas": "attributes",
}


# =============================================================================
# Export
# =============================================================================

def export_outputs(
    *,
    pool_units: pd.DataFrame,
    pool_features: gpd.GeoDataFrame,
    aquifer_units: pd.DataFrame,
    aquifer_features: gpd.GeoDataFrame,
    metadata: pd.DataFrame,
    qa: pd.DataFrame,
    schema_inventory: pd.DataFrame,
    field_dictionary: pd.DataFrame,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Write and validate the complete Northeast BC Silver package."""

    PROCESSED_GBC_NE_ATLAS.mkdir(
        parents=True,
        exist_ok=True,
    )

    if SILVER_GPKG_PATH.exists():
        SILVER_GPKG_PATH.unlink()

    pool_features.to_file(
        SILVER_GPKG_PATH,
        layer="pool_features",
        driver="GPKG",
    )

    aquifer_features.to_file(
        SILVER_GPKG_PATH,
        layer="aquifer_features",
        driver="GPKG",
    )

    # CANCO2Re package requirement:
    # logical-unit, metadata, and QA tables are stored inside the GeoPackage
    # and explicitly registered in gpkg_contents as attribute tables.
    with sqlite3.connect(
        SILVER_GPKG_PATH
    ) as conn:
        write_registered_attribute_table(
            conn,
            dataframe=pool_units,
            table_name="pool_units",
            description=(
                "One logical record per selected depleted or "
                "near-depleted pool."
            ),
        )

        write_registered_attribute_table(
            conn,
            dataframe=aquifer_units,
            table_name="aquifer_units",
            description=(
                "One logical record per saline aquifer."
            ),
        )

        write_registered_attribute_table(
            conn,
            dataframe=metadata,
            table_name="metadata_gbc_ne_atlas",
            description=(
                "Dataset-level provenance, processing, and use metadata."
            ),
        )

        write_registered_attribute_table(
            conn,
            dataframe=qa,
            table_name="qa_gbc_ne_atlas",
            description=(
                "Dataset-level quality-assurance and validation summary."
            ),
        )

    # Standardized CANCO2Re Silver sidecars. Metadata and QA remain embedded
    # in the GeoPackage as authoritative internal attribute tables; these CSVs
    # provide convenient human-readable package companions.
    schema_inventory.to_csv(
        SCHEMA_INVENTORY_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    metadata.to_csv(
        SOURCE_METADATA_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    qa.to_csv(
        QA_SUMMARY_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    field_dictionary.to_csv(
        FIELD_DICTIONARY_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    final_pool_features = validate_written_spatial_layer(
        gpkg_path=SILVER_GPKG_PATH,
        layer_name="pool_features",
        expected=pool_features,
        unique_id_field="storage_feature_id",
        target_crs=TARGET_CRS,
    )

    final_aquifer_features = validate_written_spatial_layer(
        gpkg_path=SILVER_GPKG_PATH,
        layer_name="aquifer_features",
        expected=aquifer_features,
        unique_id_field="storage_feature_id",
        target_crs=TARGET_CRS,
    )

    final_aquifer_features = validate_written_spatial_layer(
    gpkg_path=SILVER_GPKG_PATH,
    layer_name="aquifer_features",
    expected=aquifer_features,
    unique_id_field="storage_feature_id",
    target_crs=TARGET_CRS,
)

    for column in ["source_name", "source_rec_id"]:
        if column in final_aquifer_features.columns:
            literal_na = (
                final_aquifer_features[column]
                .eq("<NA>")
                .fillna(False)
            )

            if literal_na.any():
                raise ValueError(
                    f"Persisted aquifer_features.{column} contains "
                    f"{int(literal_na.sum()):,} literal '<NA>' value(s)."
                )

    validate_registered_tables(
        gpkg_path=SILVER_GPKG_PATH,
        expected=EXPECTED_GPKG_CONTENTS,
    )

    print("\nSilver outputs")
    print("--------------")
    print(f"GeoPackage:       {SILVER_GPKG_PATH}")
    print(f"Source schema:    {SCHEMA_INVENTORY_PATH}")
    print(f"Source metadata:  {SOURCE_METADATA_PATH}")
    print(f"QA summary:       {QA_SUMMARY_PATH}")
    print(f"Field dictionary: {FIELD_DICTIONARY_PATH}")

    return (
        final_pool_features,
        final_aquifer_features,
    )


# =============================================================================
# Inspection workflow
# =============================================================================

def run_inspection() -> None:
    """Inspect Bronze products and export reproducible source inventories."""

    PROCESSED_GBC_NE_ATLAS.mkdir(
        parents=True,
        exist_ok=True,
    )
    INSPECTION_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    shapefiles = discover_shapefiles()

    print(
        f"Discovered {len(shapefiles):,} Appendix E shapefiles."
    )

    shapefile_inventory = build_shapefile_inventory(
        shapefiles
    )
    workbook_inventory = inspect_workbook()
    pool_reconciliation = reconcile_pool_sources(
        shapefiles
    )

    shapefile_inventory.to_csv(
        SCHEMA_INVENTORY_PATH,
        index=False,
        encoding="utf-8-sig",
    )
    workbook_inventory.to_csv(
        WORKBOOK_INVENTORY_PATH,
        index=False,
        encoding="utf-8-sig",
    )
    pool_reconciliation.to_csv(
        POOL_RECONCILIATION_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    print(f"Shapefile inventory: {SCHEMA_INVENTORY_PATH}")
    print(f"Workbook inventory:  {WORKBOOK_INVENTORY_PATH}")
    print(f"Pool reconciliation: {POOL_RECONCILIATION_PATH}")

    print("\nInspection summary")
    print("------------------")
    print(
        f"Shapefiles:      "
        f"{len(shapefile_inventory):,}"
    )
    print(
        f"Workbook sheets: "
        f"{len(workbook_inventory):,}"
    )
    print(
        "Unique CRS identities: "
        f"{shapefile_inventory['source_epsg'].nunique(dropna=True):,}"
    )

    print("\nSource-layer classes")
    print("--------------------")

    class_counts = (
        shapefile_inventory[
            "source_class"
        ]
        .value_counts()
        .sort_index()
    )

    for source_class, count in class_counts.items():
        print(
            f"{source_class:<30} {count:>3}"
        )

    print("\nPool reconciliation")
    print("-------------------")

    for _, row in pool_reconciliation.iterrows():
        print(
            f"{row['source_name']}: "
            f"{row['unique_link_codes']:,} unique codes, "
            f"{row['unmatched_to_master']:,} unmatched"
        )


# =============================================================================
# Complete harmonization workflow
# =============================================================================

def run_harmonization(
    *,
    inspect_only: bool = False,
) -> None:
    """Run source inspection or the complete Northeast BC Silver build."""

    if inspect_only:
        run_inspection()
        return

    shapefiles = discover_shapefiles()

    print("Northeast BC storage atlas harmonization")
    print("---------------------------------------")
    print(f"Source root: {APPENDIX_E_ROOT}")
    print(f"Shapefiles: {len(shapefiles):,}")
    print(f"Target CRS: {TARGET_CRS}\n")

    shapefile_inventory = build_shapefile_inventory(
        shapefiles
    )

    pool_reconciliation = reconcile_pool_sources(
        shapefiles
    )

    PROCESSED_GBC_NE_ATLAS.mkdir(
        parents=True,
        exist_ok=True,
    )

    if inspect_only:
        run_inspection()
        return

    pool_units = build_pool_units()

    pool_features, pool_qa = build_pool_features(
        shapefiles,
        pool_units,
    )

    pool_units = propagate_pool_formations(
        pool_units,
        pool_features,
    )

    aquifer_paths = find_aquifer_layers(
        shapefiles
    )

    aquifer_units = build_aquifer_units(
        aquifer_paths
    )

    aquifer_features, aquifer_source_qa = (
        build_aquifer_features(
            aquifer_paths,
            aquifer_units,
        )
    )

    metadata = build_metadata_table(
        pool_units=pool_units,
        aquifer_units=aquifer_units,
        shapefile_inventory=shapefile_inventory,
    )

    qa = build_qa_table(
        pool_units=pool_units,
        pool_features=pool_features,
        pool_qa=pool_qa,
        aquifer_units=aquifer_units,
        aquifer_features=aquifer_features,
        aquifer_source_qa=aquifer_source_qa,
        pool_reconciliation=pool_reconciliation,
    )

    (
        pool_units_dictionary,
        pool_features_dictionary,
        aquifer_units_dictionary,
        aquifer_features_dictionary,
    ) = build_field_dictionaries()

    field_dictionary = combine_field_dictionaries(
        pool_units_dictionary=pool_units_dictionary,
        pool_features_dictionary=pool_features_dictionary,
        aquifer_units_dictionary=aquifer_units_dictionary,
        aquifer_features_dictionary=aquifer_features_dictionary,
    )

    (
        final_pool_features,
        final_aquifer_features,
    ) = export_outputs(
        pool_units=pool_units,
        pool_features=pool_features,
        aquifer_units=aquifer_units,
        aquifer_features=aquifer_features,
        metadata=metadata,
        qa=qa,
        schema_inventory=shapefile_inventory,
        field_dictionary=field_dictionary,
    )

    print("\nHarmonization summary")
    print("---------------------")
    print(
        f"Pool logical units:     "
        f"{len(pool_units):,}"
    )
    print(
        f"Pool spatial features:  "
        f"{len(final_pool_features):,}"
    )
    print(
        f"Aquifer logical units:  "
        f"{len(aquifer_units):,}"
    )
    print(
        f"Aquifer spatial features:"
        f" {len(final_aquifer_features):,}"
    )
    print(
        "Aquifer zero-theoretical anomalies: "
        f"{int(aquifer_units['source_zero_theoretical_anomaly'].sum()):,}"
    )
    print(
        "Aquifer SHP/Appendix C storage mismatches: "
        f"{int((~aquifer_units['source_storage_values_match_appendix_c']).sum()):,}"
    )
    print(f"CRS:                    {TARGET_CRS}")
    print(
        "Final invalid geometries: "
        f"{int((~final_pool_features.geometry.is_valid).sum()) + int((~final_aquifer_features.geometry.is_valid).sum()):,}"
    )


# =============================================================================
# CLI
# =============================================================================

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Inspect or harmonize the Northeast BC Geological Carbon "
            "Capture and Storage Atlas."
        )
    )

    parser.add_argument(
        "--inspect-only",
        action="store_true",
        help=(
            "Inspect Appendix C and Appendix E and export source "
            "inventories without building the Silver GeoPackage."
        ),
    )

    return parser.parse_args()


def main() -> None:
    """Run the Northeast BC storage-atlas harmonization workflow."""

    args = parse_args()

    run_harmonization(
        inspect_only=args.inspect_only,
    )


if __name__ == "__main__":
    main()
