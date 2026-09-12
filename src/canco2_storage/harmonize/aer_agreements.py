"""
Harmonize Alberta Carbon Sequestration Agreement source data.

This module converts the provider shapefile downloaded by
``canco2_storage.acquisition.aer_agreements`` into the AER Silver products
previously established in the exploratory workflow.

The source represents regulatory / tenure information associated with carbon
sequestration pore-space agreements. It does not provide quantified geological
CO2 storage capacity, injectivity, geological prospectivity, storage
probability, permitted injection capacity, or project-ready storage resource.

Workflow
--------
1. Discover and inspect the Bronze AER shapefile.
2. Validate the expected source schema and EPSG:3400 source CRS.
3. Harmonize source fields while preserving agreement and tract identifiers.
4. Repair invalid geometries when required and reproject to EPSG:3978.
5. Preserve one feature per source tract.
6. Validate agreement-level attribute consistency.
7. Dissolve tract geometries by agreement identifier.
8. Preserve distinct tract-level zone descriptions during dissolve.
9. Export tract and agreement layers to one Silver GeoPackage.
10. Export metadata, QA tables, source-schema inventory, and field dictionaries.
11. Reopen the written GeoPackage and validate the persisted artifact.

The original Bronze files are never modified.
"""

from __future__ import annotations

import argparse
import sqlite3
import warnings
from datetime import date
from pathlib import Path
from typing import TypedDict

import geopandas as gpd
import pandas as pd
from shapely import make_valid

from canco2_storage.paths import find_project_root

from canco2_storage.metadata.common import (
    CANCO2RE_SUBMISSION,
    build_submission_stem,
    write_readme,
)

from canco2_storage.metadata.aer_agreements import (
    DATA_TYPE,
    build_readme,
)

# =============================================================================
# Project paths
# =============================================================================

PROJECT_ROOT = find_project_root()

RAW_AER_AGREEMENTS = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "aer_agreements"
)

RAW_AER_SOURCE = RAW_AER_AGREEMENTS / "source"

PROCESSED_AER_AGREEMENTS = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "aer_agreements"
)

CREATED_DATE = date.today()

SUBMISSION_STEM = build_submission_stem(
    data_type=DATA_TYPE,
    created_date=CREATED_DATE,
)

SILVER_GPKG_PATH = (
    PROCESSED_AER_AGREEMENTS
    / f"{SUBMISSION_STEM}.gpkg"
)

README_PATH = (
    PROCESSED_AER_AGREEMENTS
    / (
        f"{CREATED_DATE:%Y%m%d}_"
        f"{CANCO2RE_SUBMISSION.activity_code}_"
        f"{DATA_TYPE}README_"
        f"{CANCO2RE_SUBMISSION.creator_initials}.md"
    )
)

SCHEMA_INVENTORY_PATH = (
    PROCESSED_AER_AGREEMENTS
    / (
        f"{CREATED_DATE:%Y%m%d}_"
        f"{CANCO2RE_SUBMISSION.activity_code}_"
        f"{DATA_TYPE}SourceSchema_"
        f"{CANCO2RE_SUBMISSION.creator_initials}.csv"
    )
)

AGREEMENT_FIELD_DICTIONARY_PATH = (
    PROCESSED_AER_AGREEMENTS
    / (
        f"{CREATED_DATE:%Y%m%d}_"
        f"{CANCO2RE_SUBMISSION.activity_code}_"
        f"AERAgreementsFieldDictionary_"
        f"{CANCO2RE_SUBMISSION.creator_initials}.csv"
    )
)

TRACT_FIELD_DICTIONARY_PATH = (
    PROCESSED_AER_AGREEMENTS
    / (
        f"{CREATED_DATE:%Y%m%d}_"
        f"{CANCO2RE_SUBMISSION.activity_code}_"
        f"AERAgreementTractsFieldDictionary_"
        f"{CANCO2RE_SUBMISSION.creator_initials}.csv"
    )
)

TARGET_CRS = "EPSG:3978"
EXPECTED_SOURCE_CRS = "EPSG:3400"
EXPECTED_SHAPEFILE_NAME = "CS_Agreements.shp"


# =============================================================================
# Source metadata
# =============================================================================

DATASET_ID = "aer_agreements"

SOURCE_DATASET = "AER Carbon Sequestration Agreements"
SOURCE_ORGANIZATION = "Alberta Energy Regulator (AER)"
SOURCE_TITLE = "Carbon Sequestration Agreements"
SOURCE_YEAR = 2026

SOURCE_URL = (
    "https://gis.energy.gov.ab.ca/Geoview/CarbonSequestration"
)

SOURCE_PARENT_URL = (
    "https://www.alberta.ca/"
    "carbon-capture-utilization-and-storage-carbon-sequestration-tenure"
)

SOURCE_ARCHIVE_URL = (
    "https://gis.energy.gov.ab.ca/"
    "GeoviewData/CS_Agreements_Shape.zip"
)

SOURCE_DISCLAIMER = (
    "Carbon Sequestration Agreement boundaries are shown to the full ATS "
    "Landkey and may therefore appear to include minerals not owned by the "
    "Alberta Crown and/or minerals reserved from disposition. Detailed permit "
    "and lease searches should be confirmed with Alberta Crown Land Data "
    "Support."
)

ASSESSMENT_TYPE = "carbon_sequestration_agreement"
DATA_CLASS = "regulatory_tenure"
CAPACITY_DATA = False


# =============================================================================
# Explicit source-field mapping
# =============================================================================

SOURCE_FIELD_MAP = {
    "AgreementN": "agreement_id",
    "AgreementT": "agreement_type_code",
    "Tract": "tract_id",
    "MINTYPE": "mineral_type",
    "AGGROUP": "agreement_group",
    "Status": "status",
    "Vintage": "vintage",
    "DesRep": "designated_representative",
    "ZoneDesc": "zone_description",
    "ORGAREA": "original_area_ha",
    "AGREEAREA": "agreement_area_ha",
    "TERMDATE": "term_date",
    "CONTDATE": "continuation_date",
    "CUREXPIRY": "current_expiry",
    "Shape_STAr": "source_shape_area_m2",
    "Shape_STLe": "source_shape_length_m",
}

REQUIRED_SOURCE_FIELDS = set(SOURCE_FIELD_MAP)

DATE_FIELDS = (
    "term_date",
    "continuation_date",
    "current_expiry",
)

TEXT_IDENTIFIER_FIELDS = (
    "agreement_id",
    "tract_id",
    "agreement_type_code",
)

AGREEMENT_CONSISTENCY_FIELDS = (
    "agreement_group",
    "agreement_type_code",
    "mineral_type",
    "status",
    "vintage",
    "designated_representative",
    "original_area_ha",
    "agreement_area_ha",
    "term_date",
    "continuation_date",
    "current_expiry",
)

TRACT_COLUMNS = [
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
    "source_shape_area_m2",
    "source_shape_length_m",
    "geometry_area_m2",
    "geometry_area_ha",
    "geometry_perimeter_m",
    "source_dataset",
    "source_feature_id",
    "source_feature_uid",
    "source_crs",
    "assessment_type",
    "data_class",
    "capacity_data",
    "geometry",
]

AGREEMENT_COLUMNS = [
    "agreement_id",
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
    "source_dataset",
    "source_crs",
    "tract_count",
    "geometry_area_m2",
    "geometry_area_ha",
    "geometry_perimeter_m",
    "assessment_type",
    "data_class",
    "capacity_data",
    "geometry",
]


# =============================================================================
# Field dictionaries
# =============================================================================

TRACT_FIELD_DICTIONARY_RECORDS = [{'data_type': 'TEXT',
  'definition': 'AER agreement identifier.',
  'field': 'agreement_id',
  'notes': 'Preserved as text to retain the source identifier exactly.',
  'origin': 'source harmonized',
  'units': 'identifier'},
 {'data_type': 'TEXT',
  'definition': 'AER tract identifier within an agreement.',
  'field': 'tract_id',
  'notes': 'Preserved as text because source values contain leading zeros.',
  'origin': 'source harmonized',
  'units': 'identifier'},
 {'data_type': 'TEXT',
  'definition': 'Broad AER agreement category.',
  'field': 'agreement_group',
  'notes': 'Source values include LEASE, PERMIT, and APP.',
  'origin': 'source harmonized',
  'units': 'text'},
 {'data_type': 'TEXT',
  'definition': 'AER agreement type code.',
  'field': 'agreement_type_code',
  'notes': 'Source field AgreementT; codes include 058, 059, 061 and A-prefixed variants.',
  'origin': 'source harmonized',
  'units': 'code'},
 {'data_type': 'TEXT',
  'definition': 'Mineral or pore-space rights type reported by AER.',
  'field': 'mineral_type',
  'notes': 'All records in the 2026 source dataset are PORE SPACE.',
  'origin': 'source harmonized',
  'units': 'text'},
 {'data_type': 'TEXT',
  'definition': 'Agreement status reported by AER.',
  'field': 'status',
  'notes': 'All records in the 2026 source dataset are ACTIVE.',
  'origin': 'source harmonized',
  'units': 'text'},
 {'data_type': 'TEXT',
  'definition': 'AER vintage or agreement-term classification.',
  'field': 'vintage',
  'notes': 'Source documentation does not provide a formal field definition.',
  'origin': 'source harmonized',
  'units': 'text'},
 {'data_type': 'TEXT',
  'definition': 'Designated representative or agreement holder reported by AER.',
  'field': 'designated_representative',
  'notes': 'Renamed from source field DesRep.',
  'origin': 'source harmonized',
  'units': 'text'},
 {'data_type': 'TEXT',
  'definition': 'Geological pore-space interval or zone description associated with the tract.',
  'field': 'zone_description',
  'notes': 'May differ between tracts belonging to the same agreement.',
  'origin': 'source harmonized',
  'units': 'text'},
 {'data_type': 'REAL',
  'definition': 'Original agreement area reported by AER.',
  'field': 'original_area_ha',
  'notes': 'Agreement-level value repeated across tracts where an agreement contains multiple '
           'tracts.',
  'origin': 'source harmonized',
  'units': 'ha'},
 {'data_type': 'REAL',
  'definition': 'Current agreement area reported by AER.',
  'field': 'agreement_area_ha',
  'notes': 'Agreement-level value repeated across tracts where an agreement contains multiple '
           'tracts.',
  'origin': 'source harmonized',
  'units': 'ha'},
 {'data_type': 'DATE',
  'definition': 'Agreement term date reported by AER.',
  'field': 'term_date',
  'notes': 'Converted from the source text field TERMDATE.',
  'origin': 'source harmonized',
  'units': 'date'},
 {'data_type': 'DATE',
  'definition': 'Agreement continuation date reported by AER.',
  'field': 'continuation_date',
  'notes': 'Source field CONTDATE; null for all features in the 2026 source dataset.',
  'origin': 'source harmonized',
  'units': 'date'},
 {'data_type': 'DATE',
  'definition': 'Current agreement expiry date reported by AER.',
  'field': 'current_expiry',
  'notes': 'Converted from the source text field CUREXPIRY.',
  'origin': 'source harmonized',
  'units': 'date'},
 {'data_type': 'REAL',
  'definition': 'Area measurement stored with the original AER geometry.',
  'field': 'source_shape_area_m2',
  'notes': 'Preserved from source field Shape_STAr prior to reprojection.',
  'origin': 'source spatial',
  'units': 'm^2'},
 {'data_type': 'REAL',
  'definition': 'Boundary length measurement stored with the original AER geometry.',
  'field': 'source_shape_length_m',
  'notes': 'Preserved from source field Shape_STLe prior to reprojection.',
  'origin': 'source spatial',
  'units': 'm'},
 {'data_type': 'REAL',
  'definition': 'Feature area calculated from the harmonized EPSG:3978 geometry.',
  'field': 'geometry_area_m2',
  'notes': 'Recalculated after reprojection.',
  'origin': 'derived spatial',
  'units': 'm^2'},
 {'data_type': 'REAL',
  'definition': 'Feature area calculated from the harmonized EPSG:3978 geometry.',
  'field': 'geometry_area_ha',
  'notes': 'geometry_area_m2 divided by 10,000.',
  'origin': 'derived spatial',
  'units': 'ha'},
 {'data_type': 'REAL',
  'definition': 'Feature perimeter calculated from the harmonized EPSG:3978 geometry.',
  'field': 'geometry_perimeter_m',
  'notes': 'Recalculated after reprojection.',
  'origin': 'derived spatial',
  'units': 'm'},
 {'data_type': 'TEXT',
  'definition': 'Name of the Bronze source dataset from which the feature was derived.',
  'field': 'source_dataset',
  'notes': 'Set to AER Carbon Sequestration Agreements.',
  'origin': 'provenance',
  'units': 'text'},
 {'data_type': 'INTEGER',
  'definition': 'Sequential identifier assigned to the original source feature during '
                'harmonization.',
  'field': 'source_feature_id',
  'notes': 'Corresponds to the source feature row used in this Silver-layer workflow.',
  'origin': 'provenance',
  'units': 'identifier'},
 {'data_type': 'TEXT',
  'definition': 'Unique provenance identifier for the source tract feature.',
  'field': 'source_feature_uid',
  'notes': 'Constructed as agreement_id:tract_id.',
  'origin': 'provenance',
  'units': 'text identifier'},
 {'data_type': 'TEXT',
  'definition': 'Coordinate reference system of the original AER source geometry.',
  'field': 'source_crs',
  'notes': 'EPSG:3400 prior to conversion to EPSG:3978.',
  'origin': 'provenance',
  'units': 'CRS text'},
 {'data_type': 'TEXT',
  'definition': 'Type of storage-related assessment or dataset represented by the feature.',
  'field': 'assessment_type',
  'notes': 'Set to carbon_sequestration_agreement.',
  'origin': 'derived classification',
  'units': 'text'},
 {'data_type': 'TEXT',
  'definition': 'High-level role of the dataset within the geological storage data model.',
  'field': 'data_class',
  'notes': 'Set to regulatory_tenure.',
  'origin': 'derived classification',
  'units': 'text'},
 {'data_type': 'BOOLEAN',
  'definition': 'Flag indicating whether the dataset contains quantified CO2 storage capacity '
                'estimates.',
  'field': 'capacity_data',
  'notes': 'False; this dataset contains regulatory agreement information rather than storage '
           'capacity.',
  'origin': 'derived classification',
  'units': 'boolean'},
 {'data_type': 'POLYGON / MULTIPOLYGON',
  'definition': 'Polygonal geometry representing the AER carbon sequestration agreement tract.',
  'field': 'geometry',
  'notes': 'Stored in EPSG:3978.',
  'origin': 'source geometry reprojected',
  'units': 'geometry'}]

AGREEMENT_FIELD_DICTIONARY_RECORDS = [{'data_type': 'TEXT',
  'definition': 'AER agreement identifier.',
  'field': 'agreement_id',
  'notes': 'Preserved as text to retain the source identifier exactly.',
  'origin': 'source harmonized',
  'units': 'identifier'},
 {'data_type': 'TEXT',
  'definition': 'Broad AER agreement category.',
  'field': 'agreement_group',
  'notes': 'Source values include LEASE, PERMIT, and APP.',
  'origin': 'source harmonized',
  'units': 'text'},
 {'data_type': 'TEXT',
  'definition': 'AER agreement type code.',
  'field': 'agreement_type_code',
  'notes': 'Source field AgreementT; codes include 058, 059, 061 and A-prefixed variants.',
  'origin': 'source harmonized',
  'units': 'code'},
 {'data_type': 'TEXT',
  'definition': 'Mineral or pore-space rights type reported by AER.',
  'field': 'mineral_type',
  'notes': 'All records in the 2026 source dataset are PORE SPACE.',
  'origin': 'source harmonized',
  'units': 'text'},
 {'data_type': 'TEXT',
  'definition': 'Agreement status reported by AER.',
  'field': 'status',
  'notes': 'All records in the 2026 source dataset are ACTIVE.',
  'origin': 'source harmonized',
  'units': 'text'},
 {'data_type': 'TEXT',
  'definition': 'AER vintage or agreement-term classification.',
  'field': 'vintage',
  'notes': 'Source documentation does not provide a formal field definition.',
  'origin': 'source harmonized',
  'units': 'text'},
 {'data_type': 'TEXT',
  'definition': 'Designated representative or agreement holder reported by AER.',
  'field': 'designated_representative',
  'notes': 'Renamed from source field DesRep.',
  'origin': 'source harmonized',
  'units': 'text'},
 {'data_type': 'TEXT',
  'definition': 'Geological pore-space interval or zone description associated with the agreement.',
  'field': 'zone_description',
  'notes': 'For single-tract agreements this preserves the source tract description. For '
           "multi-tract agreements, unique tract-level zone descriptions are concatenated using ' "
           "| ' so that no geological interval information is discarded during dissolve.",
  'origin': 'source harmonized',
  'units': 'text'},
 {'data_type': 'REAL',
  'definition': 'Original agreement area reported by AER.',
  'field': 'original_area_ha',
  'notes': 'Agreement-level value repeated across tracts where an agreement contains multiple '
           'tracts.',
  'origin': 'source harmonized',
  'units': 'ha'},
 {'data_type': 'REAL',
  'definition': 'Current agreement area reported by AER.',
  'field': 'agreement_area_ha',
  'notes': 'Agreement-level value repeated across tracts where an agreement contains multiple '
           'tracts.',
  'origin': 'source harmonized',
  'units': 'ha'},
 {'data_type': 'DATE',
  'definition': 'Agreement term date reported by AER.',
  'field': 'term_date',
  'notes': 'Converted from the source text field TERMDATE.',
  'origin': 'source harmonized',
  'units': 'date'},
 {'data_type': 'DATE',
  'definition': 'Agreement continuation date reported by AER.',
  'field': 'continuation_date',
  'notes': 'Source field CONTDATE; null for all features in the 2026 source dataset.',
  'origin': 'source harmonized',
  'units': 'date'},
 {'data_type': 'DATE',
  'definition': 'Current agreement expiry date reported by AER.',
  'field': 'current_expiry',
  'notes': 'Converted from the source text field CUREXPIRY.',
  'origin': 'source harmonized',
  'units': 'date'},
 {'data_type': 'REAL',
  'definition': 'Feature area calculated from the harmonized EPSG:3978 geometry.',
  'field': 'geometry_area_m2',
  'notes': 'Recalculated after reprojection.',
  'origin': 'derived spatial',
  'units': 'm^2'},
 {'data_type': 'REAL',
  'definition': 'Feature area calculated from the harmonized EPSG:3978 geometry.',
  'field': 'geometry_area_ha',
  'notes': 'geometry_area_m2 divided by 10,000.',
  'origin': 'derived spatial',
  'units': 'ha'},
 {'data_type': 'REAL',
  'definition': 'Feature perimeter calculated from the harmonized EPSG:3978 geometry.',
  'field': 'geometry_perimeter_m',
  'notes': 'Recalculated after reprojection.',
  'origin': 'derived spatial',
  'units': 'm'},
 {'data_type': 'TEXT',
  'definition': 'Name of the Bronze source dataset from which the feature was derived.',
  'field': 'source_dataset',
  'notes': 'Set to AER Carbon Sequestration Agreements.',
  'origin': 'provenance',
  'units': 'text'},
 {'data_type': 'TEXT',
  'definition': 'Coordinate reference system of the original AER source geometry.',
  'field': 'source_crs',
  'notes': 'EPSG:3400 prior to conversion to EPSG:3978.',
  'origin': 'provenance',
  'units': 'CRS text'},
 {'data_type': 'TEXT',
  'definition': 'Type of storage-related assessment or dataset represented by the feature.',
  'field': 'assessment_type',
  'notes': 'Set to carbon_sequestration_agreement.',
  'origin': 'derived classification',
  'units': 'text'},
 {'data_type': 'TEXT',
  'definition': 'High-level role of the dataset within the geological storage data model.',
  'field': 'data_class',
  'notes': 'Set to regulatory_tenure.',
  'origin': 'derived classification',
  'units': 'text'},
 {'data_type': 'BOOLEAN',
  'definition': 'Flag indicating whether the dataset contains quantified CO2 storage capacity '
                'estimates.',
  'field': 'capacity_data',
  'notes': 'False; this dataset contains regulatory agreement information rather than storage '
           'capacity.',
  'origin': 'derived classification',
  'units': 'boolean'},
 {'data_type': 'INTEGER',
  'definition': 'Number of source AER tract features represented by the dissolved agreement '
                'geometry.',
  'field': 'tract_count',
  'notes': 'Most agreements contain one tract; two agreements in the 2026 source dataset contain '
           'two tracts.',
  'origin': 'derived',
  'units': 'count'},
 {'data_type': 'POLYGON / MULTIPOLYGON',
  'definition': 'Polygonal geometry representing the complete AER carbon sequestration agreement.',
  'field': 'geometry',
  'notes': 'Created by dissolving tract geometries by agreement_id and stored in EPSG:3978.',
  'origin': 'derived spatial',
  'units': 'geometry'}]


# =============================================================================
# TRACT QA TypedDict
# =============================================================================


class TractQA(TypedDict):
    """Typed QA summary produced while harmonizing the AER tract layer."""

    source_feature_count: int
    tract_feature_count: int
    source_crs: str
    silver_crs: str
    native_invalid_before_repair: int
    native_invalid_after_repair: int
    projected_invalid_before_repair: int
    projected_invalid_after_repair: int
    source_warning_count: int
    source_warnings: str

# =============================================================================
# Source discovery and inspection
# =============================================================================


def discover_source_shapefile() -> Path:
    """Discover and validate the single AER Bronze shapefile."""

    shapefiles = sorted(RAW_AER_SOURCE.rglob("*.shp"))

    if len(shapefiles) != 1:
        raise ValueError(
            "Expected exactly one AER Carbon Sequestration Agreement "
            f"shapefile under {RAW_AER_SOURCE}, found {len(shapefiles)}: "
            f"{[path.name for path in shapefiles]}"
        )

    path = shapefiles[0]

    if path.name != EXPECTED_SHAPEFILE_NAME:
        raise ValueError(
            "Unexpected AER source shapefile. "
            f"Expected {EXPECTED_SHAPEFILE_NAME!r}, found {path.name!r}."
        )

    return path


def read_source_layer(
    path: Path,
) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Read the Bronze shapefile and capture provider/driver warnings."""

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        gdf = gpd.read_file(path)

    warning_messages = [str(item.message) for item in caught]

    if gdf.crs is None:
        raise ValueError(f"Source shapefile has no CRS: {path}")

    return gdf, warning_messages


def build_schema_inventory(
    path: Path,
) -> pd.DataFrame:
    """Build a one-row inventory of the source AER schema."""

    gdf, warning_messages = read_source_layer(path)

    crs = gdf.crs
    if crs is None:
        raise ValueError(f"Source shapefile has no CRS: {path}")

    geometry_types = sorted(
        str(value)
        for value in gdf.geometry.geom_type.dropna().unique()
    )

    return pd.DataFrame(
        [
            {
                "source_file": path.name,
                "feature_count": len(gdf),
                "source_crs": crs.to_string(),
                "geometry_types": ", ".join(geometry_types),
                "column_count": len(gdf.columns),
                "columns": ", ".join(gdf.columns),
                "read_warnings": " | ".join(warning_messages),
            }
        ]
    )


# =============================================================================
# Source validation
# =============================================================================


def validate_source_schema(
    path: Path,
    gdf: gpd.GeoDataFrame,
) -> None:
    """Validate the expected AER source fields, geometry, and CRS."""

    missing = REQUIRED_SOURCE_FIELDS - set(gdf.columns)

    if missing:
        raise ValueError(
            f"{path.name} is missing required AER source fields: "
            f"{sorted(missing)}"
        )

    if gdf.empty:
        raise ValueError(f"{path.name} contains no features.")

    if gdf.geometry.isna().all():
        raise ValueError(f"{path.name} contains no usable geometry.")

    epsg = gdf.crs.to_epsg() if gdf.crs is not None else None
    if epsg != 3400:
        raise ValueError(
            f"Expected source CRS {EXPECTED_SOURCE_CRS}, found {gdf.crs}."
        )


# =============================================================================
# Geometry normalization
# =============================================================================


def repair_geometries(
    gdf: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, int, int]:
    """Repair topologically invalid geometries without altering Bronze files."""

    result = gdf.copy()

    non_null = result.geometry.notna()
    invalid_before_mask = non_null & ~result.geometry.is_valid
    invalid_before = int(invalid_before_mask.sum())

    if invalid_before:
        result.loc[invalid_before_mask, "geometry"] = (
            result.loc[invalid_before_mask, "geometry"]
            .apply(make_valid)
        )

    invalid_after_mask = result.geometry.notna() & ~result.geometry.is_valid
    invalid_after = int(invalid_after_mask.sum())

    if invalid_after:
        raise ValueError(
            f"Geometry repair left {invalid_after} invalid geometries."
        )

    return result, invalid_before, invalid_after


def validate_target_crs(gdf: gpd.GeoDataFrame) -> None:
    """Require the canonical Silver CRS."""

    if gdf.crs is None or gdf.crs.to_epsg() != 3978:
        raise ValueError(
            f"Expected Silver CRS {TARGET_CRS}, found {gdf.crs}."
        )


# =============================================================================
# Attribute normalization
# =============================================================================


def normalize_text_identifier(series: pd.Series) -> pd.Series:
    """Normalize identifier values as nullable strings without losing zeros."""

    result = series.astype("string")
    return result.str.strip()


def parse_date_series(
    series: pd.Series,
    *,
    field_name: str,
) -> pd.Series:
    """Parse source date values while rejecting unparseable non-null values."""

    parsed = pd.to_datetime(series, errors="coerce")

    invalid = series.notna() & parsed.isna()

    if invalid.any():
        examples = series.loc[invalid].astype(str).unique()[:5]
        raise ValueError(
            f"{field_name} contains unparseable non-null date values: "
            f"{examples.tolist()}"
        )

    return parsed


def combine_unique_text(series: pd.Series) -> str | None:
    """Concatenate distinct non-empty strings while preserving source order."""

    values = (
        series
        .dropna()
        .astype(str)
        .str.strip()
    )

    values = [value for value in values if value]

    if not values:
        return None

    return " | ".join(dict.fromkeys(values))


# =============================================================================
# Tract harmonization
# =============================================================================


def build_tract_layer(
    path: Path,
) -> tuple[
    gpd.GeoDataFrame,
    pd.DataFrame,
    TractQA,
]:
    """Build the Silver agreement-tract layer from the Bronze shapefile."""

    source, warning_messages = read_source_layer(path)
    validate_source_schema(path, source)

    crs = source.crs
    if crs is None:
        raise ValueError(f"Source shapefile has no CRS: {path}")

    source_crs = crs.to_string()
    source_feature_count = len(source)

    source, invalid_native_before, invalid_native_after = repair_geometries(
        source
    )

    clean = source.rename(columns=SOURCE_FIELD_MAP).copy()

    for field in TEXT_IDENTIFIER_FIELDS:
        clean[field] = normalize_text_identifier(clean[field])

    for field in DATE_FIELDS:
        clean[field] = parse_date_series(
            clean[field],
            field_name=field,
        )

    numeric_fields = (
        "original_area_ha",
        "agreement_area_ha",
        "source_shape_area_m2",
        "source_shape_length_m",
    )

    for field in numeric_fields:
        raw = clean[field]
        numeric = pd.to_numeric(raw, errors="coerce")
        invalid = raw.notna() & numeric.isna()

        if invalid.any():
            examples = raw.loc[invalid].astype(str).unique()[:5]
            raise ValueError(
                f"{field} contains non-numeric values: {examples.tolist()}"
            )

        clean[field] = numeric

    if clean["agreement_id"].isna().any():
        raise ValueError("AER source contains null agreement identifiers.")

    if clean["tract_id"].isna().any():
        raise ValueError("AER source contains null tract identifiers.")

    clean["source_feature_id"] = pd.Series(
        range(len(clean)),
        index=clean.index,
        dtype="Int64",
    )

    clean["source_feature_uid"] = (
        clean["agreement_id"].astype(str)
        + ":"
        + clean["tract_id"].astype(str)
    )

    if clean["source_feature_uid"].duplicated().any():
        duplicates = (
            clean.loc[
                clean["source_feature_uid"].duplicated(keep=False),
                "source_feature_uid",
            ]
            .astype(str)
            .unique()
            .tolist()
        )
        raise ValueError(
            "AER source contains duplicate agreement/tract identifiers: "
            f"{duplicates}"
        )

    measurement_check = clean[
        [
            "agreement_id",
            "tract_id",
            "source_shape_area_m2",
            "source_shape_length_m",
        ]
    ].copy()

    clean = clean.to_crs(TARGET_CRS)
    validate_target_crs(clean)

    clean, invalid_projected_before, invalid_projected_after = (
        repair_geometries(clean)
    )

    clean["geometry_area_m2"] = clean.geometry.area
    clean["geometry_area_ha"] = clean["geometry_area_m2"] / 10_000.0
    clean["geometry_perimeter_m"] = clean.geometry.length

    measurement_check["geometry_area_m2"] = clean["geometry_area_m2"].to_numpy()
    measurement_check["geometry_perimeter_m"] = (
        clean["geometry_perimeter_m"].to_numpy()
    )

    measurement_check["source_to_silver_area_ratio"] = (
        measurement_check["source_shape_area_m2"]
        / measurement_check["geometry_area_m2"]
    )

    measurement_check["source_to_silver_length_ratio"] = (
        measurement_check["source_shape_length_m"]
        / measurement_check["geometry_perimeter_m"]
    )

    clean["source_dataset"] = SOURCE_DATASET
    clean["source_crs"] = EXPECTED_SOURCE_CRS
    clean["assessment_type"] = ASSESSMENT_TYPE
    clean["data_class"] = DATA_CLASS
    clean["capacity_data"] = CAPACITY_DATA

    tract_gdf = gpd.GeoDataFrame(
        clean[TRACT_COLUMNS].copy(),
        geometry="geometry",
        crs=TARGET_CRS,
    )

    qa: TractQA = {
        "source_feature_count": source_feature_count,
        "tract_feature_count": len(tract_gdf),
        "source_crs": source_crs,
        "silver_crs": TARGET_CRS,
        "native_invalid_before_repair": invalid_native_before,
        "native_invalid_after_repair": invalid_native_after,
        "projected_invalid_before_repair": invalid_projected_before,
        "projected_invalid_after_repair": invalid_projected_after,
        "source_warning_count": len(warning_messages),
        "source_warnings": " | ".join(warning_messages),
    }

    return tract_gdf, measurement_check, qa


# =============================================================================
# Agreement-level construction
# =============================================================================


def validate_agreement_consistency(
    tract_gdf: gpd.GeoDataFrame,
) -> None:
    """Validate attributes that must remain uniform within each agreement."""

    consistency = (
        tract_gdf
        .groupby("agreement_id")[list(AGREEMENT_CONSISTENCY_FIELDS)]
        .nunique(dropna=False)
    )

    inconsistent = consistency[
        (consistency > 1).any(axis=1)
    ]

    if not inconsistent.empty:
        details = {
            agreement_id: row[row > 1].index.tolist()
            for agreement_id, row in inconsistent.iterrows()
        }
        raise ValueError(
            "Agreement-level source attributes differ between tracts: "
            f"{details}"
        )


def build_agreement_layer(
    tract_gdf: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Dissolve tract features to one feature per AER agreement."""

    validate_agreement_consistency(tract_gdf)

    agreement_gdf = (
        tract_gdf
        .dissolve(
            by="agreement_id",
            as_index=False,
            aggfunc={
                "agreement_group": "first",
                "agreement_type_code": "first",
                "mineral_type": "first",
                "status": "first",
                "vintage": "first",
                "designated_representative": "first",
                "zone_description": combine_unique_text,
                "original_area_ha": "first",
                "agreement_area_ha": "first",
                "term_date": "first",
                "continuation_date": "first",
                "current_expiry": "first",
                "source_dataset": "first",
                "source_crs": "first",
            },
        )
    )

    agreement_gdf["tract_count"] = (
        tract_gdf
        .groupby("agreement_id")
        .size()
        .reindex(agreement_gdf["agreement_id"])
        .to_numpy()
    )

    agreement_gdf["geometry_area_m2"] = agreement_gdf.geometry.area
    agreement_gdf["geometry_area_ha"] = (
        agreement_gdf["geometry_area_m2"] / 10_000.0
    )
    agreement_gdf["geometry_perimeter_m"] = agreement_gdf.geometry.length

    agreement_gdf["assessment_type"] = ASSESSMENT_TYPE
    agreement_gdf["data_class"] = DATA_CLASS
    agreement_gdf["capacity_data"] = CAPACITY_DATA

    agreement_gdf = gpd.GeoDataFrame(
        agreement_gdf[AGREEMENT_COLUMNS].copy(),
        geometry="geometry",
        crs=TARGET_CRS,
    )

    agreement_gdf, _, invalid_after = repair_geometries(
        agreement_gdf
    )

    if invalid_after:
        raise ValueError(
            "Agreement dissolve produced invalid geometries."
        )

    if agreement_gdf["agreement_id"].duplicated().any():
        raise ValueError(
            "Agreement-level layer contains duplicate agreement_id values."
        )

    return agreement_gdf


# =============================================================================
# Metadata and QA
# =============================================================================


def build_metadata_table() -> pd.DataFrame:
    """Build dataset-level AER provenance and interpretation metadata."""

    records = [
        ("title", "Alberta Carbon Sequestration Agreements"),
        (
            "who",
            (
                f"{CANCO2RE_SUBMISSION.creator_name}, "
                f"CanCO2Re Activity {CANCO2RE_SUBMISSION.activity_code}"
            ),
        ),
        (
            "when",
            CREATED_DATE.isoformat(),
        ),
        (
            "submission_filename",
            SILVER_GPKG_PATH.name,
        ),
        (
            "activity_code",
            CANCO2RE_SUBMISSION.activity_code,
        ),
        (
            "creator_initials",
            CANCO2RE_SUBMISSION.creator_initials,
        ),
        ("data_class", DATA_CLASS),
        ("assessment_type", ASSESSMENT_TYPE),
        ("capacity_data", str(CAPACITY_DATA)),
        ("source_title", SOURCE_TITLE),
        ("source_organization", SOURCE_ORGANIZATION),
        ("source_year", str(SOURCE_YEAR)),
        ("source_url", SOURCE_URL),
        ("source_parent_url", SOURCE_PARENT_URL),
        ("source_archive_url", SOURCE_ARCHIVE_URL),
        (
            "source_documentation",
            "No standalone technical data dictionary was supplied with the "
            "download. Source documentation consists primarily of provider "
            "shapefile metadata and the information accompanying the AER "
            "download interface."
        ),
        ("source_disclaimer", SOURCE_DISCLAIMER),
        (
            "what",
            "Harmonized Alberta carbon sequestration agreement polygons "
            "representing regulatory pore-space agreements and associated "
            "agreement attributes. The dataset does not provide quantified "
            "geological storage capacity, injectivity, storage probability, "
            "or project-ready storage resource."
        ),
        (
            "where",
            "Alberta, Canada; source CRS EPSG:3400; Silver CRS EPSG:3978."
        ),
        (
            "how",
            "Derived from the Alberta Energy Regulator Carbon Sequestration "
            "Agreements shapefile. Source fields are standardized, dates are "
            "normalized, original geometry measurements are retained, "
            "geometries are reprojected from EPSG:3400 to EPSG:3978, geometry "
            "measurements are recalculated, feature-level provenance is added, "
            "and agreement geometries are produced by dissolving tracts by "
            "agreement identifier. Distinct tract-level zone descriptions are "
            "preserved during dissolve."
        ),
        (
            "use_limitations",
            "Agreement polygons represent regulatory or tenure information "
            "associated with carbon sequestration pore-space rights. They must "
            "not be interpreted as quantified CO2 storage capacity, injectivity, "
            "geological prospectivity, permitted injection capacity, or "
            "project-ready storage resource."
        ),
        (
            "keywords",
            "carbon storage; CO2 storage; CCUS; pore space; carbon sequestration "
            "agreement; Alberta; Alberta Energy Regulator"
        ),
        ("source_crs", EXPECTED_SOURCE_CRS),
        ("silver_crs", TARGET_CRS),
        ("bronze_layer_count", "1"),
    ]

    return pd.DataFrame(
        records,
        columns=["key", "value"],
    )


def build_qa_table(
    tract_gdf: gpd.GeoDataFrame,
    agreement_gdf: gpd.GeoDataFrame,
    measurement_check: pd.DataFrame,
    tract_qa: TractQA,
) -> pd.DataFrame:
    """Build dataset-level QA checks before final artifact validation."""

    records = [
        ("source_feature_count", tract_qa["source_feature_count"]),
        ("tract_feature_count", int(len(tract_gdf))),
        ("agreement_feature_count", int(len(agreement_gdf))),
        (
            "unique_agreement_count",
            int(tract_gdf["agreement_id"].nunique()),
        ),
        (
            "multi_tract_agreement_count",
            int((agreement_gdf["tract_count"] > 1).sum()),
        ),
        (
            "tract_null_geometry_count",
            int(tract_gdf.geometry.isna().sum()),
        ),
        (
            "tract_empty_geometry_count",
            int(tract_gdf.geometry.is_empty.sum()),
        ),
        (
            "tract_invalid_geometry_count",
            int((~tract_gdf.geometry.is_valid).sum()),
        ),
        (
            "agreement_null_geometry_count",
            int(agreement_gdf.geometry.isna().sum()),
        ),
        (
            "agreement_empty_geometry_count",
            int(agreement_gdf.geometry.is_empty.sum()),
        ),
        (
            "agreement_invalid_geometry_count",
            int((~agreement_gdf.geometry.is_valid).sum()),
        ),
        ("source_crs", EXPECTED_SOURCE_CRS),
        ("silver_crs", TARGET_CRS),
        (
            "median_source_to_silver_area_ratio",
            float(
                measurement_check[
                    "source_to_silver_area_ratio"
                ].median()
            ),
        ),
        (
            "median_source_to_silver_length_ratio",
            float(
                measurement_check[
                    "source_to_silver_length_ratio"
                ].median()
            ),
        ),
        (
            "native_invalid_before_repair",
            tract_qa["native_invalid_before_repair"],
        ),
        (
            "native_invalid_after_repair",
            tract_qa["native_invalid_after_repair"],
        ),
        (
            "projected_invalid_before_repair",
            tract_qa["projected_invalid_before_repair"],
        ),
        (
            "projected_invalid_after_repair",
            tract_qa["projected_invalid_after_repair"],
        ),
        (
            "source_warning_count",
            tract_qa["source_warning_count"],
        ),
        (
            "source_warnings",
            tract_qa["source_warnings"],
        ),
    ]

    return pd.DataFrame(
        records,
        columns=["check", "value"],
    )


def build_field_dictionaries() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build the tract- and agreement-layer field dictionaries."""

    tract_dictionary = pd.DataFrame(
        TRACT_FIELD_DICTIONARY_RECORDS
    )

    agreement_dictionary = pd.DataFrame(
        AGREEMENT_FIELD_DICTIONARY_RECORDS
    )

    return tract_dictionary, agreement_dictionary


# =============================================================================
# Post-export validation
# =============================================================================


def validate_written_spatial_layer(
    *,
    layer_name: str,
    expected: gpd.GeoDataFrame,
    unique_id_field: str,
) -> gpd.GeoDataFrame:
    """Reopen and validate one persisted Silver spatial layer."""

    written = gpd.read_file(
        SILVER_GPKG_PATH,
        layer=layer_name,
    )

    validate_target_crs(written)

    if len(written) != len(expected):
        raise ValueError(
            f"{layer_name} feature count changed during export: "
            f"{len(written)} != {len(expected)}."
        )

    if written[unique_id_field].duplicated().any():
        raise ValueError(
            f"{layer_name} contains duplicate {unique_id_field} values."
        )

    if set(written[unique_id_field]) != set(expected[unique_id_field]):
        raise ValueError(
            f"{layer_name} identifiers changed during export."
        )

    null_count = int(written.geometry.isna().sum())
    empty_count = int(written.geometry.is_empty.sum())
    invalid_count = int((~written.geometry.is_valid).sum())

    if null_count:
        raise ValueError(
            f"{layer_name} contains {null_count} null geometries."
        )

    if empty_count:
        raise ValueError(
            f"{layer_name} contains {empty_count} empty geometries."
        )

    if invalid_count:
        raise ValueError(
            f"{layer_name} contains {invalid_count} invalid geometries "
            "after GeoPackage serialization."
        )

    return written


def validate_registered_tables() -> None:
    """Require the metadata and QA tables to be registered in the GeoPackage."""

    with sqlite3.connect(SILVER_GPKG_PATH) as conn:
        contents = pd.read_sql_query(
            """
            SELECT table_name, data_type
            FROM gpkg_contents
            """,
            conn,
        )

    expected = {
        "aer_agreement_tracts": "features",
        "aer_agreements": "features",
        "metadata_aer_agreements": "attributes",
        "qa_aer_agreements": "attributes",
    }

    actual = dict(
        zip(
            contents["table_name"],
            contents["data_type"],
            strict=False,
        )
    )

    missing_or_wrong = {
        name: data_type
        for name, data_type in expected.items()
        if actual.get(name) != data_type
    }

    if missing_or_wrong:
        raise ValueError(
            "GeoPackage contents are missing expected registered layers/tables: "
            f"{missing_or_wrong}"
        )


# =============================================================================
# Export
# =============================================================================


def export_outputs(
    *,
    tract_gdf: gpd.GeoDataFrame,
    agreement_gdf: gpd.GeoDataFrame,
    metadata: pd.DataFrame,
    qa: pd.DataFrame,
    schema_inventory: pd.DataFrame,
    tract_dictionary: pd.DataFrame,
    agreement_dictionary: pd.DataFrame,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Write and validate the complete AER Silver artifact."""

    PROCESSED_AER_AGREEMENTS.mkdir(
        parents=True,
        exist_ok=True,
    )

    if SILVER_GPKG_PATH.exists():
        SILVER_GPKG_PATH.unlink()

    tract_gdf.to_file(
        SILVER_GPKG_PATH,
        layer="aer_agreement_tracts",
        driver="GPKG",
    )

    agreement_gdf.to_file(
        SILVER_GPKG_PATH,
        layer="aer_agreements",
        driver="GPKG",
    )

    with sqlite3.connect(SILVER_GPKG_PATH) as conn:
        metadata.to_sql(
            "metadata_aer_agreements",
            conn,
            if_exists="replace",
            index=False,
        )

        qa.to_sql(
            "qa_aer_agreements",
            conn,
            if_exists="replace",
            index=False,
        )

        conn.execute(
            """
            INSERT OR REPLACE INTO gpkg_contents (
                table_name,
                data_type,
                identifier,
                description
            )
            VALUES (?, 'attributes', ?, ?)
            """,
            (
                "metadata_aer_agreements",
                "metadata_aer_agreements",
                "Dataset-level provenance, processing, and use metadata.",
            ),
        )

        conn.execute(
            """
            INSERT OR REPLACE INTO gpkg_contents (
                table_name,
                data_type,
                identifier,
                description
            )
            VALUES (?, 'attributes', ?, ?)
            """,
            (
                "qa_aer_agreements",
                "qa_aer_agreements",
                "Dataset-level quality-assurance and validation summary.",
            ),
        )

    schema_inventory.to_csv(
        SCHEMA_INVENTORY_PATH,
        index=False,
    )

    tract_dictionary.to_csv(
        TRACT_FIELD_DICTIONARY_PATH,
        index=False,
    )

    agreement_dictionary.to_csv(
        AGREEMENT_FIELD_DICTIONARY_PATH,
        index=False,
    )

    final_tracts = validate_written_spatial_layer(
        layer_name="aer_agreement_tracts",
        expected=tract_gdf,
        unique_id_field="source_feature_uid",
    )

    final_agreements = validate_written_spatial_layer(
        layer_name="aer_agreements",
        expected=agreement_gdf,
        unique_id_field="agreement_id",
    )

    validate_registered_tables()

    print("\nSilver outputs")
    print("--------------")
    print(f"GeoPackage:       {SILVER_GPKG_PATH}")
    print(f"Schema inventory: {SCHEMA_INVENTORY_PATH}")
    print(f"Tract dictionary: {TRACT_FIELD_DICTIONARY_PATH}")
    print(f"Agreement dict.:  {AGREEMENT_FIELD_DICTIONARY_PATH}")

    return final_tracts, final_agreements


# =============================================================================
# Workflow
# =============================================================================


def run_harmonization(
    *,
    inspect_only: bool = False,
) -> None:
    """Run source inspection or the complete AER Silver build."""

    source_path = discover_source_shapefile()

    print("AER Carbon Sequestration Agreement harmonization")
    print("-----------------------------------------------")
    print(f"Source file: {source_path}")
    print(f"Expected source CRS: {EXPECTED_SOURCE_CRS}")
    print(f"Target CRS:          {TARGET_CRS}\n")

    schema_inventory = build_schema_inventory(source_path)

    PROCESSED_AER_AGREEMENTS.mkdir(
        parents=True,
        exist_ok=True,
    )

    schema_inventory.to_csv(
        SCHEMA_INVENTORY_PATH,
        index=False,
    )

    if inspect_only:
        print(f"Saved schema inventory: {SCHEMA_INVENTORY_PATH}")
        return

    tract_gdf, measurement_check, tract_qa = build_tract_layer(
        source_path
    )

    agreement_gdf = build_agreement_layer(
        tract_gdf
    )

    metadata = build_metadata_table()

    qa = build_qa_table(
        tract_gdf=tract_gdf,
        agreement_gdf=agreement_gdf,
        measurement_check=measurement_check,
        tract_qa=tract_qa,
    )

    tract_dictionary, agreement_dictionary = (
        build_field_dictionaries()
    )

    final_tracts, final_agreements = export_outputs(
        tract_gdf=tract_gdf,
        agreement_gdf=agreement_gdf,
        metadata=metadata,
        qa=qa,
        schema_inventory=schema_inventory,
        tract_dictionary=tract_dictionary,
        agreement_dictionary=agreement_dictionary,
    )

    readme_text = build_readme(
        output_filename=SILVER_GPKG_PATH.name,
        tract_layer_name="aer_agreement_tracts",
        agreement_layer_name="aer_agreements",
        tract_dictionary_filename=TRACT_FIELD_DICTIONARY_PATH.name,
        agreement_dictionary_filename=AGREEMENT_FIELD_DICTIONARY_PATH.name,
        tract_feature_count=len(final_tracts),
        agreement_feature_count=len(final_agreements),
        multi_tract_agreement_count=int(
            (final_agreements["tract_count"] > 1).sum()
        ),
        target_crs=TARGET_CRS,
        tract_invalid_geometry_count=int(
            (~final_tracts.geometry.is_valid).sum()
        ),
        agreement_invalid_geometry_count=int(
            (~final_agreements.geometry.is_valid).sum()
        ),
        median_area_ratio=float(
            measurement_check[
                "source_to_silver_area_ratio"
            ].median()
        ),
        median_length_ratio=float(
            measurement_check[
                "source_to_silver_length_ratio"
            ].median()
        ),
        created_date=CREATED_DATE,
    )

    write_readme(
        README_PATH,
        readme_text,
    )

    print(f"README:            {README_PATH}")

    print("\nHarmonization summary")
    print("---------------------")
    print(f"Tract features:     {len(final_tracts):,}")
    print(f"Agreement features: {len(final_agreements):,}")
    print(
        "Multi-tract agreements: "
        f"{int((final_agreements['tract_count'] > 1).sum()):,}"
    )
    print(f"CRS:                {final_tracts.crs}")
    print(
        "Tract invalid geometries: "
        f"{int((~final_tracts.geometry.is_valid).sum()):,}"
    )
    print(
        "Agreement invalid geometries: "
        f"{int((~final_agreements.geometry.is_valid).sum()):,}"
    )


# =============================================================================
# CLI
# =============================================================================


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Inspect or harmonize Alberta Carbon Sequestration Agreement "
            "source data."
        )
    )

    parser.add_argument(
        "--inspect-only",
        action="store_true",
        help=(
            "Inspect and export the source schema inventory without "
            "building the Silver GeoPackage."
        ),
    )

    return parser.parse_args()


def main() -> None:
    """Run the AER harmonization workflow."""

    args = parse_args()

    run_harmonization(
        inspect_only=args.inspect_only,
    )


if __name__ == "__main__":
    main()
