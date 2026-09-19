"""Build the unified Canadian geological CO2 storage GeoPackage.

This script is the cleaned, script-native form of Notebook 12. It preserves the
validated logic from the notebook conversion without adding new geological or
storage assumptions.

Runtime inputs
--------------
Four dated Silver GeoPackages under ``data/processed``:

- AER carbon sequestration agreements
- GSC Atlantic Chance-of-Success storage assessment
- Northeast BC storage atlas
- DOE/NETL NATCARB v1502

A Statistics Canada province/territory boundary shapefile is also required for
spatially subsetting NATCARB saline and coal grid cells to Canada, matching the
Notebook 12 method.

Primary output
--------------
``data/processed/unified_storage/YYYYMMDD_13_CanadaGeologicalStorageUnified_AV_v2.gpkg``

The build date and submission stem are generated through the repository metadata
naming helpers. Precursor Silver GeoPackages are discovered from their canonical
``data/processed/<dataset>/`` directories.

The unified GeoPackage persists the four canonical substantive tables:

- storage_units
- storage_features
- storage_assessments
- administrative_features

It also persists dataset documentation. Precursor metadata and QA tables are
discovered directly from each Silver GeoPackage rather than being identified by
hard-coded table names. A normalized source catalog provides one human-readable
row per precursor dataset while the complete child metadata tables are retained
as key/value lineage. The core unified metadata also records pointers to those
provenance tables. Unified documentation table names are derived from the
unified dataset identifier.

The script does not synthesize QGIS-specific metadata tables or XML. Repository metadata remain in the internal GeoPackage documentation tables; QGIS layer metadata can be managed separately within QGIS when needed.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


import geopandas as gpd
import pandas as pd

from canco2_storage.harmonize.common import (
    SILVER_CRS,
    register_attribute_table,
    validate_registered_tables,
    validate_target_crs,
)
from canco2_storage.metadata.common import (
    CANCO2RE_SUBMISSION,
    build_submission_stem,
)
from canco2_storage.paths import find_project_root


# =============================================================================
# Repository and package constants
# =============================================================================

WORKING_CRS = SILVER_CRS

UNIFIED_DATA_TYPE = "CanadaGeologicalStorageUnified"
UNIFIED_BUILD_VARIANT = "v2"
CREATED_DATE = date.today()
UNIFIED_DATE = CREATED_DATE.isoformat()

UNIFIED_SUBMISSION_FILENAME = (
    f"{build_submission_stem(data_type=UNIFIED_DATA_TYPE, created_date=CREATED_DATE)}_"
    f"{UNIFIED_BUILD_VARIANT}.gpkg"
)

CANADIAN_PROVINCE_TERRITORY_CODES = {
    "AB", "BC", "MB", "NB", "NL", "NS", "NT",
    "NU", "ON", "PE", "QC", "SK", "YT",
}

PRUID_TO_CODE = {
    "10": "NL",
    "11": "PE",
    "12": "NS",
    "13": "NB",
    "24": "QC",
    "35": "ON",
    "46": "MB",
    "47": "SK",
    "48": "AB",
    "59": "BC",
    "60": "YT",
    "61": "NT",
    "62": "NU",
}


CANONICAL_SCHEMAS: dict[str, tuple[str, ...]] = {
    "storage_units": (
        "storage_unit_id",
        "source_dataset",
        "source_unit_id",
        "storage_type",
        "storage_subtype",
        "storage_name",
        "formation",
        "geological_group",
        "basin_name",
        "country",
        "province_territory",
        "land_status",
        "assessment_type",
        "data_class",
        "capacity_data",
        "capacity_status",
        "injectivity_status",
        "co2_phase",
    ),
    "storage_features": (
        "storage_feature_id",
        "storage_unit_id",
        "source_dataset",
        "source_layer",
        "source_feature_id",
        "storage_type",
        "storage_subtype",
        "representation",
        "assessment_type",
        "data_class",
        "capacity_data",
        "injectivity_status",
        "country",
        "province_territory",
        "land_status",
        "geometry_area_m2",
        "geometry_area_ha",
        "geometry_perimeter_m",
        "geometry",
    ),
    "storage_assessments": (
        "storage_assessment_id",
        "storage_feature_id",
        "storage_unit_id",
        "source_dataset",
        "source_layer",
        "assessment_scope",
        "assessment_type",
        "storage_p10_tonnes",
        "storage_p50_tonnes",
        "storage_p90_tonnes",
        "theoretical_storage_tonnes",
        "effective_storage_tonnes",
        "capacity_basis",
        "capacity_method",
        "capacity_status",
        "depth_m",
        "thickness_m",
        "pressure_mpa",
        "temperature_c",
        "porosity_fraction",
        "permeability_md",
        "salinity_tds_ppm",
        "reservoir_cos",
        "seal_cos",
        "trap_cos",
        "total_cos",
        "co2_phase",
    ),
}


# Canonical SQLite/pandas type contract for quantitative assessment fields.
# These columns are nullable continuous measurements or capacities and are
# intentionally persisted as REAL even when a particular source contributes
# only missing values.
STORAGE_ASSESSMENT_REAL_COLUMNS: tuple[str, ...] = (
    "storage_p10_tonnes",
    "storage_p50_tonnes",
    "storage_p90_tonnes",
    "theoretical_storage_tonnes",
    "effective_storage_tonnes",
    "depth_m",
    "thickness_m",
    "pressure_mpa",
    "temperature_c",
    "porosity_fraction",
    "permeability_md",
    "salinity_tds_ppm",
    "reservoir_cos",
    "seal_cos",
    "trap_cos",
    "total_cos",
)

ADMINISTRATIVE_COLUMNS = (
    "administrative_feature_id",
    "parent_administrative_feature_id",
    "source_dataset",
    "source_layer",
    "source_feature_id",
    "administrative_type",
    "agreement_id",
    "tract_id",
    "agreement_group",
    "agreement_type_code",
    "mineral_type",
    "status",
    "vintage",
    "designated_representative",
    "zone_description",
    "original_area_ha",
    "agreement_area_ha",
    "term_date",
    "continuation_date",
    "current_expiry",
    "tract_count",
    "province_territory",
    "geometry_area_m2",
    "geometry_area_ha",
    "geometry_perimeter_m",
    "assessment_type",
    "data_class",
    "capacity_data",
    "geometry",
)

FIELD_TYPE_TO_SUBTYPE = {
    "OIL": "oil_reservoir",
    "GAS": "gas_reservoir",
    "OIL & GAS": "oil_and_gas_reservoir",
    "STORAGE": "storage_reservoir",
    "UNDETERMINED": "unknown",
}


@dataclass(frozen=True)
class BuildPaths:
    """Container for resolved input and output paths used by the unified build.

    Attributes
    ----------
    project_root : pathlib.Path
        Repository root containing ``pyproject.toml``.
    source_dir : pathlib.Path
        Root directory containing the processed Silver datasets.
    source_files : dict[str, pathlib.Path]
        Mapping from source dataset identifier to source GeoPackage path.
    output_path : pathlib.Path
        Destination path for the unified GeoPackage.
    province_boundary_path : pathlib.Path
        Statistics Canada province/territory boundary dataset used for
        jurisdiction assignment.
    """
    project_root: Path
    source_dir: Path
    source_files: dict[str, Path]
    output_path: Path
    province_boundary_path: Path


@dataclass
class UnifiedTables:
    """Container for the four canonical unified storage tables.

    Attributes
    ----------
    storage_units : pandas.DataFrame
        Logical geological storage units.
    storage_features : geopandas.GeoDataFrame
        Spatial representations associated with storage units.
    storage_assessments : pandas.DataFrame
        Capacity, prospectivity, and related storage assessment records.
    administrative_features : geopandas.GeoDataFrame
        Regulatory and tenure polygons retained separately from geological
        storage objects.
    """
    storage_units: pd.DataFrame
    storage_features: gpd.GeoDataFrame
    storage_assessments: pd.DataFrame
    administrative_features: gpd.GeoDataFrame


@dataclass
class DocumentationTables:
    """Container for source-lineage and unified documentation products.

    Attributes
    ----------
    source_catalog : pandas.DataFrame
        One normalized provenance row per precursor Silver dataset, including
        source title, authorship/preparer, organization, publication, year, and
        available source links.
    source_metadata : pandas.DataFrame
        Complete key/value metadata copied from precursor Silver GeoPackages.
    source_qa : pandas.DataFrame
        QA records copied from precursor Silver GeoPackages.
    unified_metadata : pandas.DataFrame
        Dataset-level metadata for the unified product.
    unified_qa : pandas.DataFrame
        QA results calculated from the persisted unified GeoPackage.
    """
    source_catalog: pd.DataFrame
    source_metadata: pd.DataFrame
    source_qa: pd.DataFrame
    unified_metadata: pd.DataFrame
    unified_qa: pd.DataFrame


# =============================================================================
# Path resolution
# =============================================================================


def discover_latest_silver_gpkg(
    directory: Path,
    *,
    data_type: str,
) -> Path:
    """Return the newest canonical Silver GeoPackage for one precursor dataset.

    Accepted filenames follow the repository submission convention

    ``YYYYMMDD_<activity>_<data_type>_<initials>.gpkg``

    and also tolerate a future timestamped form

    ``YYYYMMDDHHMMSS_<activity>_<data_type>_<initials>.gpkg``.

    Selection is based first on the date/timestamp encoded in the filename and,
    when more than one matching artifact has the same encoded timestamp, on file
    modification time. Historical Silver builds can therefore coexist without
    hard-coding a particular build date.
    """

    if not directory.is_dir():
        raise FileNotFoundError(
            f"Silver dataset directory does not exist: {directory}"
        )

    suffix = (
        f"_{CANCO2RE_SUBMISSION.activity_code}_"
        f"{data_type}_{CANCO2RE_SUBMISSION.creator_initials}.gpkg"
    )

    filename_pattern = re.compile(
        rf"^(?P<stamp>\d{{8}}(?:\d{{6}})?){re.escape(suffix)}$"
    )

    candidates: list[tuple[str, int, Path]] = []

    for path in directory.glob("*.gpkg"):
        match = filename_pattern.fullmatch(path.name)
        if match is None:
            continue

        stamp = match.group("stamp")

        # Put date-only and datetime-stamped filenames on the same sortable scale.
        normalized_stamp = f"{stamp}000000" if len(stamp) == 8 else stamp

        candidates.append(
            (
                normalized_stamp,
                path.stat().st_mtime_ns,
                path,
            )
        )

    if not candidates:
        raise FileNotFoundError(
            "No canonical Silver GeoPackage found for "
            f"data_type={data_type!r} in {directory}. "
            f"Expected a filename ending with {suffix!r}."
        )

    _, _, latest_path = max(
        candidates,
        key=lambda item: (item[0], item[1]),
    )

    return latest_path


def build_paths(
    project_root: Path,
    output_path: Path | None = None,
) -> BuildPaths:
    """Resolve source and output paths for the unified storage build.

    Parameters
    ----------
    project_root : pathlib.Path
        Repository root.
    output_path : pathlib.Path or None, optional
        Optional override for the dated unified GeoPackage output path.

    Returns
    -------
    BuildPaths
        Resolved build-path configuration.
    """
    raw_dir = project_root / "data" / "raw"

    province_boundary_path = (
        raw_dir
        / "basemaps"
        / "digital"
        / "lpr_000a21a_e.shp"
    )

    source_dir = project_root / "data" / "processed"

    source_files = {
        "AER": discover_latest_silver_gpkg(
            source_dir / "aer_agreements",
            data_type="AERCarbonSequestrationAgreements",
        ),
        "ATLANTIC": discover_latest_silver_gpkg(
            source_dir / "gsc_atlantic",
            data_type="AtlanticStorageCOS",
        ),
        "BC": discover_latest_silver_gpkg(
            source_dir / "gbc_ne_atlas",
            data_type="BCStorageAtlas",
        ),
        "NATCARB": discover_latest_silver_gpkg(
            source_dir / "natcarb_doe",
            data_type="NATCARBStorage",
        ),
    }

    final_output = output_path or (
        source_dir
        / "unified_storage"
        / UNIFIED_SUBMISSION_FILENAME
    )

    return BuildPaths(
        project_root=project_root,
        source_dir=source_dir,
        source_files=source_files,
        output_path=final_output,
        province_boundary_path=province_boundary_path,
    )


def validate_input_paths(paths: BuildPaths) -> None:
    """Validate that all required source datasets exist.

    Parameters
    ----------
    paths : BuildPaths
        Resolved paths for the unified build.

    Raises
    ------
    FileNotFoundError
        If any required precursor GeoPackage or province boundary dataset is
        missing.
    """
    missing = [
        path
        for path in [*paths.source_files.values(), paths.province_boundary_path]
        if not path.is_file()
    ]
    if missing:
        joined = "\n".join(f"  - {path}" for path in missing)
        raise FileNotFoundError(f"Required unified-atlas input(s) missing:\n{joined}")


# =============================================================================
# Generic helpers
# =============================================================================

def clean_key_value(value: Any) -> str | None:
    """Normalize a scalar value used in a source-derived identifier.

    Parameters
    ----------
    value : Any
        Scalar value to normalize.

    Returns
    -------
    str or None
        Uppercase stripped text, or ``None`` for null or blank values.
    """
    if pd.isna(value):
        return None

    text = str(value).strip()
    return text.upper() if text else None


def build_source_unit_key(components: list[object]) -> str:
    """Construct a pipe-delimited source-unit identity key.

    Parameters
    ----------
    components : list[object]
        Ordered identity components.

    Returns
    -------
    str
        Delimited key containing only non-null normalized components.
    """
    cleaned: list[str] = []
    for value in components:
        normalized = clean_key_value(value)
        if normalized is not None:
            cleaned.append(normalized)
    return "|".join(cleaned)


def stable_unit_id(prefix: str, source_unit_key: str) -> str:
    """Generate a stable compact identifier from a source-unit key.

    Parameters
    ----------
    prefix : str
        Dataset- and storage-class-specific identifier prefix.
    source_unit_key : str
        Canonical source-derived identity key.

    Returns
    -------
    str
        Prefix joined to the first 12 hexadecimal characters of the SHA-1 digest
        of ``source_unit_key``.
    """
    digest = hashlib.sha1(source_unit_key.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def conform_table(df: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    """Conform a table to an ordered canonical column contract.

    Parameters
    ----------
    df : pandas.DataFrame
        Input table.
    columns : tuple[str, ...]
        Required output columns in canonical order.

    Returns
    -------
    pandas.DataFrame
        Copy containing exactly the requested columns, with missing columns added
        as ``pandas.NA``.
    """
    result = df.copy()
    for column in columns:
        if column not in result.columns:
            result[column] = pd.NA
    return result.loc[:, list(columns)]


def enforce_storage_assessment_types(df: pd.DataFrame) -> pd.DataFrame:
    """Apply the canonical nullable numeric type contract to assessments.

    Quantitative storage-assessment fields are coerced with ``errors="coerce"``
    and stored using pandas' nullable ``Float64`` dtype. This prevents columns
    that are sparse or entirely missing for one source dataset from degrading to
    generic ``object``/TEXT when the unified GeoPackage is created.

    Parameters
    ----------
    df : pandas.DataFrame
        Canonical storage-assessment table.

    Returns
    -------
    pandas.DataFrame
        Copy with all quantitative assessment columns typed as nullable Float64.
    """
    result = df.copy()
    for column in STORAGE_ASSESSMENT_REAL_COLUMNS:
        result[column] = pd.to_numeric(result[column], errors="coerce").astype("Float64")
    return result


def conform_storage_features(df: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Conform a spatial table to the canonical storage-feature schema.

    Parameters
    ----------
    df : geopandas.GeoDataFrame
        Spatial feature table to conform.

    Returns
    -------
    geopandas.GeoDataFrame
        Canonical storage-feature table preserving the input CRS.
    """
    columns = CANONICAL_SCHEMAS["storage_features"]
    conformed = conform_table(df, columns)
    return gpd.GeoDataFrame(conformed, geometry="geometry", crs=df.crs)


def clean_field_types(series: pd.Series) -> list[str]:
    """Return normalized unique field-type labels from a series.

    Parameters
    ----------
    series : pandas.Series
        Source field-type values.

    Returns
    -------
    list[str]
        Sorted uppercase nonblank field-type labels.
    """
    return sorted(
        series.dropna()
        .astype("string")
        .str.strip()
        .str.upper()
        .loc[lambda values: values.ne("")]
        .unique()
        .tolist()
    )


def resolve_storage_subtype(series: pd.Series) -> str:
    """Resolve a canonical hydrocarbon storage subtype from field types.

    Parameters
    ----------
    series : pandas.Series
        Source field-type labels associated with one logical storage unit.

    Returns
    -------
    str
        Canonical subtype, including ``oil_reservoir``, ``gas_reservoir``,
        ``oil_and_gas_reservoir``, ``storage_reservoir``, or ``unknown``.
    """
    values = clean_field_types(series)
    if not values:
        return "unknown"
    if len(values) == 1:
        return FIELD_TYPE_TO_SUBTYPE.get(values[0], "unknown")
    hydrocarbon_values = set(values) & {"OIL", "GAS", "OIL & GAS"}
    if len(hydrocarbon_values) > 1:
        return "oil_and_gas_reservoir"
    return "unknown"


def join_field_types(series: pd.Series) -> object:
    """Join normalized field-type labels for diagnostic retention.

    Parameters
    ----------
    series : pandas.Series
        Source field-type labels.

    Returns
    -------
    object
        Pipe-delimited normalized labels, or ``pandas.NA`` when no values are
        present.
    """
    values = clean_field_types(series)
    return " | ".join(values) if values else pd.NA


def summarize_jurisdictions(joined: gpd.GeoDataFrame) -> pd.DataFrame:
    """Summarize province/territory intersections for NATCARB features.

    Parameters
    ----------
    joined : geopandas.GeoDataFrame
        Spatial-join output containing ``natcarb_id``, province codes, and province
        names.

    Returns
    -------
    pandas.DataFrame
        One row per NATCARB feature with jurisdiction codes, names, count, method,
        and cross-jurisdiction flag.
    """
    summary = (
        joined.groupby("natcarb_id", dropna=False)
        .agg(
            province_codes=(
                "province",
                lambda s: ",".join(sorted(s.dropna().astype(str).unique())),
            ),
            province_names=(
                "province_name",
                lambda s: " | ".join(sorted(s.dropna().astype(str).unique())),
            ),
            province_count=("province", lambda s: s.dropna().nunique()),
        )
        .reset_index()
    )
    summary["jurisdiction_method"] = "spatial_intersection"
    summary["cross_jurisdiction"] = summary["province_count"] > 1
    return summary


def aggregate_province_codes(series: pd.Series) -> str:
    """Aggregate comma-delimited province codes into a unique sorted string.

    Parameters
    ----------
    series : pandas.Series
        Province-code values, potentially containing comma-delimited entries.

    Returns
    -------
    str
        Comma-delimited unique province/territory codes in sorted order.
    """
    codes = {
        code
        for value in series.dropna()
        for code in str(value).split(",")
        if code
    }
    return ",".join(sorted(codes))


def validate_primary_key(df: pd.DataFrame, column: str, table_name: str) -> None:
    """Validate non-null uniqueness of a table primary key.

    Parameters
    ----------
    df : pandas.DataFrame
        Table containing the key.
    column : str
        Primary-key column name.
    table_name : str
        Human-readable table name used in error messages.

    Raises
    ------
    ValueError
        If the key contains null or duplicate values.
    """
    if df[column].isna().any():
        raise ValueError(f"{table_name} contains missing {column} values.")
    if df[column].duplicated().any():
        raise ValueError(f"{table_name} contains duplicate {column} values.")


# =============================================================================
# NATCARB identity construction and Canadian subset
# =============================================================================


def build_saline_unit_key(row: pd.Series) -> pd.Series:
    """Build the NATCARB saline logical-unit identity for one source row.

    Parameters
    ----------
    row : pandas.Series
        NATCARB saline source record.

    Returns
    -------
    pandas.Series
        ``source_unit_id``, stable ``storage_unit_id``, and the applied
        ``unit_identity_rule``.
    """
    partnership = clean_key_value(row.get("partnership"))
    resource_name = clean_key_value(row.get("resource_name"))
    basin_name = clean_key_value(row.get("basin_name"))

    if resource_name is None:
        return pd.Series(
            {
                "source_unit_id": pd.NA,
                "storage_unit_id": pd.NA,
                "unit_identity_rule": "missing_resource_name",
            }
        )

    if basin_name is not None:
        identity_rule = "partnership_basin_resource"
        components = [
            "NATCARB", partnership, "SALINE", basin_name, resource_name
        ]
    else:
        identity_rule = "partnership_resource"
        components = ["NATCARB", partnership, "SALINE", resource_name]

    source_unit_id = build_source_unit_key(components)
    return pd.Series(
        {
            "source_unit_id": source_unit_id,
            "storage_unit_id": stable_unit_id("NAT_SAL", source_unit_id),
            "unit_identity_rule": identity_rule,
        }
    )


def build_coal_unit_key(row: pd.Series) -> pd.Series:
    """Build the NATCARB coal logical-unit identity for one source row.

    Parameters
    ----------
    row : pandas.Series
        NATCARB coal source record.

    Returns
    -------
    pandas.Series
        ``source_unit_id``, stable ``storage_unit_id``, and the applied
        ``unit_identity_rule``.
    """
    partnership = clean_key_value(row.get("partnership"))
    resource_name = clean_key_value(row.get("resource_name"))

    if resource_name is None:
        return pd.Series(
            {
                "source_unit_id": pd.NA,
                "storage_unit_id": pd.NA,
                "unit_identity_rule": "missing_resource_name",
            }
        )

    source_unit_id = build_source_unit_key(
        ["NATCARB", partnership, "COAL", resource_name]
    )
    return pd.Series(
        {
            "source_unit_id": source_unit_id,
            "storage_unit_id": stable_unit_id("NAT_COAL", source_unit_id),
            "unit_identity_rule": "partnership_resource",
        }
    )


def build_oil_gas_unit_key(row: pd.Series) -> pd.Series:
    """Build the NATCARB oil-and-gas logical-unit identity for one source row.

    Parameters
    ----------
    row : pandas.Series
        NATCARB oil-and-gas source record.

    Returns
    -------
    pandas.Series
        ``source_unit_id``, stable ``storage_unit_id``, and the applied
        ``unit_identity_rule``.
    """
    partnership = clean_key_value(row.get("partnership"))
    field_name = clean_key_value(row.get("field_name"))
    reservoir_name = clean_key_value(row.get("reservoir_name"))
    reservoir_number = clean_key_value(row.get("reservoir_number"))

    if field_name is None:
        return pd.Series(
            {
                "source_unit_id": pd.NA,
                "storage_unit_id": pd.NA,
                "unit_identity_rule": "missing_field_name",
            }
        )

    if reservoir_number is not None:
        identity_rule = "partnership_field_reservoir_number"
        components = [
            "NATCARB", partnership, "OIL_GAS", field_name, reservoir_number
        ]
    elif reservoir_name is not None:
        identity_rule = "partnership_field_reservoir_name"
        components = [
            "NATCARB", partnership, "OIL_GAS", field_name, reservoir_name
        ]
    else:
        identity_rule = "partnership_field"
        components = ["NATCARB", partnership, "OIL_GAS", field_name]

    source_unit_id = build_source_unit_key(components)
    return pd.Series(
        {
            "source_unit_id": source_unit_id,
            "storage_unit_id": stable_unit_id("NAT_OG", source_unit_id),
            "unit_identity_rule": identity_rule,
        }
    )


def load_province_boundaries(path: Path) -> gpd.GeoDataFrame:
    """Load and normalize Canadian province and territory boundaries.

    Parameters
    ----------
    path : pathlib.Path
        Boundary dataset containing ``PRUID``, ``PRENAME``, and geometry.

    Returns
    -------
    geopandas.GeoDataFrame
        Boundaries reprojected to ``WORKING_CRS`` with standardized province codes
        and names.

    Raises
    ------
    ValueError
        If required fields are missing or a PRUID cannot be mapped.
    """
    provinces = gpd.read_file(path)
    required = {"PRUID", "PRENAME", "geometry"}
    missing = required - set(provinces.columns)
    if missing:
        raise ValueError(
            "Province boundary file is missing Notebook 12 fields: "
            f"{sorted(missing)}"
        )

    provinces = (
        provinces[["PRUID", "PRENAME", "geometry"]]
        .rename(columns={"PRENAME": "province_name"})
        .to_crs(WORKING_CRS)
        .copy()
    )
    provinces["province"] = (
        provinces["PRUID"].astype("string").map(PRUID_TO_CODE)
    )
    if provinces["province"].isna().any():
        raise ValueError(
            "One or more province/territory PRUID values were not mapped."
        )
    return provinces


def load_canadian_natcarb(
    natcarb_path: Path,
    provinces: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Load NATCARB storage layers and retain their Canadian subset.

    Parameters
    ----------
    natcarb_path : pathlib.Path
        NATCARB Silver GeoPackage.
    provinces : geopandas.GeoDataFrame
        Standardized Canadian province and territory boundaries.

    Returns
    -------
    tuple[geopandas.GeoDataFrame, geopandas.GeoDataFrame, geopandas.GeoDataFrame]
        Canadian saline, coal, and oil-and-gas NATCARB features with jurisdiction
        and stable logical-unit identifiers attached.
    """
    saline = gpd.read_file(natcarb_path, layer="saline_resource_cells").to_crs(
        WORKING_CRS
    )
    coal = gpd.read_file(natcarb_path, layer="coal_resource_cells").to_crs(
        WORKING_CRS
    )
    oil_gas = gpd.read_file(natcarb_path, layer="oil_gas_resources").to_crs(
        WORKING_CRS
    )

    canada_mask = provinces[["geometry"]].dissolve()
    province_lookup = provinces[["province", "province_name", "geometry"]].copy()

    saline_canada = gpd.sjoin(
        saline, canada_mask, how="inner", predicate="intersects"
    ).drop(columns="index_right", errors="ignore")
    coal_canada = gpd.sjoin(
        coal, canada_mask, how="inner", predicate="intersects"
    ).drop(columns="index_right", errors="ignore")

    saline_geo = summarize_jurisdictions(
        gpd.sjoin(
            saline_canada,
            province_lookup,
            how="left",
            predicate="intersects",
        )
    )
    coal_geo = summarize_jurisdictions(
        gpd.sjoin(
            coal_canada,
            province_lookup,
            how="left",
            predicate="intersects",
        )
    )

    saline_canada = saline_canada.merge(
        saline_geo, on="natcarb_id", how="left", validate="one_to_one"
    )
    coal_canada = coal_canada.merge(
        coal_geo, on="natcarb_id", how="left", validate="one_to_one"
    )

    oil_gas_canada = oil_gas.loc[
        oil_gas["state_source"]
        .astype("string")
        .str.strip()
        .str.upper()
        .isin(CANADIAN_PROVINCE_TERRITORY_CODES)
    ].copy()
    oil_gas_canada["province_codes"] = (
        oil_gas_canada["state_source"]
        .astype("string")
        .str.strip()
        .str.upper()
    )
    oil_gas_canada["province_count"] = 1
    oil_gas_canada["cross_jurisdiction"] = False
    oil_gas_canada["jurisdiction_method"] = "source_reported"

    saline_canada[["source_unit_id", "storage_unit_id", "unit_identity_rule"]] = (
        saline_canada.apply(build_saline_unit_key, axis=1)
    )
    coal_canada[["source_unit_id", "storage_unit_id", "unit_identity_rule"]] = (
        coal_canada.apply(build_coal_unit_key, axis=1)
    )
    oil_gas_canada[
        ["source_unit_id", "storage_unit_id", "unit_identity_rule"]
    ] = oil_gas_canada.apply(build_oil_gas_unit_key, axis=1)

    return saline_canada, coal_canada, oil_gas_canada


# =============================================================================
# Canonical storage units
# =============================================================================


def build_natcarb_storage_units(
    saline: gpd.GeoDataFrame,
    coal: gpd.GeoDataFrame,
    oil_gas: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """Construct canonical logical storage units from Canadian NATCARB data.

    Parameters
    ----------
    saline : geopandas.GeoDataFrame
        Canadian NATCARB saline features.
    coal : geopandas.GeoDataFrame
        Canadian NATCARB coal features.
    oil_gas : geopandas.GeoDataFrame
        Canadian NATCARB oil-and-gas features.

    Returns
    -------
    pandas.DataFrame
        Canonical NATCARB ``storage_units`` records.
    """
    saline_units = (
        saline.groupby("storage_unit_id", dropna=False)
        .agg(
            source_unit_id=("source_unit_id", "first"),
            storage_name=("resource_name", "first"),
            basin_name=("basin_name", "first"),
            assessment_type=("assessment_type", "first"),
            data_class=("data_class", "first"),
            capacity_data=("capacity_data", "first"),
            injectivity_status=("injectivity_status", "first"),
            province_territory=("province_codes", aggregate_province_codes),
        )
        .reset_index()
    )

    saline_units["source_dataset"] = "NATCARB"
    saline_units["storage_type"] = "saline_aquifer"
    saline_units["storage_subtype"] = pd.NA
    saline_units["formation"] = pd.NA
    saline_units["geological_group"] = pd.NA
    saline_units["country"] = "Canada"
    saline_units["land_status"] = pd.NA
    saline_units["capacity_status"] = "reported"
    saline_units["co2_phase"] = pd.NA

    coal_units = (
        coal.groupby("storage_unit_id", dropna=False)
        .agg(
            source_unit_id=("source_unit_id", "first"),
            storage_name=("resource_name", "first"),
            assessment_type=("assessment_type", "first"),
            data_class=("data_class", "first"),
            capacity_data=("capacity_data", "first"),
            injectivity_status=("injectivity_status", "first"),
            province_territory=("province_codes", aggregate_province_codes),
        )
        .reset_index()
    )

    coal_units["source_dataset"] = "NATCARB"
    coal_units["storage_type"] = "coal"
    coal_units["storage_subtype"] = pd.NA
    coal_units["formation"] = pd.NA
    coal_units["geological_group"] = pd.NA
    coal_units["basin_name"] = pd.NA
    coal_units["country"] = "Canada"
    coal_units["land_status"] = pd.NA
    coal_units["capacity_status"] = "reported"
    coal_units["co2_phase"] = pd.NA

    subtype = (
        oil_gas.groupby("storage_unit_id", dropna=False)
        .agg(
            storage_subtype=("field_type", resolve_storage_subtype),
            field_type_values=("field_type", join_field_types),
        )
        .reset_index()
    )
    oil_gas_units = (
        oil_gas.groupby("storage_unit_id", dropna=False)
        .agg(
            source_unit_id=("source_unit_id", "first"),
            storage_name=("field_name", "first"),
            assessment_type=("assessment_type", "first"),
            data_class=("data_class", "first"),
            capacity_data=("capacity_data", "first"),
            injectivity_status=("injectivity_status", "first"),
            province_territory=("province_codes", "first"),
        )
        .reset_index()
        .merge(
            subtype[["storage_unit_id", "storage_subtype"]],
            on="storage_unit_id",
            how="left",
            validate="one_to_one",
        )
    )

    oil_gas_units["source_dataset"] = "NATCARB"
    oil_gas_units["storage_type"] = "depleted_hydrocarbon_reservoir"
    oil_gas_units["formation"] = pd.NA
    oil_gas_units["geological_group"] = pd.NA
    oil_gas_units["basin_name"] = pd.NA
    oil_gas_units["country"] = "Canada"
    oil_gas_units["land_status"] = pd.NA
    oil_gas_units["capacity_status"] = "reported"
    oil_gas_units["co2_phase"] = pd.NA

    combined = pd.concat(
        [saline_units, coal_units, oil_gas_units],
        ignore_index=True,
        sort=False,
    )
    combined = conform_table(combined, CANONICAL_SCHEMAS["storage_units"])
    validate_primary_key(combined, "storage_unit_id", "NATCARB storage_units")
    return combined


def build_bc_storage_units(bc_path: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Construct canonical storage units from the Northeast BC storage atlas.

    Parameters
    ----------
    bc_path : pathlib.Path
        BC Silver GeoPackage.

    Returns
    -------
    tuple[pandas.DataFrame, pandas.DataFrame, pandas.DataFrame]
        Canonical BC storage units, source aquifer-unit table, and source pool-unit
        table.
    """
    aquifers = gpd.read_file(bc_path, layer="aquifer_units", ignore_geometry=True)
    pools = gpd.read_file(bc_path, layer="pool_units", ignore_geometry=True)

    aquifer_units = pd.DataFrame(
        {
            "storage_unit_id": "BC_AQ_" + aquifers["storage_unit_id"].astype("string"),
            "source_dataset": "BC_STORAGE_ATLAS",
            "source_unit_id": aquifers["storage_unit_id"].astype("string"),
            "storage_type": "saline_aquifer",
            "storage_subtype": aquifers["aquifer_type"].astype("string").str.strip(),
            "storage_name": aquifers["aquifer_name"],
            "formation": aquifers["formation"],
            "geological_group": pd.NA,
            "basin_name": pd.NA,
            "country": "Canada",
            "province_territory": "British Columbia",
            "land_status": pd.NA,
            "assessment_type": aquifers["assessment_type"],
            "data_class": aquifers["data_class"],
            "capacity_data": aquifers["capacity_data"],
            "capacity_status": "reported",
            "injectivity_status": pd.NA,
            "co2_phase": aquifers["co2_phase"],
        }
    )

    pool_units = pd.DataFrame(
        {
            "storage_unit_id": "BC_POOL_" + pools["storage_unit_id"].astype("string"),
            "source_dataset": "BC_STORAGE_ATLAS",
            "source_unit_id": pools["storage_unit_id"].astype("string"),
            "storage_type": "depleted_hydrocarbon_reservoir",
            "storage_subtype": pools["pool_type"].astype("string").str.strip(),
            "storage_name": pools["pool_name"],
            "formation": pools["formation"],
            "geological_group": pd.NA,
            "basin_name": pd.NA,
            "country": "Canada",
            "province_territory": "British Columbia",
            "land_status": pd.NA,
            "assessment_type": pools["assessment_type"],
            "data_class": pools["data_class"],
            "capacity_data": pools["capacity_data"],
            "capacity_status": "reported",
            "injectivity_status": pd.NA,
            "co2_phase": pools["co2_phase"],
        }
    )

    combined = pd.concat([aquifer_units, pool_units], ignore_index=True)
    combined = conform_table(combined, CANONICAL_SCHEMAS["storage_units"])
    return combined, aquifers, pools


def build_atlantic_storage_units(
    atlantic_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Construct canonical logical units from Atlantic prospectivity data.

    Parameters
    ----------
    atlantic_path : pathlib.Path
        Atlantic Silver GeoPackage.

    Returns
    -------
    tuple[pandas.DataFrame, pandas.DataFrame]
        Canonical Atlantic storage units and the source nonspatial table used
        to construct them.
    """
    source = gpd.read_file(
        atlantic_path,
        layer="storage_units",
        ignore_geometry=True,
    )

    base = (
        source.groupby("storage_unit_id", dropna=False)
        .agg(
            storage_name=("storage_unit_name", "first"),
            geological_group=("geological_group", "first"),
            assessment_type=("assessment_type", "first"),
            data_class=("data_class", "first"),
            capacity_data=("capacity_data", "first"),
            capacity_status=("capacity_status", "first"),
            injectivity_status=("injectivity_status", "first"),
        )
        .reset_index()
    )

    base["source_unit_id"] = base["storage_unit_id"].astype("string")
    base["storage_unit_id"] = "ATL_" + base["source_unit_id"]

    base["source_dataset"] = "ATLANTIC_COS"
    base["storage_type"] = pd.NA
    base["storage_subtype"] = pd.NA
    base["formation"] = pd.NA
    base["basin_name"] = pd.NA
    base["country"] = "Canada"
    base["province_territory"] = pd.NA
    base["land_status"] = pd.NA
    base["co2_phase"] = pd.NA

    combined = conform_table(
        base,
        CANONICAL_SCHEMAS["storage_units"],
    )

    return combined, source


# =============================================================================
# Canonical storage features
# =============================================================================


def build_natcarb_storage_features(
    saline: gpd.GeoDataFrame,
    coal: gpd.GeoDataFrame,
    oil_gas: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Construct canonical spatial storage features from NATCARB data.

    Parameters
    ----------
    saline : geopandas.GeoDataFrame
        Canadian NATCARB saline features.
    coal : geopandas.GeoDataFrame
        Canadian NATCARB coal features.
    oil_gas : geopandas.GeoDataFrame
        Canadian NATCARB oil-and-gas features.

    Returns
    -------
    geopandas.GeoDataFrame
        Canonical NATCARB ``storage_features`` records in ``WORKING_CRS``.
    """
    saline_features = saline.copy()
    saline_features["storage_feature_id"] = (
        "NATCARB_SALINE_" + saline_features["natcarb_id"].astype("string")
    )
    saline_features["source_dataset"] = "NATCARB"
    saline_features["source_layer"] = "saline_resource_cells"
    saline_features["source_feature_id"] = saline_features["natcarb_id"].astype("string")
    saline_features["storage_type"] = "saline_aquifer"
    saline_features["storage_subtype"] = pd.NA
    saline_features["representation"] = "resource_grid_cell"
    saline_features["country"] = "Canada"
    saline_features["province_territory"] = saline_features["province_codes"]

    coal_features = coal.copy()
    coal_features["storage_feature_id"] = (
        "NATCARB_COAL_" + coal_features["natcarb_id"].astype("string")
    )
    coal_features["source_dataset"] = "NATCARB"
    coal_features["source_layer"] = "coal_resource_cells"
    coal_features["source_feature_id"] = coal_features["natcarb_id"].astype("string")
    coal_features["storage_type"] = "coal"
    coal_features["storage_subtype"] = pd.NA
    coal_features["representation"] = "resource_grid_cell"
    coal_features["country"] = "Canada"
    coal_features["province_territory"] = coal_features["province_codes"]

    oil_gas_features = oil_gas.copy()
    oil_gas_features["storage_feature_id"] = (
        "NATCARB_OILGAS_" + oil_gas_features["natcarb_id"].astype("string")
    )
    oil_gas_features["source_dataset"] = "NATCARB"
    oil_gas_features["source_layer"] = "oil_gas_resources"
    oil_gas_features["source_feature_id"] = oil_gas_features["natcarb_id"].astype("string")
    oil_gas_features["storage_type"] = "depleted_hydrocarbon_reservoir"
    oil_gas_features["representation"] = "storage_resource"
    oil_gas_features["country"] = "Canada"
    oil_gas_features["province_territory"] = oil_gas_features["province_codes"]

    frames = [
        conform_storage_features(saline_features),
        conform_storage_features(coal_features),
        conform_storage_features(oil_gas_features),
    ]
    combined = gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True),
        geometry="geometry",
        crs=WORKING_CRS,
    )
    validate_primary_key(combined, "storage_feature_id", "NATCARB storage_features")
    return combined


def build_bc_storage_features(bc_path: Path) -> gpd.GeoDataFrame:
    """Construct canonical spatial features from the Northeast BC storage atlas.

    Parameters
    ----------
    bc_path : pathlib.Path
        BC Silver GeoPackage.

    Returns
    -------
    geopandas.GeoDataFrame
        Canonical BC aquifer and pool spatial features in ``WORKING_CRS``.
    """
    aquifers = gpd.read_file(bc_path, layer="aquifer_features").to_crs(WORKING_CRS)
    pools = gpd.read_file(bc_path, layer="pool_features").to_crs(WORKING_CRS)

    for frame, prefix, feature_prefix, source_layer, storage_type, representation in [
        (
            aquifers,
            "BC_AQ_",
            "BC_AQ_FEATURE_",
            "aquifer_features",
            "saline_aquifer",
            "aquifer_extent",
        ),
        (
            pools,
            "BC_POOL_",
            "BC_POOL_FEATURE_",
            "pool_features",
            "depleted_hydrocarbon_reservoir",
            "pool_extent",
        ),
    ]:
        source_unit_id = frame["storage_unit_id"].astype("string")
        # Notebook 12 first created the source-facing feature identifier from the
        # unprefixed BC storage-unit ID, then constructed the final canonical
        # storage_feature_id after the storage_unit_id prefix was applied.
        frame["storage_feature_id"] = feature_prefix + source_unit_id
        frame["storage_unit_id"] = prefix + source_unit_id
        frame["source_dataset"] = "BC_STORAGE_ATLAS"
        frame["source_layer"] = source_layer
        frame["source_feature_id"] = frame["storage_feature_id"].astype("string")
        frame["storage_feature_id"] = (
            feature_prefix
            + frame["storage_unit_id"].astype("string")
            + "_"
            + frame["source_feature_order"].astype("string")
        )
        frame["storage_type"] = storage_type
        frame["representation"] = representation
        frame["country"] = "Canada"
        frame["province_territory"] = "BC"

    combined = gpd.GeoDataFrame(
        pd.concat(
            [conform_storage_features(aquifers), conform_storage_features(pools)],
            ignore_index=True,
        ),
        geometry="geometry",
        crs=WORKING_CRS,
    )
    validate_primary_key(combined, "storage_feature_id", "BC storage_features")
    return combined


def build_atlantic_storage_features(atlantic_path: Path) -> gpd.GeoDataFrame:
    """Construct canonical spatial features from Atlantic prospectivity polygons.

    Parameters
    ----------
    atlantic_path : pathlib.Path
        Atlantic Silver GeoPackage.

    Returns
    -------
    geopandas.GeoDataFrame
        Canonical Atlantic prospectivity polygons in ``WORKING_CRS``.
    """
    source = gpd.read_file(atlantic_path, layer="storage_units").to_crs(WORKING_CRS)
    source["storage_feature_id"] = "ATL_FEATURE_" + source["feature_id"].astype("string")
    source["storage_unit_id"] = "ATL_" + source["storage_unit_id"].astype("string")
    source["source_dataset"] = "ATLANTIC_COS"
    source["source_layer"] = "storage_units"
    source["storage_type"] = pd.NA
    source["storage_subtype"] = pd.NA
    source["representation"] = "prospectivity_polygon"
    source["country"] = "Canada"
    # Older Atlantic Silver packages predate the standard geometry-measure
    # fields. Calculate them from the canonical projected geometry so unified
    # builds remain complete when consuming those packages.
    source["geometry_area_m2"] = source.geometry.area
    source["geometry_area_ha"] = source["geometry_area_m2"] / 10_000.0
    source["geometry_perimeter_m"] = source.geometry.length
    combined = conform_storage_features(source)
    validate_primary_key(combined, "storage_feature_id", "Atlantic storage_features")
    return combined


# =============================================================================
# Canonical storage assessments
# =============================================================================


def build_natcarb_storage_assessments(
    saline: gpd.GeoDataFrame,
    coal: gpd.GeoDataFrame,
    oil_gas: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """Construct canonical feature-scoped NATCARB storage assessments.

    Parameters
    ----------
    saline : geopandas.GeoDataFrame
        Canadian NATCARB saline features.
    coal : geopandas.GeoDataFrame
        Canadian NATCARB coal features.
    oil_gas : geopandas.GeoDataFrame
        Canadian NATCARB oil-and-gas features.

    Returns
    -------
    pandas.DataFrame
        Canonical NATCARB ``storage_assessments`` records.
    """
    frames: list[pd.DataFrame] = []
    definitions = [
        (saline, "NATCARB_SALINE_ASSESS_", "NATCARB_SALINE_", "saline_resource_cells"),
        (coal, "NATCARB_COAL_ASSESS_", "NATCARB_COAL_", "coal_resource_cells"),
        (oil_gas, "NATCARB_OILGAS_ASSESS_", "NATCARB_OILGAS_", "oil_gas_resources"),
    ]
    for source, assessment_prefix, feature_prefix, source_layer in definitions:
        frame = source.copy()
        frame["storage_assessment_id"] = assessment_prefix + frame["natcarb_id"].astype("string")
        frame["storage_feature_id"] = feature_prefix + frame["natcarb_id"].astype("string")
        frame["source_dataset"] = "NATCARB"
        frame["source_layer"] = source_layer
        frame["assessment_scope"] = "feature"
        frames.append(conform_table(frame, CANONICAL_SCHEMAS["storage_assessments"]))
    combined = pd.concat(frames, ignore_index=True)
    validate_primary_key(combined, "storage_assessment_id", "NATCARB storage_assessments")
    return combined


def build_bc_storage_assessments(
    aquifers: pd.DataFrame,
    pools: pd.DataFrame,
) -> pd.DataFrame:
    """Construct unit-scoped BC storage assessments.

    Parameters
    ----------
    aquifers : pandas.DataFrame
        Source BC aquifer-unit table.
    pools : pandas.DataFrame
        Source BC pool-unit table.

    Returns
    -------
    pandas.DataFrame
        Canonical BC assessment records with source capacity values converted to
        canonical units where required.
    """
    aq = aquifers.copy()
    aq["source_storage_unit_id"] = aq["storage_unit_id"].astype("string")
    aq["storage_unit_id"] = "BC_AQ_" + aq["source_storage_unit_id"]
    aq["storage_assessment_id"] = "BC_AQ_ASSESS_" + aq["source_storage_unit_id"]
    aq["storage_feature_id"] = pd.NA
    aq["source_dataset"] = "BC_STORAGE_ATLAS"
    aq["source_layer"] = "aquifer_units"
    aq["assessment_scope"] = "unit"
    aq["storage_p10_tonnes"] = aq["p10_effective_storage_mt"] * 1_000_000
    aq["storage_p50_tonnes"] = aq["p50_effective_storage_mt"] * 1_000_000
    aq["storage_p90_tonnes"] = aq["p90_effective_storage_mt"] * 1_000_000
    aq["theoretical_storage_tonnes"] = aq["theoretical_storage_mt"] * 1_000_000
    aq["capacity_method"] = aq["theoretical_storage_method"]

    pool = pools.copy()
    pool["source_storage_unit_id"] = pool["storage_unit_id"].astype("string")
    pool["storage_unit_id"] = "BC_POOL_" + pool["source_storage_unit_id"]
    pool["storage_assessment_id"] = "BC_POOL_ASSESS_" + pool["source_storage_unit_id"]
    pool["storage_feature_id"] = pd.NA
    pool["source_dataset"] = "BC_STORAGE_ATLAS"
    pool["source_layer"] = "pool_units"
    pool["assessment_scope"] = "unit"
    pool["theoretical_storage_tonnes"] = pool["theoretical_storage_mt"] * 1_000_000
    pool["effective_storage_tonnes"] = pool["effective_storage_mt"] * 1_000_000
    pool["pressure_mpa"] = pool["initial_pressure_kpa"] / 1000

    combined = pd.concat(
        [
            conform_table(aq, CANONICAL_SCHEMAS["storage_assessments"]),
            conform_table(pool, CANONICAL_SCHEMAS["storage_assessments"]),
        ],
        ignore_index=True,
    )
    validate_primary_key(combined, "storage_assessment_id", "BC storage_assessments")
    return combined


def build_atlantic_storage_assessments(atlantic_path: Path) -> pd.DataFrame:
    """Construct feature-scoped Atlantic prospectivity assessments.

    Parameters
    ----------
    atlantic_path : pathlib.Path
        Atlantic Silver GeoPackage.

    Returns
    -------
    pandas.DataFrame
        Canonical Atlantic assessment records.
    """
    source = gpd.read_file(atlantic_path, layer="storage_units").to_crs(WORKING_CRS)
    source["storage_feature_id"] = "ATL_FEATURE_" + source["feature_id"].astype("string")
    source["storage_unit_id"] = "ATL_" + source["storage_unit_id"].astype("string")
    source["storage_assessment_id"] = "ATL_ASSESS_" + source["feature_id"].astype("string")
    source["source_dataset"] = "ATLANTIC_COS"
    source["source_layer"] = "storage_units"
    source["assessment_scope"] = "feature"
    combined = conform_table(source, CANONICAL_SCHEMAS["storage_assessments"])
    validate_primary_key(combined, "storage_assessment_id", "Atlantic storage_assessments")
    return combined


# =============================================================================
# Administrative features
# =============================================================================


def build_administrative_features(aer_path: Path) -> gpd.GeoDataFrame:
    """Construct canonical AER agreement and tract administrative features.

    Parameters
    ----------
    aer_path : pathlib.Path
        AER carbon-sequestration-agreement Silver GeoPackage.

    Returns
    -------
    geopandas.GeoDataFrame
        Agreement and tract features conformed to the canonical administrative
        schema in ``WORKING_CRS``.
    """
    agreements = gpd.read_file(aer_path, layer="aer_agreements").to_crs(WORKING_CRS)
    tracts = gpd.read_file(aer_path, layer="aer_agreement_tracts").to_crs(WORKING_CRS)

    agreement_features = agreements.copy()
    agreement_features["administrative_feature_id"] = (
        "AER_AGREEMENT_" + agreement_features["agreement_id"].astype("string")
    )
    agreement_features["parent_administrative_feature_id"] = pd.NA
    agreement_features["source_layer"] = "aer_agreements"
    agreement_features["source_feature_id"] = agreement_features["agreement_id"].astype("string")
    agreement_features["administrative_type"] = "carbon_sequestration_agreement"
    agreement_features["tract_id"] = pd.NA
    agreement_features["province_territory"] = "AB"

    tract_features = tracts.copy()
    tract_features["administrative_feature_id"] = (
        "AER_TRACT_" + tract_features["source_feature_uid"].astype("string")
    )
    tract_features["parent_administrative_feature_id"] = (
        "AER_AGREEMENT_" + tract_features["agreement_id"].astype("string")
    )
    tract_features["source_layer"] = "aer_agreement_tracts"
    tract_features["source_feature_id"] = tract_features["source_feature_uid"].astype("string")
    tract_features["administrative_type"] = "carbon_sequestration_agreement_tract"
    tract_features["tract_count"] = 1
    tract_features["province_territory"] = "AB"

    for column in ADMINISTRATIVE_COLUMNS:
        if column not in agreement_features.columns:
            agreement_features[column] = pd.NA
        if column not in tract_features.columns:
            tract_features[column] = pd.NA

    combined = gpd.GeoDataFrame(
        pd.concat(
            [
                agreement_features.loc[:, list(ADMINISTRATIVE_COLUMNS)],
                tract_features.loc[:, list(ADMINISTRATIVE_COLUMNS)],
            ],
            ignore_index=True,
        ),
        geometry="geometry",
        crs=WORKING_CRS,
    )
    validate_primary_key(
        combined,
        "administrative_feature_id",
        "administrative_features",
    )
    return combined


# =============================================================================
# Build and validate the four-table canonical database
# =============================================================================


def validate_canonical_tables(tables: UnifiedTables) -> None:
    """Validate relational, spatial, and semantic integrity of canonical tables.

    Parameters
    ----------
    tables : UnifiedTables
        In-memory canonical tables to validate.

    Raises
    ------
    ValueError
        If primary keys, relationships, CRS, geometry, assessment scope, bounded
        fractions, or P10/P50/P90 monotonicity checks fail.
    """
    validate_primary_key(tables.storage_units, "storage_unit_id", "storage_units")
    validate_primary_key(tables.storage_features, "storage_feature_id", "storage_features")
    validate_primary_key(
        tables.storage_assessments,
        "storage_assessment_id",
        "storage_assessments",
    )
    validate_primary_key(
        tables.administrative_features,
        "administrative_feature_id",
        "administrative_features",
    )

    valid_units = set(tables.storage_units["storage_unit_id"])
    valid_features = set(tables.storage_features["storage_feature_id"])
    valid_admin = set(tables.administrative_features["administrative_feature_id"])

    if (~tables.storage_features["storage_unit_id"].isin(valid_units)).any():
        raise ValueError("storage_features contains invalid storage_unit_id links.")
    if (~tables.storage_assessments["storage_unit_id"].isin(valid_units)).any():
        raise ValueError("storage_assessments contains invalid storage_unit_id links.")

    feature_scoped = tables.storage_assessments["assessment_scope"].eq("feature")
    invalid_feature_links = (
        feature_scoped
        & ~tables.storage_assessments["storage_feature_id"].isin(valid_features)
    )
    if invalid_feature_links.any():
        raise ValueError(
            "Feature-scoped storage_assessments contains invalid storage_feature_id links."
        )

    parent = tables.administrative_features["parent_administrative_feature_id"]
    invalid_parent = parent.notna() & ~parent.isin(valid_admin)
    if invalid_parent.any():
        raise ValueError("administrative_features contains invalid parent links.")

    for name, gdf in {
        "storage_features": tables.storage_features,
        "administrative_features": tables.administrative_features,
    }.items():
        try:
            validate_target_crs(gdf, target_crs=WORKING_CRS)
        except ValueError as exc:
            raise ValueError(f"{name} must use {WORKING_CRS}.") from exc
        if gdf.geometry.isna().any():
            raise ValueError(f"{name} contains missing geometry.")
        if gdf.geometry.is_empty.any():
            raise ValueError(f"{name} contains empty geometry.")
        if (~gdf.geometry.is_valid).any():
            raise ValueError(f"{name} contains invalid geometry.")

    expected_geometry_measures = {
        "geometry_area_m2": tables.storage_features.geometry.area,
        "geometry_area_ha": tables.storage_features.geometry.area / 10_000.0,
        "geometry_perimeter_m": tables.storage_features.geometry.length,
    }
    for column, expected in expected_geometry_measures.items():
        values = pd.to_numeric(tables.storage_features[column], errors="coerce")
        if values.isna().any():
            raise ValueError(f"storage_features contains missing {column} values.")
        if (values <= 0).any():
            raise ValueError(f"storage_features contains non-positive {column} values.")
        tolerance = expected.abs() * 1e-9 + 1e-6
        if ((values - expected).abs() > tolerance).any():
            raise ValueError(
                f"storage_features contains {column} values inconsistent with "
                f"its {WORKING_CRS} geometry."
            )

    incorrectly_typed = [
        column
        for column in STORAGE_ASSESSMENT_REAL_COLUMNS
        if not pd.api.types.is_float_dtype(tables.storage_assessments[column].dtype)
    ]
    if incorrectly_typed:
        raise ValueError(
            "storage_assessments quantitative columns must be floating-point: "
            f"{incorrectly_typed}"
        )

    # Notebook 12 semantic checks retained without tightening their scope.
    unsupported_scope = ~tables.storage_assessments["assessment_scope"].isin(
        ["feature", "unit"]
    )
    if unsupported_scope.any():
        raise ValueError("storage_assessments contains unsupported assessment_scope.")

    fraction_columns = [
        "porosity_fraction",
        "reservoir_cos",
        "seal_cos",
        "trap_cos",
        "total_cos",
    ]
    for column in fraction_columns:
        values = pd.to_numeric(tables.storage_assessments[column], errors="coerce")
        invalid = values.notna() & ~values.between(0, 1, inclusive="both")
        if invalid.any():
            raise ValueError(f"{column} contains value(s) outside [0, 1].")

    p10 = pd.to_numeric(tables.storage_assessments["storage_p10_tonnes"], errors="coerce")
    p50 = pd.to_numeric(tables.storage_assessments["storage_p50_tonnes"], errors="coerce")
    p90 = pd.to_numeric(tables.storage_assessments["storage_p90_tonnes"], errors="coerce")
    complete = p10.notna() & p50.notna() & p90.notna()
    ascending = complete & (p10 <= p50) & (p50 <= p90)
    descending = complete & (p10 >= p50) & (p50 >= p90)
    if (complete & ~(ascending | descending)).any():
        raise ValueError("Non-monotonic P10/P50/P90 triplet(s) detected.")


def build_unified_tables(paths: BuildPaths) -> UnifiedTables:
    """Build and validate the four canonical unified storage tables.

    Parameters
    ----------
    paths : BuildPaths
        Resolved source, boundary, and output paths.

    Returns
    -------
    UnifiedTables
        Validated in-memory canonical tables.
    """
    print("\n[1/5] Loading province and territory boundaries...")
    provinces = load_province_boundaries(paths.province_boundary_path)
    print(f"      Boundaries loaded: {len(provinces):,}")

    print("[2/5] Loading NATCARB and retaining Canadian records...")
    saline, coal, oil_gas = load_canadian_natcarb(
        paths.source_files["NATCARB"],
        provinces,
    )
    print(
        "      Canadian NATCARB features: "
        f"{len(saline):,} saline | "
        f"{len(coal):,} coal | "
        f"{len(oil_gas):,} oil/gas"
    )

    print("[3/5] Building canonical storage units...")
    natcarb_units = build_natcarb_storage_units(saline, coal, oil_gas)
    bc_units, bc_aquifer_units, bc_pool_units = build_bc_storage_units(
        paths.source_files["BC"]
    )
    atlantic_units, _ = build_atlantic_storage_units(
        paths.source_files["ATLANTIC"]
    )
    print(
        "      Units by source: "
        f"{len(natcarb_units):,} NATCARB | "
        f"{len(bc_units):,} BC | "
        f"{len(atlantic_units):,} Atlantic"
    )

    storage_units = pd.concat(
        [natcarb_units, bc_units, atlantic_units],
        ignore_index=True,
    )

    print("[4/5] Building canonical spatial storage features...")
    storage_features = gpd.GeoDataFrame(
        pd.concat(
            [
                build_natcarb_storage_features(saline, coal, oil_gas),
                build_bc_storage_features(paths.source_files["BC"]),
                build_atlantic_storage_features(paths.source_files["ATLANTIC"]),
            ],
            ignore_index=True,
        ),
        geometry="geometry",
        crs=WORKING_CRS,
    )

    print(f"      Spatial storage features: {len(storage_features):,}")

    print("[5/5] Building assessments and administrative features...")
    storage_assessments = pd.concat(
        [
            build_natcarb_storage_assessments(saline, coal, oil_gas),
            build_bc_storage_assessments(bc_aquifer_units, bc_pool_units),
            build_atlantic_storage_assessments(paths.source_files["ATLANTIC"]),
        ],
        ignore_index=True,
    )
    storage_assessments = enforce_storage_assessment_types(storage_assessments)

    administrative_features = build_administrative_features(
        paths.source_files["AER"]
    )
    print(
        f"      Storage assessments: {len(storage_assessments):,}\n"
        f"      Administrative features: {len(administrative_features):,}"
    )

    tables = UnifiedTables(
        storage_units=storage_units,
        storage_features=storage_features,
        storage_assessments=storage_assessments,
        administrative_features=administrative_features,
    )
    print("      Validating canonical relationships and geometry...")
    validate_canonical_tables(tables)
    print("      Canonical validation passed.")
    return tables


# =============================================================================
# GeoPackage export and round-trip validation
# =============================================================================


def prepare_gpkg_gdf(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Prepare a GeoDataFrame for safe GeoPackage serialization.

    Parameters
    ----------
    gdf : geopandas.GeoDataFrame
        Spatial table to prepare.

    Returns
    -------
    geopandas.GeoDataFrame
        Copy in which null object and string values are converted to Python
        ``None`` while geometry is preserved.
    """
    export = gdf.copy()
    geometry_column = export.geometry.name
    for column in export.columns:
        if column == geometry_column:
            continue
        series = export[column]
        if (
            pd.api.types.is_string_dtype(series.dtype)
            or pd.api.types.is_object_dtype(series.dtype)
        ):
            export[column] = series.astype("object").where(series.notna(), None)
    return export


def _sqlite_type_for_series(series: pd.Series) -> str:
    """Return a conservative SQLite storage class for a pandas Series."""
    if pd.api.types.is_bool_dtype(series.dtype) or pd.api.types.is_integer_dtype(series.dtype):
        return "INTEGER"
    if pd.api.types.is_float_dtype(series.dtype):
        return "REAL"
    return "TEXT"


def _create_attribute_table(
    conn: sqlite3.Connection,
    *,
    table_name: str,
    frame: pd.DataFrame,
    stable_id_column: str,
    foreign_keys: tuple[tuple[str, str, str], ...] = (),
) -> None:
    """Create one GeoPackage attribute table with relational constraints.

    The GeoPackage row identifier is an integer ``fid`` primary key. The stable
    domain identifier remains a separate ``TEXT UNIQUE NOT NULL`` field so it can
    be preserved across rebuilds and used by downstream joins.
    """
    conn.execute(f'DROP TABLE IF EXISTS "{table_name}";')

    column_definitions: list[str] = ["fid INTEGER PRIMARY KEY AUTOINCREMENT"]
    for column in frame.columns:
        sql_type = _sqlite_type_for_series(frame[column])
        constraints = ""
        if column == stable_id_column:
            constraints = " NOT NULL UNIQUE"
        column_definitions.append(f'"{column}" {sql_type}{constraints}')

    for column, parent_table, parent_column in foreign_keys:
        column_definitions.append(
            f'FOREIGN KEY ("{column}") REFERENCES '
            f'"{parent_table}"("{parent_column}")'
        )

    ddl = (
        f'CREATE TABLE "{table_name}" (\n    '
        + ",\n    ".join(column_definitions)
        + "\n);"
    )
    conn.execute(ddl)
    frame.to_sql(table_name, conn, if_exists="append", index=False)


def _add_domain_integrity_constraints(conn: sqlite3.Connection) -> None:
    """Add indexes and trigger-based integrity checks to GeoPandas feature tables.

    GeoPandas creates the spatial feature tables and their GeoPackage metadata.
    Rebuilding those tables manually would risk disturbing GeoPackage geometry and
    RTree registrations. Instead, v2 leaves the GeoPackage-managed integer ``fid``
    primary keys intact, adds unique indexes on stable domain identifiers, and uses
    triggers to enforce relationships that cannot be added with SQLite ``ALTER
    TABLE`` without rebuilding the spatial tables.
    """
    conn.executescript(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
            ux_storage_features_storage_feature_id
        ON storage_features(storage_feature_id);

        CREATE INDEX IF NOT EXISTS
            ix_storage_features_storage_unit_id
        ON storage_features(storage_unit_id);

        CREATE UNIQUE INDEX IF NOT EXISTS
            ux_administrative_features_administrative_feature_id
        ON administrative_features(administrative_feature_id);

        CREATE INDEX IF NOT EXISTS
            ix_administrative_features_parent_id
        ON administrative_features(parent_administrative_feature_id);

        CREATE TRIGGER IF NOT EXISTS trg_storage_features_unit_insert
        BEFORE INSERT ON storage_features
        FOR EACH ROW
        WHEN NEW.storage_unit_id IS NOT NULL
         AND NOT EXISTS (
             SELECT 1 FROM storage_units
             WHERE storage_unit_id = NEW.storage_unit_id
         )
        BEGIN
            SELECT RAISE(ABORT, 'storage_features.storage_unit_id references a missing storage_units row');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_storage_features_unit_update
        BEFORE UPDATE OF storage_unit_id ON storage_features
        FOR EACH ROW
        WHEN NEW.storage_unit_id IS NOT NULL
         AND NOT EXISTS (
             SELECT 1 FROM storage_units
             WHERE storage_unit_id = NEW.storage_unit_id
         )
        BEGIN
            SELECT RAISE(ABORT, 'storage_features.storage_unit_id references a missing storage_units row');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_admin_parent_insert
        BEFORE INSERT ON administrative_features
        FOR EACH ROW
        WHEN NEW.parent_administrative_feature_id IS NOT NULL
         AND NOT EXISTS (
             SELECT 1 FROM administrative_features
             WHERE administrative_feature_id = NEW.parent_administrative_feature_id
         )
        BEGIN
            SELECT RAISE(ABORT, 'administrative_features.parent_administrative_feature_id references a missing administrative feature');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_admin_parent_update
        BEFORE UPDATE OF parent_administrative_feature_id ON administrative_features
        FOR EACH ROW
        WHEN NEW.parent_administrative_feature_id IS NOT NULL
         AND NOT EXISTS (
             SELECT 1 FROM administrative_features
             WHERE administrative_feature_id = NEW.parent_administrative_feature_id
         )
        BEGIN
            SELECT RAISE(ABORT, 'administrative_features.parent_administrative_feature_id references a missing administrative feature');
        END;
        """
    )


def export_unified_tables(tables: UnifiedTables, output_path: Path) -> None:
    """Write the canonical tables to the unified GeoPackage.

    Parameters
    ----------
    tables : UnifiedTables
        Validated canonical tables.
    output_path : pathlib.Path
        Destination GeoPackage path.

    Notes
    -----
    Spatial tables are written through GeoPandas. Nonspatial canonical tables are
    written through SQLite after the GeoPackage is initialized. An existing output
    file is replaced.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    storage_features = prepare_gpkg_gdf(tables.storage_features)
    administrative_features = prepare_gpkg_gdf(tables.administrative_features)

    for column in ["geometry_area_m2", "geometry_area_ha", "geometry_perimeter_m"]:
        storage_features[column] = pd.to_numeric(
            tables.storage_features[column], errors="coerce"
        )
    storage_features["capacity_data"] = tables.storage_features["capacity_data"].astype(
        "boolean"
    )

    storage_features.to_file(output_path, layer="storage_features", driver="GPKG")
    administrative_features.to_file(
        output_path,
        layer="administrative_features",
        driver="GPKG",
    )

    with closing(sqlite3.connect(output_path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")

        _create_attribute_table(
            conn,
            table_name="storage_units",
            frame=tables.storage_units,
            stable_id_column="storage_unit_id",
        )

        # Parent keys on the GeoPandas-created feature tables must be unique before
        # SQLite can use them as referenced keys from the attribute tables.
        _add_domain_integrity_constraints(conn)

        _create_attribute_table(
            conn,
            table_name="storage_assessments",
            frame=tables.storage_assessments,
            stable_id_column="storage_assessment_id",
            foreign_keys=(
                ("storage_unit_id", "storage_units", "storage_unit_id"),
                ("storage_feature_id", "storage_features", "storage_feature_id"),
            ),
        )

        register_attribute_table(
            conn,
            table_name="storage_units",
            description=(
                "Logical geological CO2 storage units used by the unified Canadian "
                "storage model."
            ),
        )
        register_attribute_table(
            conn,
            table_name="storage_assessments",
            description=(
                "Capacity, prospectivity, and reservoir assessment records linked "
                "to storage units and spatial features."
            ),
        )

        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_storage_assessments_storage_unit_id "
            "ON storage_assessments(storage_unit_id);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_storage_assessments_storage_feature_id "
            "ON storage_assessments(storage_feature_id);"
        )
        conn.commit()


def validate_existing_gpkg(output_path: Path) -> dict[str, int]:
    """Validate a persisted unified GeoPackage by round-trip loading.

    Parameters
    ----------
    output_path : pathlib.Path
        Existing unified GeoPackage.

    Returns
    -------
    dict[str, int]
        Row counts for the four required canonical tables.

    Raises
    ------
    FileNotFoundError
        If the GeoPackage does not exist.
    ValueError
        If required tables are missing or canonical integrity checks fail.
    """
    if not output_path.is_file():
        raise FileNotFoundError(output_path)

    required_tables = {
        "storage_units",
        "storage_features",
        "storage_assessments",
        "administrative_features",
    }
    with closing(sqlite3.connect(output_path)) as conn:
        present = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table';"
            )
        }
        missing = required_tables - present
        if missing:
            raise ValueError(f"Missing required table(s): {sorted(missing)}")
        conn.execute("PRAGMA foreign_keys = ON;")

        storage_units = pd.read_sql("SELECT * FROM storage_units", conn)
        storage_assessments = pd.read_sql("SELECT * FROM storage_assessments", conn)

        foreign_key_issues = conn.execute("PRAGMA foreign_key_check;").fetchall()
        if foreign_key_issues:
            raise ValueError(
                "SQLite foreign-key validation failed: "
                f"{foreign_key_issues[:10]}"
            )

        required_unique_indexes = {
            "ux_storage_features_storage_feature_id",
            "ux_administrative_features_administrative_feature_id",
        }
        present_indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index';"
            )
        }
        missing_indexes = required_unique_indexes - present_indexes
        if missing_indexes:
            raise ValueError(
                "Missing stable-domain unique index(es): "
                f"{sorted(missing_indexes)}"
            )

    validate_registered_tables(
        gpkg_path=output_path,
        expected={
            "storage_units": "attributes",
            "storage_features": "features",
            "storage_assessments": "attributes",
            "administrative_features": "features",
        },
    )

    storage_features = gpd.read_file(output_path, layer="storage_features")
    administrative_features = gpd.read_file(output_path, layer="administrative_features")

    tables = UnifiedTables(
        storage_units=storage_units,
        storage_features=storage_features,
        storage_assessments=storage_assessments,
        administrative_features=administrative_features,
    )
    validate_canonical_tables(tables)

    # Notebook 12 export-specific null serialization check.
    for table_name, df in {
        "storage_units": storage_units,
        "storage_features": storage_features,
        "storage_assessments": storage_assessments,
        "administrative_features": administrative_features,
    }.items():
        for column in df.columns:
            if column == "geometry":
                continue
            mask = df[column].notna() & df[column].astype(str).eq("<NA>")
            if mask.any():
                raise ValueError(
                    f'{table_name}.{column} contains literal "<NA>" values.'
                )

    return {
        "storage_units": len(storage_units),
        "storage_features": len(storage_features),
        "storage_assessments": len(storage_assessments),
        "administrative_features": len(administrative_features),
    }


# =============================================================================
# Notebook 12 documentation products retained in memory
# =============================================================================



def list_user_tables(conn: sqlite3.Connection) -> list[str]:
    """List non-system tables stored in a SQLite or GeoPackage database.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open SQLite connection.

    Returns
    -------
    list[str]
        Sorted table names excluding SQLite, GeoPackage, and RTree system
        tables.
    """
    table_names = [
        row[0]
        for row in conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            ORDER BY name;
            """
        )
    ]
    return [
        name
        for name in table_names
        if not (
            name.startswith("sqlite_")
            or name.startswith("gpkg_")
            or name.startswith("rtree_")
        )
    ]


def discover_documentation_tables(
    conn: sqlite3.Connection,
) -> tuple[str, str]:
    """Discover the metadata and QA tables in a precursor Silver GeoPackage.

    Discovery is based on the established Silver naming contract: one
    non-system table beginning with ``metadata_`` and one beginning with
    ``qa_``. The function intentionally inspects the database rather than
    maintaining source-specific table names in this script.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open connection to a precursor Silver GeoPackage.

    Returns
    -------
    tuple[str, str]
        Metadata table name followed by QA table name.

    Raises
    ------
    ValueError
        If exactly one metadata table and one QA table cannot be identified.
    """
    table_names = list_user_tables(conn)
    metadata_tables = [
        name for name in table_names if name.lower().startswith("metadata_")
    ]
    qa_tables = [
        name for name in table_names if name.lower().startswith("qa_")
    ]

    if len(metadata_tables) != 1:
        raise ValueError(
            "Expected exactly one precursor metadata table matching "
            f"'metadata_*'; found {metadata_tables}."
        )
    if len(qa_tables) != 1:
        raise ValueError(
            "Expected exactly one precursor QA table matching "
            f"'qa_*'; found {qa_tables}."
        )

    return metadata_tables[0], qa_tables[0]


def metadata_lookup(metadata: pd.DataFrame) -> dict[str, Any]:
    """Convert a two-column metadata table to a key/value mapping.

    Parameters
    ----------
    metadata : pandas.DataFrame
        Metadata table containing ``key`` and ``value`` columns.

    Returns
    -------
    dict[str, Any]
        Metadata key/value mapping.

    Raises
    ------
    ValueError
        If required columns are absent or metadata keys are null or duplicated.
    """
    required_columns = {"key", "value"}
    missing = required_columns - set(metadata.columns)
    if missing:
        raise ValueError(
            f"Metadata table is missing required column(s): {sorted(missing)}"
        )
    if metadata["key"].isna().any():
        raise ValueError("Metadata table contains null keys.")
    if metadata["key"].duplicated().any():
        raise ValueError("Metadata table contains duplicate keys.")

    return dict(zip(metadata["key"], metadata["value"], strict=True))


def documentation_table_names(
    unified_metadata: pd.DataFrame,
) -> dict[str, str]:
    """Derive documentation table names from unified dataset metadata.

    Parameters
    ----------
    unified_metadata : pandas.DataFrame
        Unified key/value metadata table containing ``dataset_id``.

    Returns
    -------
    dict[str, str]
        Table names for precursor lineage metadata, precursor lineage QA,
        unified metadata, and unified QA.

    Raises
    ------
    ValueError
        If ``dataset_id`` is unavailable or cannot be converted to a valid
        SQLite table-name suffix.
    """
    lookup = metadata_lookup(unified_metadata)
    dataset_id = str(lookup.get("dataset_id", "")).strip().lower()

    if not dataset_id:
        raise ValueError("Unified metadata does not define a dataset_id.")

    suffix = re.sub(r"[^a-z0-9_]+", "_", dataset_id).strip("_")
    if not suffix:
        raise ValueError(
            f"Could not derive documentation table names from dataset_id={dataset_id!r}."
        )

    return {
        "source_catalog": f"source_catalog_{suffix}",
        "source_metadata": f"source_metadata_{suffix}",
        "source_qa": f"source_qa_{suffix}",
        "metadata": f"metadata_{suffix}",
        "qa": f"qa_{suffix}",
    }



def first_metadata_value(
    lookup: dict[str, Any],
    *keys: str,
) -> Any | None:
    """Return the first populated value among candidate metadata keys.

    Metadata keys in the precursor Silver packages are not fully uniform in
    capitalization or naming. This helper performs case-insensitive lookup and
    returns the first non-null, nonblank value from the supplied key candidates.

    Parameters
    ----------
    lookup : dict[str, Any]
        Metadata key/value mapping.
    *keys : str
        Candidate metadata keys in preference order.

    Returns
    -------
    Any or None
        First populated metadata value, or ``None`` when none is available.
    """
    normalized = {
        str(key).strip().lower(): value
        for key, value in lookup.items()
    }

    for key in keys:
        value = normalized.get(key.strip().lower())

        if value is None:
            continue

        if pd.isna(value):
            continue

        if isinstance(value, str) and not value.strip():
            continue

        return value

    return None

def derive_source_year(lookup: dict[str, Any]) -> Any | None:
    """Derive a source publication or dataset year from precursor metadata.

    Parameters
    ----------
    lookup : dict[str, Any]
        Metadata key/value mapping for one precursor dataset.

    Returns
    -------
    Any or None
        Source year when available. Full publication dates are reduced to their
        leading four-digit year.
    """
    value = first_metadata_value(
        lookup,
        "source_year",
        "source_publication_year",
        "source_publication_date",
        "publication_year",
    )
    if value is None:
        return None

    text_value = str(value).strip()
    match = re.match(r"^(\d{4})", text_value)
    return match.group(1) if match else value


def derive_source_authors(lookup: dict[str, Any]) -> Any | None:
    """Derive the best available source authorship description.

    Explicit author fields are preferred. A source preparer is used next. When
    the precursor metadata contains a formal attribution statement, the leading
    citation authorship is retained. Institutional source organization is used
    only as the final fallback for datasets without named authors.

    Parameters
    ----------
    lookup : dict[str, Any]
        Metadata key/value mapping for one precursor dataset.

    Returns
    -------
    Any or None
        Best available named or institutional authorship description.
    """
    explicit = first_metadata_value(
        lookup,
        "source_authors",
        "source_author",
        "authors",
        "author",
        "source_preparer",
    )
    if explicit is not None:
        return explicit

    attribution = first_metadata_value(
        lookup,
        "attribution_text",
        "recommended_citation",
        "source_citation",
        "citation",
    )
    if isinstance(attribution, str):
        cleaned = attribution.strip()
        cleaned = re.sub(r"^Derived from\s+", "", cleaned, flags=re.IGNORECASE)
        match = re.match(r"^(.*?)(?:\s*\(|,\s*)(\d{4})(?:\)|,)", cleaned)
        if match and match.group(1).strip():
            return match.group(1).strip().rstrip(",")

    return first_metadata_value(
        lookup,
        "source_organization",
        "organization",
    )


def build_source_catalog(source_metadata: pd.DataFrame) -> pd.DataFrame:
    """Build a normalized one-row-per-source provenance catalog.

    The complete precursor metadata remain preserved in ``source_metadata``.
    This catalog provides a compact human-readable crosswalk for users of the
    unified database and is derived entirely from the metadata tables embedded
    in the precursor Silver GeoPackages.

    Parameters
    ----------
    source_metadata : pandas.DataFrame
        Combined precursor key/value metadata containing ``source_key``,
        ``dataset_id``, ``source_table``, ``key``, and ``value``.

    Returns
    -------
    pandas.DataFrame
        Normalized provenance catalog with source identity, authorship,
        organization, publication information, source links, citation text, and
        originating metadata table.

    Raises
    ------
    ValueError
        If the required lineage columns are absent.
    """
    required = {"source_key", "dataset_id", "source_table", "key", "value"}
    missing = required - set(source_metadata.columns)
    if missing:
        raise ValueError(
            "Source metadata are missing required lineage column(s): "
            f"{sorted(missing)}"
        )

    rows: list[dict[str, object]] = []

    for source_key, group in source_metadata.groupby(
        "source_key",
        sort=True,
        dropna=False,
    ):
        lookup = dict(
            zip(
                group["key"],
                group["value"],
                strict=True,
            )
        )

        source_url = first_metadata_value(
            lookup,
            "source_url",
            "source_page",
            "project_url",
            "dataset_url",
        )
        source_parent_url = first_metadata_value(
            lookup,
            "source_parent_url",
            "parent_url",
            "parent_page",
        )
        source_resource_url = first_metadata_value(
            lookup,
            "source_resource_url",
            "source_resource_page",
            "resource_url",
            "source_archive_url",
        )

        rows.append(
            {
                "source_key": source_key,
                "dataset_id": group["dataset_id"].iloc[0],
                "source_title": first_metadata_value(
                    lookup,
                    "source_title",
                    "title",
                ),
                "source_authors": derive_source_authors(lookup),
                "source_organization": first_metadata_value(
                    lookup,
                    "source_organization",
                    "organization",
                ),
                "source_publication": first_metadata_value(
                    lookup,
                    "source_publication",
                    "publication",
                ),
                "source_year": derive_source_year(lookup),
                "source_version": first_metadata_value(
                    lookup,
                    "source_version",
                    "version",
                ),
                "source_url": source_url,
                "source_parent_url": source_parent_url,
                "source_resource_url": source_resource_url,
                "source_doi": first_metadata_value(
                    lookup,
                    "source_doi",
                    "doi",
                ),
                "source_citation": first_metadata_value(
                    lookup,
                    "recommended_citation",
                    "source_citation",
                    "citation",
                    "attribution_text",
                ),
                "submission_filename": first_metadata_value(
                    lookup,
                    "submission_filename",
                ),
                "metadata_table": group["source_table"].iloc[0],
            }
        )

    catalog = pd.DataFrame(rows)

    if catalog["source_title"].isna().any():
        missing_sources = catalog.loc[
            catalog["source_title"].isna(),
            "source_key",
        ].tolist()
        raise ValueError(
            "Could not derive source_title for precursor dataset(s): "
            f"{missing_sources}"
        )

    return catalog


def print_source_catalog(source_catalog: pd.DataFrame) -> None:
    """Print a concise provenance summary for precursor datasets.

    Parameters
    ----------
    source_catalog : pandas.DataFrame
        Normalized precursor source catalog.

    Returns
    -------
    None
    """
    print("\\nSource datasets")
    print("---------------")

    for row in source_catalog.itertuples(index=False):
        title = row.source_title or "(untitled source)"
        authors = row.source_authors or row.source_organization or "unknown author"
        year = row.source_year or "year unknown"
        organization = row.source_organization or "organization unknown"

        print(f"[{row.source_key}] {title}")
        print(f"  Authors/preparer: {authors}")
        print(f"  Organization:     {organization}")
        print(f"  Year:             {year}")

        if row.source_url:
            print(f"  Source:           {row.source_url}")
        elif row.source_parent_url:
            print(f"  Source:           {row.source_parent_url}")

def supplement_source_metadata(
    source_key: str,
    metadata: pd.DataFrame,
) -> pd.DataFrame:
    """Add documented metadata fields missing from a precursor metadata table.

    Supplemental values are used only where the precursor GeoPackage does not
    already provide the corresponding key. Existing child metadata always takes
    precedence.

    Parameters
    ----------
    source_key : str
        Unified-build source identifier.
    metadata : pandas.DataFrame
        Precursor metadata containing ``key`` and ``value`` columns.

    Returns
    -------
    pandas.DataFrame
        Metadata with documented supplemental fields appended when absent.
    """
    result = metadata.copy()
    existing_keys = set(result["key"].astype(str))

    if source_key == "NATCARB":
        supplements = {
            "source_title": "NATCARB All Data v1502",
            "source_year": "2015",
            "source_url": "https://edx.netl.doe.gov/dataset/natcarb",
            "source_resource_url": (
                "https://edx.netl.doe.gov/dataset/natcarb-alldata-v1502"
            ),
        }

        missing_rows = [
            {"key": key, "value": value}
            for key, value in supplements.items()
            if key not in existing_keys
        ]

        if missing_rows:
            result = pd.concat(
                [result, pd.DataFrame(missing_rows)],
                ignore_index=True,
            )

    return result


def read_precursor_documentation(
    source_files: dict[str, Path],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read metadata and QA lineage from precursor Silver GeoPackages.

    The precursor documentation table names are discovered from each
    GeoPackage at runtime. This avoids maintaining a second, hard-coded mapping
    of table names in the unified build script.

    Parameters
    ----------
    source_files : dict[str, pathlib.Path]
        Mapping from precursor dataset identifier to GeoPackage path.

    Returns
    -------
    tuple[pandas.DataFrame, pandas.DataFrame]
        Combined source metadata and source QA tables with precursor dataset
        identifiers and originating table names attached.
    """
    metadata_frames: list[pd.DataFrame] = []
    qa_frames: list[pd.DataFrame] = []

    for source_key, gpkg_path in source_files.items():
        with closing(sqlite3.connect(gpkg_path)) as conn:
            metadata_table, qa_table = discover_documentation_tables(conn)

            metadata = pd.read_sql_query(
                f'SELECT key, value FROM "{metadata_table}";',
                conn,
            )

            metadata = supplement_source_metadata(
                source_key,
                metadata,
            )

            source_lookup = metadata_lookup(metadata)
            dataset_id = str(
                source_lookup.get("dataset_id")
                or source_lookup.get("data_type")
                or source_key
            )

            metadata.insert(0, "source_table", metadata_table)
            metadata.insert(0, "dataset_id", dataset_id)
            metadata.insert(0, "source_key", source_key)
            metadata_frames.append(metadata)

            qa = pd.read_sql_query(
                f'SELECT * FROM "{qa_table}";',
                conn,
            )
            if "notes" not in qa.columns:
                qa["notes"] = None

            required_qa_columns = {"check", "value", "notes"}
            missing_qa_columns = required_qa_columns - set(qa.columns)
            if missing_qa_columns:
                raise ValueError(
                    f"{gpkg_path.name}:{qa_table} is missing required "
                    f"QA column(s): {sorted(missing_qa_columns)}"
                )

            qa = qa[["check", "value", "notes"]]
            qa.insert(0, "source_table", qa_table)
            qa.insert(0, "dataset_id", dataset_id)
            qa.insert(0, "source_key", source_key)
            qa_frames.append(qa)

    source_metadata = (
        pd.concat(metadata_frames, ignore_index=True)
        .sort_values(["source_key", "dataset_id", "key"])
        .reset_index(drop=True)
    )
    source_qa = (
        pd.concat(qa_frames, ignore_index=True)
        .sort_values(["source_key", "dataset_id", "check"])
        .reset_index(drop=True)
    )

    return source_metadata, source_qa


def build_unified_metadata(source_catalog: pd.DataFrame) -> pd.DataFrame:
    """Build and validate dataset-level metadata for the unified product.

    Parameters
    ----------
    source_catalog : pandas.DataFrame
        Normalized precursor source catalog used to document the datasets that
        contribute to the unified product.

    Returns
    -------
    pandas.DataFrame
        Two-column key/value metadata table satisfying the unified metadata
        contract.

    Raises
    ------
    ValueError
        If metadata keys are missing, duplicated, null, or inconsistent with the
        submission filename convention.
    """
    rows = [
        ("title", "Canada Geological CO2 Storage Unified Database"),
        ("dataset_id", "canada_geological_storage_unified"),
        ("data_type", UNIFIED_DATA_TYPE),
        ("who", "Andrew Vigars, CanCO2Re Activity 13"),
        (
            "what",
            "Unified Canadian geological CO2 storage database integrating "
            "harmonized geological storage capacity, geological prospectivity, "
            "and regulatory tenure datasets from multiple precursor Silver GeoPackages.",
        ),
        ("when", UNIFIED_DATE),
        (
            "where",
            "Canada. Spatial layers use NAD83 / Canada Atlas Lambert, EPSG:3978.",
        ),
        (
            "how",
            "Constructed by harmonizing and integrating precursor Silver "
            "GeoPackages from Alberta Energy Regulator carbon sequestration "
            "agreements, the Northeast BC Geological Carbon Capture and Storage "
            "Atlas, Geological Survey of Canada Atlantic Chance of Success mapping, "
            "and the Canadian subset of DOE/NETL NATCARB v1502.",
        ),
        ("activity_code", "13"),
        ("creator_name", "Andrew Vigars"),
        ("creator_initials", "AV"),
        ("submission_filename", UNIFIED_SUBMISSION_FILENAME),
        (
            "dataset_role",
            "Unified integration-layer database for national-scale geological CO2 "
            "storage screening, comparison, spatial analysis, and downstream CCUS modelling.",
        ),
        (
            "package_purpose",
            "Provides a common national schema for geological storage units, spatial "
            "representations, storage assessments, and regulatory administrative "
            "features while preserving source provenance and source-specific interpretation.",
        ),
        ("silver_crs", WORKING_CRS),
        ("silver_format", "GeoPackage"),
        ("assessment_type", "mixed_geological_storage_assessment"),
        ("data_class", "integrated_geological_storage"),
        ("capacity_data", "mixed"),
        ("capacity_status", "source_dependent"),
        ("injectivity_status", "source_dependent"),
        (
            "interpretation_note",
            "The unified database integrates datasets with different scientific and "
            "regulatory meanings. Geological capacity, geological prospectivity, and "
            "regulatory tenure records must not be treated as interchangeable. "
            "Source_dataset and assessment_type fields should be used when interpreting "
            "individual records.",
        ),
        (
            "processing_summary",
            "Precursor Silver datasets were mapped into a canonical schema consisting "
            "of storage_units, storage_features, storage_assessments, and "
            "administrative_features. Stable source-derived identifiers and "
            "source_dataset provenance were preserved. Logical storage units were "
            "separated from spatial representations, assessment scope was retained "
            "explicitly, and regulatory tenure polygons were kept separate from "
            "geological storage objects.",
        ),
        (
            "use_limitations",
            "This database is intended for regional and national screening, comparative "
            "analysis, and model input preparation. It does not establish project-ready "
            "storage capacity, demonstrated injectivity, permitted injection capacity, "
            "legal storage rights, or site-specific geological suitability. "
            "Source-specific limitations remain authoritative and should be consulted "
            "through source_metadata.",
        ),
        (
            "keywords",
            "carbon storage; CO2 storage; CCUS; geological storage; saline aquifer; "
            "depleted reservoir; geological prospectivity; carbon sequestration "
            "agreement; Canada",
        ),
    ]
    metadata = pd.DataFrame(rows, columns=["key", "value"])

    dataset_id = str(
        metadata.loc[
            metadata["key"].eq("dataset_id"),
            "value",
        ].iloc[0]
    )
    suffix = re.sub(r"[^a-z0-9_]+", "_", dataset_id.lower()).strip("_")

    lineage_rows = pd.DataFrame(
        [
            ("precursor_dataset_count", str(len(source_catalog))),
            ("source_catalog_table", f"source_catalog_{suffix}"),
            ("source_metadata_table", f"source_metadata_{suffix}"),
            ("source_qa_table", f"source_qa_{suffix}"),
        ],
        columns=["key", "value"],
    )
    metadata = pd.concat(
        [metadata, lineage_rows],
        ignore_index=True,
    )

    required = {
        "title", "dataset_id", "data_type", "who", "what", "when", "where", "how",
        "activity_code", "creator_name", "creator_initials", "submission_filename",
        "dataset_role", "package_purpose", "silver_crs", "silver_format",
        "assessment_type", "data_class", "capacity_data", "capacity_status",
        "injectivity_status", "interpretation_note", "processing_summary",
        "use_limitations", "keywords", "precursor_dataset_count",
        "source_catalog_table", "source_metadata_table", "source_qa_table",
    }
    if metadata["key"].isna().any() or metadata["key"].duplicated().any():
        raise ValueError("Unified metadata key integrity failed.")
    missing = required - set(metadata["key"])
    if missing:
        raise ValueError(f"Unified metadata missing key(s): {sorted(missing)}")

    lookup = dict(zip(metadata["key"], metadata["value"], strict=True))
    expected_filename = (
        f"{lookup['when'].replace('-', '')}_{lookup['activity_code']}_"
        f"{lookup['data_type']}_{lookup['creator_initials']}"
        f"_{UNIFIED_BUILD_VARIANT}.gpkg"
    )
    if lookup["submission_filename"] != expected_filename:
        raise ValueError(
            "Unified submission filename contract failed: "
            f"expected {expected_filename!r}, found "
            f"{lookup['submission_filename']!r}."
        )
    return metadata


def build_unified_qa(output_path: Path) -> pd.DataFrame:
    """Build QA records from the persisted unified GeoPackage.

    Parameters
    ----------
    output_path : pathlib.Path
        Persisted unified GeoPackage to inspect.

    Returns
    -------
    pandas.DataFrame
        QA checks and values for canonical counts, identifiers, relationships,
        geometry registration, CRS, and geometry validity.

    Raises
    ------
    ValueError
        If any required integrity check fails.
    """
    rows: list[dict[str, object]] = []
    canonical_tables = (
        "storage_units",
        "storage_features",
        "storage_assessments",
        "administrative_features",
    )
    id_fields = {
        "storage_units": "storage_unit_id",
        "storage_features": "storage_feature_id",
        "storage_assessments": "storage_assessment_id",
        "administrative_features": "administrative_feature_id",
    }

    with closing(sqlite3.connect(output_path)) as conn:
        for table_name in canonical_tables:
            row_count = conn.execute(
                f'SELECT COUNT(*) FROM "{table_name}";'
            ).fetchone()[0]
            rows.append(
                {
                    "check": f"{table_name}_count",
                    "value": row_count,
                    "notes": f"Persisted row count for {table_name}.",
                }
            )

        for table_name, id_field in id_fields.items():
            missing_count = conn.execute(
                f'''SELECT COUNT(*) FROM "{table_name}"
                    WHERE "{id_field}" IS NULL
                       OR TRIM(CAST("{id_field}" AS TEXT)) = '';'''
            ).fetchone()[0]
            duplicate_count = conn.execute(
                f'''SELECT COUNT(*) - COUNT(DISTINCT "{id_field}")
                    FROM "{table_name}" WHERE "{id_field}" IS NOT NULL;'''
            ).fetchone()[0]
            rows.extend(
                [
                    {
                        "check": f"{table_name}_missing_id_count",
                        "value": missing_count,
                        "notes": f"Null or blank values in {id_field}.",
                    },
                    {
                        "check": f"{table_name}_duplicate_id_count",
                        "value": duplicate_count,
                        "notes": f"Duplicate non-null values in {id_field}.",
                    },
                ]
            )

        assessment_type_rows = conn.execute(
            'PRAGMA table_info("storage_assessments");'
        ).fetchall()
        assessment_sql_types = {row[1]: str(row[2]).upper() for row in assessment_type_rows}
        wrong_sql_types = {
            column: assessment_sql_types.get(column)
            for column in STORAGE_ASSESSMENT_REAL_COLUMNS
            if assessment_sql_types.get(column) != "REAL"
        }
        rows.append(
            {
                "check": "storage_assessments_real_type_count",
                "value": len(STORAGE_ASSESSMENT_REAL_COLUMNS) - len(wrong_sql_types),
                "notes": (
                    "Quantitative assessment columns persisted as SQLite REAL. "
                    f"Unexpected types: {wrong_sql_types or 'none'}."
                ),
            }
        )
        if wrong_sql_types:
            raise ValueError(
                "storage_assessments quantitative columns must persist as REAL: "
                f"{wrong_sql_types}"
            )

        relationships = {
            "storage_features_orphan_unit_count": """
                SELECT COUNT(*) FROM storage_features AS f
                LEFT JOIN storage_units AS u ON f.storage_unit_id = u.storage_unit_id
                WHERE f.storage_unit_id IS NOT NULL AND u.storage_unit_id IS NULL;
            """,
            "storage_assessments_orphan_unit_count": """
                SELECT COUNT(*) FROM storage_assessments AS a
                LEFT JOIN storage_units AS u ON a.storage_unit_id = u.storage_unit_id
                WHERE a.storage_unit_id IS NOT NULL AND u.storage_unit_id IS NULL;
            """,
            "storage_assessments_orphan_feature_count": """
                SELECT COUNT(*) FROM storage_assessments AS a
                LEFT JOIN storage_features AS f ON a.storage_feature_id = f.storage_feature_id
                WHERE a.storage_feature_id IS NOT NULL AND f.storage_feature_id IS NULL;
            """,
            "administrative_features_orphan_parent_count": """
                SELECT COUNT(*) FROM administrative_features AS child
                LEFT JOIN administrative_features AS parent
                  ON child.parent_administrative_feature_id = parent.administrative_feature_id
                WHERE child.parent_administrative_feature_id IS NOT NULL
                  AND parent.administrative_feature_id IS NULL;
            """,
        }
        for check, sql in relationships.items():
            rows.append(
                {
                    "check": check,
                    "value": conn.execute(sql).fetchone()[0],
                    "notes": "Logical relationship integrity check.",
                }
            )

        geometry_columns = pd.read_sql_query(
            """
            SELECT table_name, column_name, geometry_type_name, srs_id
            FROM gpkg_geometry_columns ORDER BY table_name;
            """,
            conn,
        )
        spatial_tables = geometry_columns["table_name"].tolist()
        spatial_crs = sorted(
            geometry_columns["srs_id"].dropna().astype(int).unique().tolist()
        )
        rows.append(
            {
                "check": "feature_layers",
                "value": len(spatial_tables),
                "notes": "Number of registered spatial feature tables.",
            }
        )
        rows.append(
            {
                "check": "silver_crs",
                "value": f"EPSG:{spatial_crs[0]}" if len(spatial_crs) == 1 else str(spatial_crs),
                "notes": "CRS registered for persisted spatial feature tables.",
            }
        )
        for table_name in spatial_tables:
            count = conn.execute(
                f'SELECT COUNT(*) FROM "{table_name}" WHERE geom IS NULL;'
            ).fetchone()[0]
            rows.append(
                {
                    "check": f"{table_name}_null_geometry_count",
                    "value": count,
                    "notes": f"Persisted null geometry count for {table_name}.",
                }
            )

    for table_name in ["storage_features", "administrative_features"]:
        gdf = gpd.read_file(output_path, layer=table_name)
        invalid = int((gdf.geometry.notna() & ~gdf.geometry.is_valid).sum())
        rows.append(
            {
                "check": f"{table_name}_invalid_geometry_count",
                "value": invalid,
                "notes": f"Persisted invalid geometry count for {table_name}.",
            }
        )

    qa = (
        pd.DataFrame(rows)
        .drop_duplicates(subset="check", keep="last")
        .sort_values("check")
        .reset_index(drop=True)
    )
    lookup = dict(zip(qa["check"], qa["value"], strict=True))
    zero_expected = {
        "administrative_features_duplicate_id_count",
        "administrative_features_missing_id_count",
        "administrative_features_null_geometry_count",
        "administrative_features_invalid_geometry_count",
        "administrative_features_orphan_parent_count",
        "storage_assessments_duplicate_id_count",
        "storage_assessments_missing_id_count",
        "storage_assessments_orphan_feature_count",
        "storage_assessments_orphan_unit_count",
        "storage_features_duplicate_id_count",
        "storage_features_missing_id_count",
        "storage_features_null_geometry_count",
        "storage_features_invalid_geometry_count",
        "storage_features_orphan_unit_count",
        "storage_units_duplicate_id_count",
        "storage_units_missing_id_count",
    }
    failures = {
        check: lookup[check]
        for check in zero_expected
        if int(lookup[check]) != 0
    }
    if failures:
        raise ValueError(f"Unified QA integrity checks failed: {failures}")
    if lookup["silver_crs"] != WORKING_CRS:
        raise ValueError(f"Expected {WORKING_CRS}, found {lookup['silver_crs']}.")
    if int(lookup["feature_layers"]) != 2:
        raise ValueError("Expected exactly two registered spatial feature layers.")
    return qa


def build_documentation(paths: BuildPaths) -> DocumentationTables:
    """Build source-lineage, unified metadata, and unified QA products.

    Parameters
    ----------
    paths : BuildPaths
        Resolved build paths.

    Returns
    -------
    DocumentationTables
        In-memory documentation tables associated with the unified product.
    """
    source_metadata, source_qa = read_precursor_documentation(paths.source_files)
    source_catalog = build_source_catalog(source_metadata)
    unified_metadata = build_unified_metadata(source_catalog)
    unified_qa = build_unified_qa(paths.output_path)

    return DocumentationTables(
        source_catalog=source_catalog,
        source_metadata=source_metadata,
        source_qa=source_qa,
        unified_metadata=unified_metadata,
        unified_qa=unified_qa,
    )


def export_documentation_tables(
    documentation: DocumentationTables,
    output_path: Path,
) -> dict[str, str]:
    """Persist the source catalog, source lineage, unified metadata, and QA tables.

    Unified table names are derived from the ``dataset_id`` stored in the
    unified metadata. No source-specific metadata or QA table names are
    hard-coded in this export step.

    Parameters
    ----------
    documentation : DocumentationTables
        Documentation products generated for the unified database.
    output_path : pathlib.Path
        Unified GeoPackage receiving the documentation tables.

    Returns
    -------
    dict[str, str]
        Mapping from documentation role to persisted table name.
    """
    names = documentation_table_names(documentation.unified_metadata)

    with closing(sqlite3.connect(output_path)) as conn:
        registerable_tables: tuple[tuple[str, pd.DataFrame, str], ...] = (
            (
                "source_catalog",
                documentation.source_catalog,
                "Normalized one-row-per-precursor source catalog.",
            ),
            (
                "source_metadata",
                documentation.source_metadata,
                "Complete precursor metadata lineage in key/value form.",
            ),
            (
                "source_qa",
                documentation.source_qa,
                "Complete precursor QA lineage in key/value form.",
            ),
            (
                "metadata",
                documentation.unified_metadata,
                "Unified dataset metadata and interpretation notes.",
            ),
            (
                "qa",
                documentation.unified_qa,
                "Unified persisted QA checks and results.",
            ),
        )
        for role, frame, description in registerable_tables:
            frame.to_sql(
                names[role],
                conn,
                if_exists="replace",
                index=False,
            )
            register_attribute_table(
                conn,
                table_name=names[role],
                description=description,
            )
        conn.commit()

    return names


def validate_documentation_tables(
    output_path: Path,
    unified_metadata: pd.DataFrame,
) -> dict[str, int]:
    """Validate persisted documentation tables in the unified GeoPackage.

    Parameters
    ----------
    output_path : pathlib.Path
        Unified GeoPackage to validate.
    unified_metadata : pandas.DataFrame
        Unified metadata used to derive expected documentation table names.

    Returns
    -------
    dict[str, int]
        Persisted row count for each documentation table.

    Raises
    ------
    ValueError
        If an expected documentation table is absent or empty.
    """
    names = documentation_table_names(unified_metadata)

    with closing(sqlite3.connect(output_path)) as conn:
        present = set(list_user_tables(conn))
        missing = set(names.values()) - present
        if missing:
            raise ValueError(
                f"Missing persisted documentation table(s): {sorted(missing)}"
            )

        counts = {
            role: int(
                conn.execute(
                    f'SELECT COUNT(*) FROM "{table_name}";'
                ).fetchone()[0]
            )
            for role, table_name in names.items()
        }

    empty = {
        role: count
        for role, count in counts.items()
        if count == 0
    }
    if empty:
        raise ValueError(
            f"Persisted documentation table(s) are empty: {sorted(empty)}"
        )

    return counts


# =============================================================================
# CLI
# =============================================================================


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for build or validation execution.

    Returns
    -------
    argparse.Namespace
        Parsed command-line arguments.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Build or validate the unified Canadian geological storage atlas GeoPackage."
        )
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Repository root. Defaults to nearest parent containing pyproject.toml.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Override the dated unified GeoPackage output path.",
    )
    parser.add_argument(
        "--validate-existing",
        type=Path,
        default=None,
        help="Validate an existing unified GeoPackage without rebuilding it.",
    )
    return parser.parse_args()


def main() -> None:
    """Run the unified storage build or validate an existing GeoPackage.

    The command-line mode is selected by the presence of ``--validate-existing``.
    Otherwise, this function resolves build paths, validates inputs, constructs and
    exports the canonical tables, performs round-trip validation, and builds the
    in-memory documentation products.
    """
    args = parse_args()

    if args.validate_existing is not None:
        counts = validate_existing_gpkg(args.validate_existing.resolve())
        print("Unified atlas canonical GeoPackage validation passed.")
        for table, count in counts.items():
            print(f"  {table:<24} {count:>8,}")
        return

    project_root = (
        args.project_root.resolve()
        if args.project_root is not None
        else find_project_root()
    )
    paths = build_paths(
        project_root=project_root,
        output_path=args.output.resolve() if args.output is not None else None,
    )
    validate_input_paths(paths)

    print("CANCO2-Storage unified atlas build")
    print("---------------------------------")
    print(f"Project root: {paths.project_root}")
    print(f"Output:       {paths.output_path}")

    print("\nInput datasets")
    print("--------------")
    for source_key, source_path in paths.source_files.items():
        print(f"[{source_key:<8}] {source_path.name}")
    print(f"[BASEMAP ] {paths.province_boundary_path.name}")

    tables = build_unified_tables(paths)

    print("\nExporting canonical GeoPackage tables...")
    export_unified_tables(tables, paths.output_path)
    print(f"      Written: {paths.output_path.name}")

    print("Running persisted round-trip validation...")
    counts = validate_existing_gpkg(paths.output_path)
    print("      Round-trip validation passed.")

    print("\nBuilding provenance, metadata, and QA documentation...")
    documentation = build_documentation(paths)
    print_source_catalog(documentation.source_catalog)
    print("\nPersisting documentation tables...")
    documentation_names = export_documentation_tables(
        documentation,
        paths.output_path,
    )
    documentation_counts = validate_documentation_tables(
        paths.output_path,
        documentation.unified_metadata,
    )
    print("      Documentation validation passed.")

    print("\nBuild and round-trip validation passed.")
    for table, count in counts.items():
        print(f"  {table:<24} {count:>8,}")

    print("\nPersisted documentation tables")
    print("------------------------------")
    for role, table_name in documentation_names.items():
        print(
            f"  {table_name:<48} "
            f"{documentation_counts[role]:>8,}"
        )


if __name__ == "__main__":
    main()
