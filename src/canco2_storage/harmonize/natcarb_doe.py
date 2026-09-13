"""
Harmonize the DOE/NETL NATCARB All Data v1502 geological storage dataset.

This module converts the validated NATCARB v1502 Bronze File Geodatabase
into a standardized Silver GeoPackage suitable for cross-dataset comparison,
querying, and downstream national geological-storage integration.

The core Silver product preserves five geological storage representations:

- saline resource 10 km cells,
- saline resource polygons,
- coal resource 10 km cells,
- coal resource polygons,
- oil and gas storage-resource polygons.

The ten provider domain tables are also retained as non-spatial reference
tables.

This module:

- loads validated NATCARB FileGDB layers,
- validates required source fields,
- preserves source FileGDB feature identifiers,
- constructs stable CANCO2-Storage feature identifiers,
- standardizes source field names,
- converts selected physical units to canonical SI representations,
- preserves assessed, overlap, duplicate, and P50-method semantics,
- repairs geometries where required,
- reprojects spatial layers to the repository Silver CRS,
- calculates standardized geometry metrics,
- builds intrinsic source and QA metadata tables,
- writes the harmonized GeoPackage and supporting inspection tables.

It does not:

- remove provider-flagged duplicate records,
- aggregate overlapping resources,
- infer missing geological properties,
- merge 10 km and polygon representations,
- infer parent-child relationships between resource grids and polygons,
- clip the dataset to Canada,
- calculate storage capacity where the provider did not provide one,
- calculate injectivity,
- render human-readable README documentation,
- or construct the final unified Canadian geological-storage ontology.
"""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import geopandas as gpd
import pandas as pd
import pyogrio

from canco2_storage.harmonize.common import (
    SILVER_CRS,
    project_and_measure,
    validate_registered_tables,
    validate_target_crs,
    validate_written_spatial_layer,
    write_registered_attribute_table,
)
from canco2_storage.metadata.common import (
    CANCO2RE_SUBMISSION,
    build_submission_stem,
)
from canco2_storage.paths import find_project_root


# =============================================================================
# Project paths
# =============================================================================

PROJECT_ROOT = find_project_root()

RAW_NATCARB = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "natcarb_doe"
    / "source"
    / "NATCARB_v1502.gdb"
)

PROCESSED_NATCARB = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "natcarb_doe"
)

INSPECTION_DIR = PROCESSED_NATCARB / "inspection"

# CanCO2Re researcher-submission naming convention:
# YYYYMMDD_ActivityCode_DataType_CreatorInitials
DATA_TYPE = "NATCARBStorage"
CREATED_DATE = date.today()

SUBMISSION_STEM = build_submission_stem(
    data_type=DATA_TYPE,
    created_date=CREATED_DATE,
)

OUTPUT_GPKG = (
    PROCESSED_NATCARB
    / f"{SUBMISSION_STEM}.gpkg"
)


def build_companion_filename(
    suffix: str,
    extension: str,
) -> str:
    """Build one CanCO2Re companion filename for the current run."""

    return (
        f"{CREATED_DATE:%Y%m%d}_"
        f"{CANCO2RE_SUBMISSION.activity_code}_"
        f"{DATA_TYPE}{suffix}_"
        f"{CANCO2RE_SUBMISSION.creator_initials}."
        f"{extension}"
    )


SOURCE_SCHEMA_PATH = (
    PROCESSED_NATCARB
    / build_companion_filename(
        "SourceSchema",
        "csv",
    )
)

SOURCE_METADATA_PATH = (
    PROCESSED_NATCARB
    / build_companion_filename(
        "SourceMetadata",
        "csv",
    )
)

QA_SUMMARY_PATH = (
    PROCESSED_NATCARB
    / build_companion_filename(
        "QASummary",
        "csv",
    )
)

FIELD_DICTIONARY_PATH = (
    PROCESSED_NATCARB
    / build_companion_filename(
        "FieldDictionary",
        "csv",
    )
)

LAYER_INVENTORY_PATH = (
    INSPECTION_DIR
    / build_companion_filename(
        "LayerInventory",
        "csv",
    )
)

CAPACITY_QA_PATH = (
    INSPECTION_DIR
    / build_companion_filename(
        "CapacityQA",
        "csv",
    )
)


# =============================================================================
# Repository conventions
# =============================================================================

DATASET_ID = "natcarb_doe"
SOURCE_VERSION = "v1502"
SOURCE_ORGANIZATION = (
    "U.S. Department of Energy, National Energy Technology Laboratory"
)
SOURCE_TITLE = "NATCARB All Data v1502"
SOURCE_PUBLICATION_DATE = "2015-05-14"
SOURCE_GEOGRAPHIC_EXTENT = "United States and parts of Canada"

ASSESSMENT_TYPE = "quantitative_geological_storage_resource"
DATA_CLASS = "geological_storage_capacity"
INJECTIVITY_STATUS = "not_quantitatively_assessed"

METADATA_TABLE = "metadata_natcarb_doe"
QA_TABLE = "qa_natcarb_doe"

# =============================================================================
# Unit conversion constants
# =============================================================================

FT_TO_M = 0.3048
PSI_TO_MPA = 0.006894757293168361


# =============================================================================
# Layer specification
# =============================================================================


LayerKind = Literal[
    "saline",
    "coal",
    "oil_gas",
]

Representation = Literal[
    "resource_grid_cell",
    "resource_extent",
    "storage_resource",
]


@dataclass(frozen=True)
class LayerSpec:
    """Definition of one NATCARB geological source layer."""

    source_layer: str
    output_layer: str
    id_prefix: str

    storage_type: LayerKind
    representation: Representation

    has_capacity: bool
    has_resource_area: bool
    has_reservoir_properties: bool

    required_fields: tuple[str, ...]


COMMON_RESOURCE_FIELDS = (
    "PARTNERSHIP",
    "ASSESSED",
    "OVERLAP",
    "DUPLICATE",
    "CYCLE_OF_LAST_UPDATE",
)

GRID_CAPACITY_FIELDS = (
    "COL_ROW",
    "RESOURCE_NAME",
    "VOL_LOW",
    "VOL_MED",
    "VOL_HIGH",
    "RSC_AREA_CELL",
)

RESERVOIR_PROPERTY_FIELDS = (
    "DEPTH_FT",
    "THICKNESS_FT",
)

SALINE_PROPERTY_FIELDS = (
    "SALINITY_TDS",
    "PRESSURE_PSI",
    "TEMPERATURE_F",
    "POROSITY_PCT",
    "PERMEABILITY_mD",
)

LAYER_SPECS = (
    LayerSpec(
        source_layer="NATCARB_Saline_10K_v1502",
        output_layer="saline_resource_cells",
        id_prefix="natcarb:saline_cell",
        storage_type="saline",
        representation="resource_grid_cell",
        has_capacity=True,
        has_resource_area=True,
        has_reservoir_properties=True,
        required_fields=(
            *COMMON_RESOURCE_FIELDS,
            *GRID_CAPACITY_FIELDS,
            "ARRA_PROJECT",
            "BASIN_NAME",
            "MED_CALCED",
            *RESERVOIR_PROPERTY_FIELDS,
            *SALINE_PROPERTY_FIELDS,
        ),
    ),
    LayerSpec(
        source_layer="NATCARB_Saline_Poly_v1502",
        output_layer="saline_resource_areas",
        id_prefix="natcarb:saline_area",
        storage_type="saline",
        representation="resource_extent",
        has_capacity=False,
        has_resource_area=False,
        has_reservoir_properties=False,
        required_fields=(
            *COMMON_RESOURCE_FIELDS,
            "ARRA_PROJECT",
            "RESOURCE_NAME",
            "BASIN_NAME",
        ),
    ),
    LayerSpec(
        source_layer="NATCARB_Coal_10K_v1502",
        output_layer="coal_resource_cells",
        id_prefix="natcarb:coal_cell",
        storage_type="coal",
        representation="resource_grid_cell",
        has_capacity=True,
        has_resource_area=True,
        has_reservoir_properties=True,
        required_fields=(
            *COMMON_RESOURCE_FIELDS,
            *GRID_CAPACITY_FIELDS,
            "ARRA_PROJECT",
            "MED_CALCED",
            *RESERVOIR_PROPERTY_FIELDS,
        ),
    ),
    LayerSpec(
        source_layer="NATCARB_Coal_Poly_v1502",
        output_layer="coal_resource_areas",
        id_prefix="natcarb:coal_area",
        storage_type="coal",
        representation="resource_extent",
        has_capacity=False,
        has_resource_area=False,
        has_reservoir_properties=False,
        required_fields=(
            *COMMON_RESOURCE_FIELDS,
            "ARRA_PROJECT",
            "RESOURCE_NAME",
        ),
    ),
    LayerSpec(
        source_layer="NATCARB_OilGas_v1502",
        output_layer="oil_gas_resources",
        id_prefix="natcarb:oilgas",
        storage_type="oil_gas",
        representation="storage_resource",
        has_capacity=True,
        has_resource_area=False,
        has_reservoir_properties=True,
        required_fields=(
            "PARTNERSHIP",
            "FIELD_NAME",
            "TOTAL_FIELD_AREA",
            "FIELD_TYPE",
            "RESERVOIR_NUM",
            "RESERVOIR_NAME",
            "STATE_SRC",
            "VOL_LOW",
            "VOL_MED",
            "VOL_HIGH",
            "DEPTH_FT",
            "THICKNESS_FT",
            "SALINITY_TDS",
            "PRESSURE_PSI",
            "TEMPERATURE_F",
            "POROSITY_PCT",
            "PERMEABILITY_mD",
            "ASSESSED",
            "OVERLAP",
            "DUPLICATE",
            "MED_CALCED",
            "CYCLE_OF_LAST_UPDATE",
        ),
    ),
)


# =============================================================================
# Domain tables
# =============================================================================

DOMAIN_TABLES = {
    "Domain_State": "domain_state",
    "Domain_Fuel": "domain_fuel",
    "Domain_Overlap": "domain_overlap",
    "Domain_Duplicate": "domain_duplicate",
    "Domain_ARRA": "domain_arra",
    "Domain_Source_Types": "domain_source_types",
    "Domain_Med_Calced": "domain_med_calced",
    "Domain_Partnership": "domain_partnership",
    "Domain_Oil_Gas": "domain_oil_gas",
    "Domain_Assessed": "domain_assessed",
}

DOMAIN_DESCRIPTIONS = {
    "domain_state": "NATCARB state and province code lookup.",
    "domain_fuel": "NATCARB stationary-source fuel lookup.",
    "domain_overlap": "NATCARB resource overlap flag definitions.",
    "domain_duplicate": "NATCARB duplicate-resource flag definitions.",
    "domain_arra": "NATCARB ARRA project-code lookup.",
    "domain_source_types": "NATCARB stationary-source type lookup.",
    "domain_med_calced": "NATCARB medium-capacity calculation flag definitions.",
    "domain_partnership": "NATCARB Regional Carbon Sequestration Partnership lookup.",
    "domain_oil_gas": "NATCARB oil/gas field-type lookup.",
    "domain_assessed": "NATCARB storage-resource assessment flag definitions.",
}


# =============================================================================
# Harmonization result
# =============================================================================


@dataclass(frozen=True)
class NATCARBHarmonizationResult:
    """Outputs from the NATCARB Silver harmonization workflow."""

    output_gpkg: Path
    feature_layers: tuple[str, ...]
    domain_tables: tuple[str, ...]

    qa_summary_path: Path
    field_dictionary_path: Path
    source_metadata_path: Path
    source_schema_path: Path
    layer_inventory_path: Path
    capacity_qa_path: Path


# =============================================================================
# Source loading and validation
# =============================================================================


def validate_source_gdb(gdb_path: Path) -> None:
    """Validate the configured NATCARB FileGDB path."""

    if not gdb_path.is_dir():
        raise FileNotFoundError(
            f"NATCARB FileGDB not found: {gdb_path}"
        )


def validate_required_fields(
    data: pd.DataFrame,
    required_fields: tuple[str, ...],
    layer_name: str,
) -> None:
    """Validate required source fields for one geological layer."""

    missing = sorted(
        set(required_fields) - set(data.columns)
    )

    if missing:
        raise ValueError(
            f"{layer_name} is missing required source fields: {missing}"
        )


def load_source_layer(
    gdb_path: Path,
    spec: LayerSpec,
) -> gpd.GeoDataFrame:
    """Load one FileGDB layer while preserving its provider feature ID."""

    data = pyogrio.read_dataframe(
        gdb_path,
        layer=spec.source_layer,
        fid_as_index=True,
    )

    if data.empty:
        raise ValueError(
            f"NATCARB layer is empty: {spec.source_layer}"
        )

    if data.crs is None:
        raise ValueError(
            f"NATCARB layer has no defined CRS: {spec.source_layer}"
        )

    data = data.reset_index()

    fid_column = data.columns[0]

    if fid_column != "source_fid":
        data = data.rename(
            columns={fid_column: "source_fid"}
        )

    if data["source_fid"].duplicated().any():
        raise ValueError(
            f"Duplicate provider feature IDs found in {spec.source_layer}."
        )

    validate_required_fields(
        data=data,
        required_fields=spec.required_fields,
        layer_name=spec.source_layer,
    )

    return gpd.GeoDataFrame(
        data,
        geometry="geometry",
        crs=data.crs,
    )


def load_domain_table(
    gdb_path: Path,
    source_table: str,
) -> pd.DataFrame:
    """Load one non-spatial NATCARB FileGDB domain table."""

    table = pyogrio.read_dataframe(
        gdb_path,
        layer=source_table,
    )

    if table.empty:
        raise ValueError(
            f"NATCARB domain table is empty: {source_table}"
        )

    if "geometry" in table.columns:
        table = table.drop(columns="geometry")

    return pd.DataFrame(table)


# =============================================================================
# Generic cleaning helpers
# =============================================================================


def numeric(
    series: pd.Series,
) -> pd.Series:
    """Convert a source column to nullable numeric values."""

    return pd.to_numeric(
        series,
        errors="coerce",
    )


def nullable_boolean_flag(
    series: pd.Series,
    column_name: str,
) -> pd.Series:
    """Convert NATCARB 0/1 flags to nullable Boolean values."""

    values = numeric(series)

    invalid = (
        values.notna()
        & ~values.isin([0, 1])
    )

    if invalid.any():
        unexpected = sorted(
            values.loc[invalid].unique().tolist()
        )
        raise ValueError(
            f"{column_name} contains values outside 0/1: "
            f"{unexpected}"
        )

    return values.map(
        {
            0: False,
            1: True,
        }
    ).astype("boolean")


def clean_text(
    series: pd.Series,
) -> pd.Series:
    """Normalize whitespace while preserving null values."""

    output = series.astype("string").str.strip()

    null_tokens = output.isin(
        [
            "",
            "<Null>",
            "NULL",
        ]
    )

    return output.mask(null_tokens, pd.NA)


# =============================================================================
# Provider semantics
# =============================================================================


def build_p50_method(
    series: pd.Series,
) -> pd.Series:
    """Translate MED_CALCED into explicit P50 provenance."""

    values = numeric(series)

    invalid = (
        values.notna()
        & ~values.isin([0, 1])
    )

    if invalid.any():
        raise ValueError(
            "MED_CALCED contains values outside the documented 0/1 domain."
        )

    return values.map(
        {
            0: "provider",
            1: "natural_log_mean",
        }
    ).astype("string")


def normalize_field_type(
    series: pd.Series,
) -> pd.Series:
    """Normalize the observed NATCARB oil/gas field-type values."""

    values = clean_text(series).str.upper()

    allowed = {
        "OIL",
        "GAS",
        "OIL & GAS",
        "UNDETERMINED",
        "STORAGE",
    }

    invalid = sorted(
        set(values.dropna().unique())
        - allowed
    )

    if invalid:
        raise ValueError(
            f"Unexpected NATCARB FIELD_TYPE values: {invalid}"
        )

    return values


# =============================================================================
# Unit conversions
# =============================================================================


def fahrenheit_to_celsius(
    series: pd.Series,
) -> pd.Series:
    """Convert degrees Fahrenheit to degrees Celsius."""

    values = numeric(series)

    return (values - 32.0) * (5.0 / 9.0)


def percent_to_fraction(
    series: pd.Series,
) -> pd.Series:
    """Convert percentage values to fractions."""

    return numeric(series) / 100.0


# =============================================================================
# Stable identifiers
# =============================================================================


def build_natcarb_id(
    source_fid: pd.Series,
    prefix: str,
) -> pd.Series:
    """Construct a stable namespaced Silver identifier."""

    if source_fid.isna().any():
        raise ValueError(
            f"Cannot build {prefix} IDs from null source feature IDs."
        )

    ids = (
        prefix
        + ":"
        + source_fid.astype("int64").astype(str)
    )

    if ids.duplicated().any():
        raise ValueError(
            f"Generated duplicate NATCARB IDs for prefix {prefix!r}."
        )

    return ids


# =============================================================================
# Shared resource harmonization
# =============================================================================


def add_common_resource_fields(
    output: gpd.GeoDataFrame,
    source: gpd.GeoDataFrame,
    spec: LayerSpec,
) -> None:
    """Populate common geological-storage provenance and status fields."""

    output["natcarb_id"] = build_natcarb_id(
        source["source_fid"],
        spec.id_prefix,
    )

    output["source_fid"] = source["source_fid"].astype(
        "int64"
    )

    output["storage_type"] = spec.storage_type
    output["representation"] = spec.representation
    output["assessment_type"] = ASSESSMENT_TYPE
    output["data_class"] = DATA_CLASS
    output["capacity_data"] = spec.has_capacity
    output["injectivity_status"] = INJECTIVITY_STATUS

    output["partnership"] = clean_text(
        source["PARTNERSHIP"]
    )

    output["assessed"] = nullable_boolean_flag(
        source["ASSESSED"],
        "ASSESSED",
    )

    output["overlap"] = nullable_boolean_flag(
        source["OVERLAP"],
        "OVERLAP",
    )

    output["duplicate"] = nullable_boolean_flag(
        source["DUPLICATE"],
        "DUPLICATE",
    )

    output["source_cycle"] = clean_text(
        source["CYCLE_OF_LAST_UPDATE"]
    )

    output["source_dataset"] = DATASET_ID
    output["source_version"] = SOURCE_VERSION
    output["source_layer"] = spec.source_layer


def add_capacity_fields(
    output: gpd.GeoDataFrame,
    source: gpd.GeoDataFrame,
) -> None:
    """Add provider P10/P50/P90 storage-resource estimates."""

    output["storage_p10_tonnes"] = numeric(
        source["VOL_LOW"]
    )

    output["storage_p50_tonnes"] = numeric(
        source["VOL_MED"]
    )

    output["storage_p90_tonnes"] = numeric(
        source["VOL_HIGH"]
    )

    output["p50_method"] = build_p50_method(
        source["MED_CALCED"]
    )


def add_reservoir_properties(
    output: gpd.GeoDataFrame,
    source: gpd.GeoDataFrame,
) -> None:
    """Add available physical reservoir properties in standardized units."""

    output["depth_m"] = (
        numeric(source["DEPTH_FT"])
        * FT_TO_M
    )

    output["thickness_m"] = (
        numeric(source["THICKNESS_FT"])
        * FT_TO_M
    )

    if "SALINITY_TDS" in source.columns:
        output["salinity_tds_ppm"] = numeric(
            source["SALINITY_TDS"]
        )

    if "PRESSURE_PSI" in source.columns:
        output["pressure_mpa"] = (
            numeric(source["PRESSURE_PSI"])
            * PSI_TO_MPA
        )

    if "TEMPERATURE_F" in source.columns:
        output["temperature_c"] = fahrenheit_to_celsius(
            source["TEMPERATURE_F"]
        )

    if "POROSITY_PCT" in source.columns:
        output["porosity_fraction"] = percent_to_fraction(
            source["POROSITY_PCT"]
        )

    if "PERMEABILITY_mD" in source.columns:
        output["permeability_md"] = numeric(
            source["PERMEABILITY_mD"]
        )


# =============================================================================
# Layer-specific harmonization
# =============================================================================


def harmonize_grid_layer(
    source: gpd.GeoDataFrame,
    spec: LayerSpec,
) -> gpd.GeoDataFrame:
    """Harmonize one saline or coal 10 km resource-grid layer."""

    output = gpd.GeoDataFrame(
        geometry=source.geometry.copy(),
        crs=source.crs,
    )

    add_common_resource_fields(
        output,
        source,
        spec,
    )

    output["grid_cell_id"] = clean_text(
        source["COL_ROW"]
    )

    output["resource_name"] = clean_text(
        source["RESOURCE_NAME"]
    )

    if "BASIN_NAME" in source.columns:
        output["basin_name"] = clean_text(
            source["BASIN_NAME"]
        )

    if "ARRA_PROJECT" in source.columns:
        output["arra_project"] = clean_text(
            source["ARRA_PROJECT"]
        )

    output["resource_area_m2"] = numeric(
        source["RSC_AREA_CELL"]
    )

    add_capacity_fields(
        output,
        source,
    )

    add_reservoir_properties(
        output,
        source,
    )

    output, _, _ = project_and_measure(
        output,
        target_crs=SILVER_CRS,
    )

    return output


def harmonize_extent_layer(
    source: gpd.GeoDataFrame,
    spec: LayerSpec,
) -> gpd.GeoDataFrame:
    """Harmonize one saline or coal resource-extent polygon layer."""

    output = gpd.GeoDataFrame(
        geometry=source.geometry.copy(),
        crs=source.crs,
    )

    add_common_resource_fields(
        output,
        source,
        spec,
    )

    output["resource_name"] = clean_text(
        source["RESOURCE_NAME"]
    )

    if "BASIN_NAME" in source.columns:
        output["basin_name"] = clean_text(
            source["BASIN_NAME"]
        )

    if "ARRA_PROJECT" in source.columns:
        output["arra_project"] = clean_text(
            source["ARRA_PROJECT"]
        )

    output, _, _ = project_and_measure(
        output,
        target_crs=SILVER_CRS,
    )

    return output


def harmonize_oil_gas(
    source: gpd.GeoDataFrame,
    spec: LayerSpec,
) -> gpd.GeoDataFrame:
    """Harmonize the NATCARB oil and gas storage-resource layer."""

    output = gpd.GeoDataFrame(
        geometry=source.geometry.copy(),
        crs=source.crs,
    )

    add_common_resource_fields(
        output,
        source,
        spec,
    )

    output["field_name"] = clean_text(
        source["FIELD_NAME"]
    )

    output["field_type"] = normalize_field_type(
        source["FIELD_TYPE"]
    )

    output["reservoir_number"] = numeric(
        source["RESERVOIR_NUM"]
    )

    output["reservoir_name"] = clean_text(
        source["RESERVOIR_NAME"]
    )

    output["state_source"] = clean_text(
        source["STATE_SRC"]
    )

    output["total_field_area_m2"] = numeric(
        source["TOTAL_FIELD_AREA"]
    )

    add_capacity_fields(
        output,
        source,
    )

    add_reservoir_properties(
        output,
        source,
    )

    output, _, _ = project_and_measure(
        output,
        target_crs=SILVER_CRS,
    )

    return output


def harmonize_layer(
    source: gpd.GeoDataFrame,
    spec: LayerSpec,
) -> gpd.GeoDataFrame:
    """Dispatch one NATCARB source layer to its harmonization routine."""

    if spec.representation == "resource_grid_cell":
        return harmonize_grid_layer(
            source,
            spec,
        )

    if spec.representation == "resource_extent":
        return harmonize_extent_layer(
            source,
            spec,
        )

    if spec.storage_type == "oil_gas":
        return harmonize_oil_gas(
            source,
            spec,
        )

    raise ValueError(
        f"Unsupported NATCARB layer specification: {spec}"
    )


# =============================================================================
# Semantic QA
# =============================================================================


def build_capacity_qa(
    data: gpd.GeoDataFrame,
    layer_name: str,
) -> pd.DataFrame:
    """Build semantic QA checks for a capacity-bearing storage layer."""

    required = {
        "storage_p10_tonnes",
        "storage_p50_tonnes",
        "storage_p90_tonnes",
        "assessed",
    }

    if not required.issubset(data.columns):
        return pd.DataFrame()

    low = data["storage_p10_tonnes"]
    med = data["storage_p50_tonnes"]
    high = data["storage_p90_tonnes"]

    unassessed = data["assessed"].eq(False)
    assessed = data["assessed"].eq(True)

    complete_capacity = (
        low.notna()
        & med.notna()
        & high.notna()
    )

    rows = [
        {
            "layer": layer_name,
            "check": "rows",
            "count": len(data),
        },
        {
            "layer": layer_name,
            "check": "assessed_rows",
            "count": int(assessed.sum()),
        },
        {
            "layer": layer_name,
            "check": "unassessed_rows",
            "count": int(unassessed.sum()),
        },
        {
            "layer": layer_name,
            "check": "duplicate_rows",
            "count": int(
                data["duplicate"].eq(True).sum()
            ),
        },
        {
            "layer": layer_name,
            "check": "overlap_rows",
            "count": int(
                data["overlap"].eq(True).sum()
            ),
        },
        {
            "layer": layer_name,
            "check": "unassessed_with_capacity",
            "count": int(
                (
                    unassessed
                    & (
                        low.notna()
                        | med.notna()
                        | high.notna()
                    )
                ).sum()
            ),
        },
        {
            "layer": layer_name,
            "check": "p10_gt_p50",
            "count": int(
                (
                    complete_capacity
                    & (low > med)
                ).sum()
            ),
        },
        {
            "layer": layer_name,
            "check": "p50_gt_p90",
            "count": int(
                (
                    complete_capacity
                    & (med > high)
                ).sum()
            ),
        },
    ]

    return pd.DataFrame(rows)


def validate_physical_ranges(
    data: gpd.GeoDataFrame,
    layer_name: str,
) -> None:
    """Validate deterministic physical bounds without imputing data."""

    nonnegative_fields = (
        "storage_p10_tonnes",
        "storage_p50_tonnes",
        "storage_p90_tonnes",
        "resource_area_m2",
        "total_field_area_m2",
        "depth_m",
        "thickness_m",
        "salinity_tds_ppm",
        "pressure_mpa",
        "permeability_md",
    )

    for field in nonnegative_fields:
        if field not in data.columns:
            continue

        invalid = (
            data[field].notna()
            & (data[field] < 0)
        )

        if invalid.any():
            raise ValueError(
                f"{layer_name}.{field} contains "
                f"{int(invalid.sum()):,} negative value(s)."
            )

    if "porosity_fraction" in data.columns:
        invalid = (
            data["porosity_fraction"].notna()
            & (
                (data["porosity_fraction"] < 0)
                | (data["porosity_fraction"] > 1)
            )
        )

        if invalid.any():
            raise ValueError(
                f"{layer_name}.porosity_fraction contains "
                f"{int(invalid.sum()):,} value(s) outside [0, 1]."
            )


def validate_harmonized_layer(
    data: gpd.GeoDataFrame,
    spec: LayerSpec,
) -> None:
    """Validate one completed Silver feature layer."""

    if data.empty:
        raise ValueError(
            f"Harmonized layer is empty: {spec.output_layer}"
        )

    validate_target_crs(
        data,
        target_crs=SILVER_CRS,
    )

    if data["natcarb_id"].isna().any():
        raise ValueError(
            f"{spec.output_layer} contains null natcarb_id values."
        )

    if data["natcarb_id"].duplicated().any():
        raise ValueError(
            f"{spec.output_layer} contains duplicate natcarb_id values."
        )

    if data.geometry.isna().any():
        raise ValueError(
            f"{spec.output_layer} contains null geometries."
        )

    if (~data.geometry.is_valid).any():
        raise ValueError(
            f"{spec.output_layer} contains invalid geometries after repair."
        )

    validate_physical_ranges(
        data,
        spec.output_layer,
    )


# =============================================================================
# Summary metadata
# =============================================================================


def build_layer_inventory(
    harmonized: dict[str, gpd.GeoDataFrame],
) -> pd.DataFrame:
    """Build a compact inventory of Silver geological layers."""

    rows: list[dict[str, object]] = []

    for spec in LAYER_SPECS:
        data = harmonized[spec.output_layer]

        crs = data.crs

        if crs is None:
            raise ValueError(
                f"Silver layer has no CRS: {spec.output_layer}"
            )

        rows.append(
            {
                "source_layer": spec.source_layer,
                "silver_layer": spec.output_layer,
                "storage_type": spec.storage_type,
                "representation": spec.representation,
                "capacity_data": spec.has_capacity,
                "rows": len(data),
                "crs": crs.to_string(),
                "geometry_types": ", ".join(
                    sorted(
                        data.geometry.geom_type
                        .dropna()
                        .unique()
                    )
                ),
                "duplicate_flagged": int(
                    data["duplicate"].eq(True).sum()
                ),
                "overlap_flagged": int(
                    data["overlap"].eq(True).sum()
                ),
                "assessed": int(
                    data["assessed"].eq(True).sum()
                ),
            }
        )

    return pd.DataFrame(rows)


def build_field_dictionary() -> pd.DataFrame:
    """Build field definitions for all harmonized NATCARB feature-layer fields."""

    rows = [
        ("natcarb_id", "Harmonized", "Stable CANCO2-Storage identifier derived from source layer and FileGDB feature ID.", None),
        ("source_fid", "Source", "Provider FileGDB feature identifier retained for traceability.", None),
        ("storage_type", "Classification", "High-level geological storage class: saline, coal, or oil_gas.", None),
        ("representation", "Classification", "Spatial representation: resource_grid_cell, resource_extent, or storage_resource.", None),
        ("assessment_type", "Classification", "Dataset-level geological assessment type used by CANCO2-Storage.", None),
        ("data_class", "Classification", "Dataset-level CANCO2-Storage data class.", None),
        ("capacity_data", "Classification", "Whether the layer carries quantitative storage-resource estimates.", None),
        ("injectivity_status", "Classification", "Status of quantitative injectivity assessment for this dataset.", None),
        ("partnership", "Source", "NATCARB Regional Carbon Sequestration Partnership code.", None),
        ("assessed", "Harmonized", "Whether NATCARB identifies the resource as assessed for carbon storage potential.", None),
        ("overlap", "Harmonized", "Provider flag identifying overlap with an adjacent partnership resource.", None),
        ("duplicate", "Harmonized", "Provider flag identifying duplicate adjacent-partnership data; retained in Silver for provenance.", None),
        ("source_cycle", "Source", "Provider cycle or update identifier for the record.", None),
        ("source_dataset", "Provenance", "CANCO2-Storage dataset identifier.", None),
        ("source_version", "Provenance", "Provider dataset version.", None),
        ("source_layer", "Provenance", "Original NATCARB FileGDB layer name.", None),
        ("grid_cell_id", "Source", "Provider COL_ROW identifier for the NATCARB 10 km grid cell; not a unique feature identifier.", None),
        ("resource_name", "Source", "Provider geological storage-resource name.", None),
        ("basin_name", "Source", "Provider basin name where supplied.", None),
        ("arra_project", "Source", "Provider ARRA project code where supplied.", None),
        ("field_name", "Source", "Provider oil/gas field name.", None),
        ("field_type", "Harmonized", "Normalized provider oil/gas field type. STORAGE is retained when observed even though it is not documented in the supplied FIELD_TYPE metadata domain.", None),
        ("reservoir_number", "Source", "Provider reservoir number.", None),
        ("reservoir_name", "Source", "Provider reservoir name.", None),
        ("state_source", "Source", "Provider state/source jurisdiction attribute for oil and gas resources.", None),
        ("total_field_area_m2", "Harmonized", "Provider total field area, retained in square metres.", "m2"),
        ("resource_area_m2", "Harmonized", "Area of geological resource occurring within a NATCARB 10 km cell.", "m2"),
        ("storage_p10_tonnes", "Harmonized", "Provider low P10 carbon storage-resource estimate.", "metric tonnes CO2"),
        ("storage_p50_tonnes", "Harmonized", "Provider medium P50 carbon storage-resource estimate.", "metric tonnes CO2"),
        ("storage_p90_tonnes", "Harmonized", "Provider high P90 carbon storage-resource estimate.", "metric tonnes CO2"),
        ("p50_method", "Harmonized", "Whether the P50 estimate was provider-supplied or calculated by KGS from P10/P90.", None),
        ("depth_m", "Derived", "Mean storage-resource depth converted from provider feet values.", "m"),
        ("thickness_m", "Derived", "Mean storage-resource thickness converted from provider feet values.", "m"),
        ("salinity_tds_ppm", "Harmonized", "Mean total dissolved solids concentration.", "ppm"),
        ("pressure_mpa", "Derived", "Mean storage-formation pressure converted from provider PSI values.", "MPa"),
        ("temperature_c", "Derived", "Mean storage-resource temperature converted from degrees Fahrenheit.", "degC"),
        ("porosity_fraction", "Derived", "Mean provider porosity converted from percent to fraction.", "fraction"),
        ("permeability_md", "Harmonized", "Mean storage-resource permeability.", "mD"),
        ("geometry_area_m2", "Derived", "Area of the persisted Silver feature geometry in the standard projected CRS.", "m2"),
        ("geometry_area_ha", "Derived", "Area of the persisted Silver feature geometry in hectares.", "ha"),
        ("geometry_perimeter_m", "Derived", "Perimeter of the persisted Silver feature geometry in the standard projected CRS.", "m"),
        ("geometry", "Spatial", "Feature geometry reprojected to the repository Silver CRS.", SILVER_CRS),
    ]

    return pd.DataFrame(
        rows,
        columns=[
            "field",
            "field_class",
            "description",
            "units",
        ],
    )


# =============================================================================
# Export helpers
# =============================================================================


def write_feature_layers(
    layers: dict[str, gpd.GeoDataFrame],
    output_path: Path,
) -> None:
    """Write harmonized geological feature layers to one GeoPackage."""

    output_path.unlink(missing_ok=True)

    for index, spec in enumerate(LAYER_SPECS):
        data = layers[spec.output_layer]

        pyogrio.write_dataframe(
            data,
            output_path,
            layer=spec.output_layer,
            driver="GPKG",
            append=index > 0,
        )


def write_domain_tables(
    gdb_path: Path,
    output_path: Path,
) -> tuple[str, ...]:
    """Write provider domain tables as registered GeoPackage attribute tables."""

    written: list[str] = []

    with sqlite3.connect(output_path) as conn:
        for source_table, output_table in DOMAIN_TABLES.items():
            table = load_domain_table(
                gdb_path,
                source_table,
            )

            write_registered_attribute_table(
                conn,
                dataframe=table,
                table_name=output_table,
                description=DOMAIN_DESCRIPTIONS[output_table],
            )
            written.append(output_table)

    return tuple(written)


# =============================================================================
# Source metadata and schema documentation
# =============================================================================


def build_source_metadata(
    output_path: Path,
) -> pd.DataFrame:
    """Build intrinsic dataset metadata persisted in the Silver GeoPackage.

    The metadata table stores machine-readable facts about the generated
    Silver artifact. Human-readable README rendering belongs to
    ``canco2_storage.metadata.natcarb_doe``.
    """

    rows = [
        (
            "Who",
            (
                f"{CANCO2RE_SUBMISSION.creator_name}, "
                f"CanCO2Re Activity {CANCO2RE_SUBMISSION.activity_code}"
            ),
        ),
        (
            "What",
            "Harmonized DOE/NETL NATCARB v1502 geological CO2 storage-resource "
            "dataset containing saline, coal, and oil/gas storage-resource "
            "representations with published P10/P50/P90 storage estimates where "
            "available.",
        ),
        ("When", CREATED_DATE.isoformat()),
        (
            "Where",
            f"{SOURCE_GEOGRAPHIC_EXTENT}. Silver spatial layers use NAD83 / "
            f"Canada Atlas Lambert, {SILVER_CRS}.",
        ),
        (
            "How",
            "Derived from the NATCARB v1502 File Geodatabase. Five geological "
            "resource layers are harmonized to descriptive field names, documented "
            "physical units are standardized, source feature identifiers and "
            "provider assessment/overlap/duplicate/P50-method flags are preserved, "
            f"geometries are repaired when required and reprojected to {SILVER_CRS}, "
            "and provider domain tables are retained as registered GeoPackage "
            "attribute tables. Provider-flagged duplicate resources are preserved "
            "for provenance rather than silently removed.",
        ),
        ("submission_filename", output_path.name),
        ("activity_code", CANCO2RE_SUBMISSION.activity_code),
        ("creator_name", CANCO2RE_SUBMISSION.creator_name),
        ("creator_initials", CANCO2RE_SUBMISSION.creator_initials),
        ("dataset_id", DATASET_ID),
        ("data_type", DATA_TYPE),
        ("source_title", SOURCE_TITLE),
        ("source_organization", SOURCE_ORGANIZATION),
        ("source_version", SOURCE_VERSION),
        ("source_publication_date", SOURCE_PUBLICATION_DATE),
        ("source_geographic_extent", SOURCE_GEOGRAPHIC_EXTENT),
        ("source_format", "Esri File Geodatabase"),
        ("silver_format", "OGC GeoPackage"),
        ("silver_crs", SILVER_CRS),
        ("assessment_type", ASSESSMENT_TYPE),
        ("data_class", DATA_CLASS),
        ("capacity_data", "True"),
        ("injectivity_status", INJECTIVITY_STATUS),
    ]

    return pd.DataFrame(
        rows,
        columns=["key", "value"],
    )

def build_source_schema(gdb_path: Path) -> pd.DataFrame:
    """Inventory source FileGDB layers, tables, fields, and provider types."""

    rows: list[dict[str, object]] = []
    layer_names = [spec.source_layer for spec in LAYER_SPECS]
    layer_names.extend(DOMAIN_TABLES)

    for layer_name in layer_names:
        info = pyogrio.read_info(gdb_path, layer=layer_name)
        fields = list(info.get("fields", []))
        dtypes = list(info.get("dtypes", []))
        geometry_type = info.get("geometry_type")
        crs = info.get("crs")
        feature_count = info.get("features")

        if not fields:
            rows.append(
                {
                    "source_layer": layer_name,
                    "field": None,
                    "source_dtype": None,
                    "geometry_type": geometry_type,
                    "source_crs": crs,
                    "feature_count": feature_count,
                }
            )
            continue

        for field, dtype in zip(fields, dtypes, strict=False):
            rows.append(
                {
                    "source_layer": layer_name,
                    "field": field,
                    "source_dtype": str(dtype),
                    "geometry_type": geometry_type,
                    "source_crs": crs,
                    "feature_count": feature_count,
                }
            )

    return pd.DataFrame(rows)


def build_qa_summary(
    layer_inventory: pd.DataFrame,
    capacity_qa: pd.DataFrame,
) -> pd.DataFrame:
    """Build the dataset-level QA table exported in-GPKG and as CSV."""

    capacity_lookup = {
        (str(row["layer"]), str(row["check"])): int(row["count"])
        for _, row in capacity_qa.iterrows()
    }

    def total_check(name: str) -> int:
        return sum(
            count
            for (_, check), count in capacity_lookup.items()
            if check == name
        )

    rows = [
        ("feature_layers", len(LAYER_SPECS), "Five geological storage feature layers are expected."),
        ("domain_tables", len(DOMAIN_TABLES), "Ten provider lookup/domain tables are retained."),
        ("total_spatial_features", int(layer_inventory["rows"].sum()), "Total harmonized spatial features."),
        ("duplicate_flagged_features", int(layer_inventory["duplicate_flagged"].sum()), "Provider-flagged duplicates are retained for provenance."),
        ("overlap_flagged_features", int(layer_inventory["overlap_flagged"].sum()), "Provider overlap flags are retained without spatial aggregation."),
        ("assessed_features", int(layer_inventory["assessed"].sum()), "Features flagged by NATCARB as assessed."),
        ("unassessed_with_capacity", total_check("unassessed_with_capacity"), "Expected to be zero under documented NATCARB semantics."),
        ("p10_gt_p50", total_check("p10_gt_p50"), "Reported for source QA; values are not silently corrected."),
        ("p50_gt_p90", total_check("p50_gt_p90"), "Reported for source QA; values are not silently corrected."),
        ("persisted_invalid_geometries", 0, "Persisted feature layers are reopened and required to contain no invalid geometries."),
        ("silver_crs", SILVER_CRS, "All persisted spatial layers use the CanCO2Re standard CRS."),
    ]

    return pd.DataFrame(rows, columns=["check", "value", "notes"])




# =============================================================================
# Persisted-output validation
# =============================================================================


def validate_output_gpkg(
    output_path: Path,
    harmonized: dict[str, gpd.GeoDataFrame],
) -> None:
    """Validate the persisted feature and attribute-table GeoPackage contract."""

    if not output_path.is_file():
        raise FileNotFoundError(
            f"NATCARB Silver GeoPackage not found: {output_path}"
        )

    expected_contents = {
        **{spec.output_layer: "features" for spec in LAYER_SPECS},
        **{name: "attributes" for name in DOMAIN_TABLES.values()},
        METADATA_TABLE: "attributes",
        QA_TABLE: "attributes",
    }

    validate_registered_tables(
        gpkg_path=output_path,
        expected=expected_contents,
    )

    for spec in LAYER_SPECS:
        validate_written_spatial_layer(
            gpkg_path=output_path,
            layer_name=spec.output_layer,
            expected=harmonized[spec.output_layer],
            unique_id_field="natcarb_id",
            target_crs=SILVER_CRS,
        )


# =============================================================================
# Main workflow
# =============================================================================


def harmonize(
    gdb_path: Path = RAW_NATCARB,
    output_path: Path = OUTPUT_GPKG,
) -> NATCARBHarmonizationResult:
    """Run the complete NATCARB geological-storage Silver harmonization."""

    gdb_path = Path(gdb_path)
    output_path = Path(output_path)

    validate_source_gdb(gdb_path)

    PROCESSED_NATCARB.mkdir(
        parents=True,
        exist_ok=True,
    )

    INSPECTION_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("Harmonizing DOE/NETL NATCARB v1502...\n")
    print(f"Source GDB: {gdb_path}")
    print(f"Silver CRS: {SILVER_CRS}")
    print(f"Output:     {output_path}\n")

    harmonized: dict[str, gpd.GeoDataFrame] = {}
    capacity_qa_frames: list[pd.DataFrame] = []

    for spec in LAYER_SPECS:
        print(
            f"[Load] {spec.source_layer}"
        )

        source = load_source_layer(
            gdb_path,
            spec,
        )

        print(
            f"[Harmonize] {spec.source_layer} "
            f"→ {spec.output_layer}"
        )

        data = harmonize_layer(
            source,
            spec,
        )

        validate_harmonized_layer(
            data,
            spec,
        )

        harmonized[spec.output_layer] = data

        if spec.has_capacity:
            capacity_qa_frames.append(
                build_capacity_qa(
                    data,
                    spec.output_layer,
                )
            )

        print(
            f"  rows: {len(data):,}"
        )

    layer_inventory = build_layer_inventory(
        harmonized
    )

    capacity_qa = pd.concat(
        capacity_qa_frames,
        ignore_index=True,
    )

    field_dictionary = build_field_dictionary()
    source_metadata = build_source_metadata(output_path)
    source_schema = build_source_schema(gdb_path)
    qa_summary = build_qa_summary(
        layer_inventory,
        capacity_qa,
    )

    print("\nWriting NATCARB Silver GeoPackage...")

    write_feature_layers(
        harmonized,
        output_path,
    )

    written_domain_tables = write_domain_tables(
        gdb_path,
        output_path,
    )

    with sqlite3.connect(output_path) as conn:
        write_registered_attribute_table(
            conn,
            dataframe=source_metadata,
            table_name=METADATA_TABLE,
            description=(
                "Authoritative dataset-level NATCARB provenance, classification, "
                "and CanCO2Re submission metadata used by downstream "
                "documentation rendering."
            ),
        )
        write_registered_attribute_table(
            conn,
            dataframe=qa_summary,
            table_name=QA_TABLE,
            description=(
                "Dataset-level NATCARB Silver quality-assurance summary."
            ),
        )

    validate_output_gpkg(
        output_path,
        harmonized,
    )

    layer_inventory.to_csv(LAYER_INVENTORY_PATH, index=False)
    capacity_qa.to_csv(CAPACITY_QA_PATH, index=False)
    field_dictionary.to_csv(FIELD_DICTIONARY_PATH, index=False)
    source_metadata.to_csv(SOURCE_METADATA_PATH, index=False)
    source_schema.to_csv(SOURCE_SCHEMA_PATH, index=False)
    qa_summary.to_csv(QA_SUMMARY_PATH, index=False)

    result = NATCARBHarmonizationResult(
        output_gpkg=output_path,
        feature_layers=tuple(
            spec.output_layer
            for spec in LAYER_SPECS
        ),
        domain_tables=written_domain_tables,
        qa_summary_path=QA_SUMMARY_PATH,
        field_dictionary_path=FIELD_DICTIONARY_PATH,
        source_metadata_path=SOURCE_METADATA_PATH,
        source_schema_path=SOURCE_SCHEMA_PATH,
        layer_inventory_path=LAYER_INVENTORY_PATH,
        capacity_qa_path=CAPACITY_QA_PATH,
    )

    print_summary(result)

    return result


# =============================================================================
# Console summary
# =============================================================================


def print_summary(
    result: NATCARBHarmonizationResult,
) -> None:
    """Print the completed NATCARB Silver-product summary."""

    print("\nNATCARB harmonization summary")
    print("-----------------------------")
    print(f"GeoPackage:      {result.output_gpkg}")
    print(f"Feature layers:  {len(result.feature_layers)}")
    print(f"Domain tables:   {len(result.domain_tables)}")
    print("Support tables:  2 (metadata + QA)")
    print(f"QA summary:      {result.qa_summary_path.name}")
    print(f"Field dictionary:{result.field_dictionary_path.name}")
    print(f"Source metadata: {result.source_metadata_path.name}")
    print(f"Source schema:   {result.source_schema_path.name}")
    print(f"Layer inventory: {result.layer_inventory_path.name}")
    print(f"Capacity QA:     {result.capacity_qa_path.name}")

    print("\nGeological feature layers:")
    for layer in result.feature_layers:
        print(f"- {layer}")

    print("\nProvider domain tables:")
    for table in result.domain_tables:
        print(f"- {table}")


# =============================================================================
# CLI
# =============================================================================


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Harmonize DOE/NETL NATCARB v1502 geological storage "
            "resources into the CANCO2-Storage Silver schema."
        )
    )

    parser.add_argument(
        "--gdb-path",
        type=Path,
        default=RAW_NATCARB,
        help=(
            "Path to NATCARB_v1502.gdb. "
            "Defaults to the validated Bronze source."
        ),
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_GPKG,
        help=(
            "Destination Silver GeoPackage."
        ),
    )

    return parser.parse_args()


def main() -> None:
    """Run NATCARB Silver harmonization."""

    args = parse_args()

    harmonize(
        gdb_path=args.gdb_path,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
