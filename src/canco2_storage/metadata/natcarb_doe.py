"""Generate the NATCARB v1502 README from the persisted Silver GeoPackage.

The GeoPackage is the authoritative documentation source for dataset-level
metadata and QA. This module reads the registered ``metadata_natcarb_doe`` and
``qa_natcarb_doe`` attribute tables, validates the expected CanCO2Re package
contract, and renders the human-readable README.

The harmonizer remains responsible for creating the Silver data artifact.
This module does not modify the GeoPackage.
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd

from canco2_storage.metadata.common import (
    CANCO2RE_SUBMISSION,
    format_int,
    markdown_list,
    numbered_steps,
    write_readme,
)
from canco2_storage.paths import find_project_root


# =============================================================================
# Dataset identity and paths
# =============================================================================

DATA_TYPE = "NATCARBStorage"
DATASET_ID = "natcarb_doe"

TITLE = "NATCARB v1502 Geological CO₂ Storage Resources"

SOURCE_PAGE = "https://edx.netl.doe.gov/dataset/natcarb"
SOURCE_RESOURCE_PAGE = "https://edx.netl.doe.gov/dataset/natcarb-alldata-v1502"

USE_LIMITATIONS = (
    "NATCARB storage-resource estimates are regional screening estimates and "
    "must not be interpreted as permitted injection capacity, demonstrated "
    "injectivity, project-ready capacity, or a substitute for site-specific "
    "geological characterization. Provider-flagged duplicate and overlapping "
    "resources require care in aggregation."
)

KEYWORDS = (
    "carbon storage; CO2 storage; CCUS; geological storage; saline aquifer; "
    "coal; oil and gas; NATCARB; DOE; NETL; North America"
)

METADATA_TABLE = "metadata_natcarb_doe"
QA_TABLE = "qa_natcarb_doe"

EXPECTED_GPKG_CONTENTS = {
    "saline_resource_cells": "features",
    "saline_resource_areas": "features",
    "coal_resource_cells": "features",
    "coal_resource_areas": "features",
    "oil_gas_resources": "features",
    "domain_state": "attributes",
    "domain_fuel": "attributes",
    "domain_overlap": "attributes",
    "domain_duplicate": "attributes",
    "domain_arra": "attributes",
    "domain_source_types": "attributes",
    "domain_med_calced": "attributes",
    "domain_partnership": "attributes",
    "domain_oil_gas": "attributes",
    "domain_assessed": "attributes",
    METADATA_TABLE: "attributes",
    QA_TABLE: "attributes",
}

PROJECT_ROOT = find_project_root()

PROCESSED_NATCARB = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / DATASET_ID
)


# =============================================================================
# Structural documentation text
# =============================================================================

DATASET_ROLE = (
    "Silver-layer harmonization of DOE/NETL NATCARB All Data v1502 geological "
    "CO₂ storage-resource data. The Silver artifact preserves saline, coal, "
    "and oil/gas storage-resource representations together with the provider "
    "domain tables required to interpret coded NATCARB attributes."
)

PACKAGE_PURPOSE = (
    "This package is intended for regional- to continental-scale geological "
    "storage screening and cross-dataset comparison. Quantitative storage "
    "resource estimates are preserved where NATCARB reports them."
)

PROCESSING_STEPS = (
    "Reading the five NATCARB v1502 geological storage-resource feature classes "
    "from the provider File Geodatabase.",
    "Preserving the provider FileGDB feature identifier as `source_fid` and "
    "constructing stable namespaced `natcarb_id` values.",
    "Validating each source layer against an explicit required-field specification.",
    "Harmonizing source attribute names into descriptive Silver-layer field names.",
    "Preserving `COL_ROW` as the NATCARB analytical grid-cell identifier rather "
    "than treating it as a feature primary key.",
    "Preserving 10 km grid and resource-area polygons as separate source "
    "representations rather than imposing a parent-child relationship.",
    "Converting documented source units for depth, thickness, pressure, "
    "temperature, and porosity into standardized Silver fields.",
    "Preserving provider P10/P50/P90 storage-resource estimates in metric tonnes.",
    "Preserving NATCARB `ASSESSED`, `OVERLAP`, `DUPLICATE`, and `MED_CALCED` "
    "semantics as explicit harmonized fields.",
    "Retaining provider-flagged duplicate and overlapping resources rather than "
    "silently removing or aggregating them.",
    "Repairing invalid geometries when required and reprojecting all spatial "
    "layers to EPSG:3978.",
    "Recalculating geometry area and perimeter in the Silver CRS.",
    "Registering the ten NATCARB provider domain tables as GeoPackage attribute tables.",
    "Writing dataset-level metadata and QA tables into the GeoPackage.",
    "Reopening every persisted spatial layer and validating feature counts, "
    "identifiers, CRS, and geometry validity.",
    "Exporting standardized source-schema, source-metadata, QA-summary, and "
    "combined field-dictionary sidecars.",
)

STORAGE_INTERPRETATION = (
    "`saline_resource_cells` and `coal_resource_cells` represent "
    "geological-resource-by-grid-cell records; multiple resources may occupy "
    "the same NATCARB grid cell.",
    "Resource grid cells and resource-area polygons are related NATCARB products "
    "but are retained independently because the source attributes do not support "
    "a universally deterministic relational key.",
    "`storage_p10_tonnes`, `storage_p50_tonnes`, and `storage_p90_tonnes` preserve "
    "NATCARB low, medium, and high storage-resource estimates in metric tonnes.",
    "`assessed = False` represents a resource NATCARB identifies as not assessed; "
    "documented storage estimates should therefore be null.",
    "`duplicate = True` and `overlap = True` preserve provider quality/provenance "
    "flags. These records are not automatically removed in the canonical Silver product.",
    "`p50_method = natural_log_mean` identifies records where NATCARB indicates "
    "that the medium estimate was calculated from the low and high estimates.",
    "Reservoir-property coverage is source-dependent. Null geological-property "
    "fields are retained as missing rather than imputed.",
    "Quantified storage-resource estimates are screening values and should not be "
    "interpreted as demonstrated injection performance.",
)

REGISTERED_CONTENT_DESCRIPTIONS = (
    "`saline_resource_cells` — quantitative saline-resource records represented "
    "on the NATCARB 10 km analytical grid.",
    "`saline_resource_areas` — saline-resource extent polygons.",
    "`coal_resource_cells` — quantitative coal-resource records represented on "
    "the NATCARB 10 km analytical grid.",
    "`coal_resource_areas` — coal-resource extent polygons.",
    "`oil_gas_resources` — oil/gas storage-resource polygons with reservoir "
    "attributes and storage estimates where reported.",
    "`domain_state` — provider state/province lookup table.",
    "`domain_fuel` — provider fuel lookup table.",
    "`domain_overlap` — provider overlap-flag definitions.",
    "`domain_duplicate` — provider duplicate-flag definitions.",
    "`domain_arra` — provider ARRA-project lookup table.",
    "`domain_source_types` — provider source-type lookup table.",
    "`domain_med_calced` — provider medium-estimate method definitions.",
    "`domain_partnership` — NATCARB partnership lookup table.",
    "`domain_oil_gas` — provider oil/gas field-type lookup table.",
    "`domain_assessed` — provider assessed-status definitions.",
    f"`{METADATA_TABLE}` — dataset-level provenance, interpretation, "
    "classification, and submission metadata.",
    f"`{QA_TABLE}` — dataset-level quality-assurance summary.",
)


# =============================================================================
# GeoPackage readers and validation
# =============================================================================

def discover_silver_gpkg(
    processed_dir: Path = PROCESSED_NATCARB,
) -> Path:
    """Return the most recent NATCARB Silver GeoPackage by filename."""

    candidates = sorted(
        processed_dir.glob(
            f"*_{CANCO2RE_SUBMISSION.activity_code}_"
            f"{DATA_TYPE}_{CANCO2RE_SUBMISSION.creator_initials}.gpkg"
        )
    )

    if not candidates:
        raise FileNotFoundError(
            "No NATCARB Silver GeoPackage found under "
            f"{processed_dir}."
        )

    return candidates[-1]


def read_registered_contents(
    gpkg_path: Path,
) -> pd.DataFrame:
    """Read the GeoPackage contents registry."""

    with sqlite3.connect(gpkg_path) as conn:
        return pd.read_sql_query(
            """
            SELECT table_name, data_type, identifier, description
            FROM gpkg_contents
            ORDER BY table_name
            """,
            conn,
        )


def validate_registered_contents(
    gpkg_path: Path,
) -> pd.DataFrame:
    """Require the expected NATCARB CanCO2Re GeoPackage table contract."""

    contents = read_registered_contents(gpkg_path)

    actual = dict(
        zip(
            contents["table_name"],
            contents["data_type"],
            strict=False,
        )
    )

    missing_or_wrong = {
        table_name: data_type
        for table_name, data_type in EXPECTED_GPKG_CONTENTS.items()
        if actual.get(table_name) != data_type
    }

    if missing_or_wrong:
        raise ValueError(
            "GeoPackage contents do not satisfy the expected NATCARB "
            f"package contract: {missing_or_wrong}"
        )

    return contents


def read_key_value_table(
    gpkg_path: Path,
    *,
    table_name: str,
    key_column: str,
    key_aliases: tuple[str, ...] = (),
) -> dict[str, str]:
    """Read one registered key/value attribute table as a dictionary.

    The preferred key column is supplied by ``key_column``. ``key_aliases``
    supports previously persisted Silver artifacts whose metadata tables used
    descriptive column names such as ``metadata_field`` or ``qa_check``.
    """

    with sqlite3.connect(gpkg_path) as conn:
        frame = pd.read_sql_query(
            f'SELECT * FROM "{table_name}"',
            conn,
        )

    available_key_columns = (
        key_column,
        *key_aliases,
    )
    resolved_key_column = next(
        (
            column
            for column in available_key_columns
            if column in frame.columns
        ),
        None,
    )

    if resolved_key_column is None:
        raise ValueError(
            f"{table_name} is missing a supported key column. "
            f"Expected one of: {list(available_key_columns)}; "
            f"found: {list(frame.columns)}"
        )

    if "value" not in frame.columns:
        raise ValueError(
            f"{table_name} is missing required column: 'value'"
        )

    if frame[resolved_key_column].isna().any():
        raise ValueError(
            f"{table_name}.{resolved_key_column} contains null keys."
        )

    if frame[resolved_key_column].duplicated().any():
        duplicates = (
            frame.loc[
                frame[resolved_key_column].duplicated(keep=False),
                resolved_key_column,
            ]
            .astype(str)
            .unique()
            .tolist()
        )
        raise ValueError(
            f"{table_name} contains duplicate keys: {duplicates}"
        )

    return {
        str(key): "" if pd.isna(value) else str(value)
        for key, value in zip(
            frame[resolved_key_column],
            frame["value"],
            strict=False,
        )
    }


def require_keys(
    values: dict[str, str],
    required: set[str],
    *,
    context: str,
) -> None:
    """Require documentation keys before README rendering."""

    missing = sorted(
        key
        for key in required
        if key not in values or values[key] == ""
    )

    if missing:
        raise ValueError(
            f"{context} is missing required documentation keys: {missing}"
        )


def int_value(
    values: dict[str, str],
    key: str,
) -> int:
    """Read one integer-valued metadata or QA entry."""

    try:
        return int(float(values[key]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"Expected integer value for {key!r}, found {values.get(key)!r}."
        ) from exc


def build_package_filename(
    *,
    created_date: date,
    suffix: str,
    extension: str,
) -> str:
    """Build one companion filename using the CanCO2Re submission convention."""

    return (
        f"{created_date:%Y%m%d}_"
        f"{CANCO2RE_SUBMISSION.activity_code}_"
        f"{DATA_TYPE}{suffix}_"
        f"{CANCO2RE_SUBMISSION.creator_initials}"
        f".{extension}"
    )


# =============================================================================
# README rendering
# =============================================================================

def build_readme(
    gpkg_path: Path,
) -> str:
    """Render the README from persisted NATCARB metadata and QA tables."""

    gpkg_path = Path(gpkg_path)

    if not gpkg_path.is_file():
        raise FileNotFoundError(
            f"Silver GeoPackage not found: {gpkg_path}"
        )

    validate_registered_contents(gpkg_path)

    metadata = read_key_value_table(
        gpkg_path,
        table_name=METADATA_TABLE,
        key_column="key",
        key_aliases=("metadata_field",),
    )
    qa = read_key_value_table(
        gpkg_path,
        table_name=QA_TABLE,
        key_column="check",
        key_aliases=("qa_check",),
    )

    # Current NATCARB Silver contract. These are intrinsic dataset values already
    # persisted by the harmonizer; presentation-only values remain in this module.
    require_keys(
        metadata,
        {
            "Who",
            "What",
            "When",
            "Where",
            "How",
            "dataset_id",
            "source_title",
            "source_organization",
            "source_version",
            "source_publication_date",
            "source_geographic_extent",
            "silver_crs",
            "assessment_type",
            "data_class",
            "capacity_data",
            "injectivity_status",
        },
        context=METADATA_TABLE,
    )

    require_keys(
        qa,
        {
            "feature_layers",
            "domain_tables",
            "total_spatial_features",
            "duplicate_flagged_features",
            "overlap_flagged_features",
            "assessed_features",
            "unassessed_with_capacity",
            "p10_gt_p50",
            "p50_gt_p90",
            "persisted_invalid_geometries",
            "silver_crs",
        },
        context=QA_TABLE,
    )

    if metadata["dataset_id"] != DATASET_ID:
        raise ValueError(
            f"Expected dataset_id {DATASET_ID!r}, found "
            f"{metadata['dataset_id']!r}."
        )

    if metadata["silver_crs"] != qa["silver_crs"]:
        raise ValueError(
            "Metadata and QA tables disagree on the Silver CRS: "
            f"{metadata['silver_crs']} != {qa['silver_crs']}."
        )

    created_date = date.fromisoformat(
        metadata["When"]
    )

    source_schema_filename = build_package_filename(
        created_date=created_date,
        suffix="SourceSchema",
        extension="csv",
    )
    source_metadata_filename = build_package_filename(
        created_date=created_date,
        suffix="SourceMetadata",
        extension="csv",
    )
    qa_summary_filename = build_package_filename(
        created_date=created_date,
        suffix="QASummary",
        extension="csv",
    )
    field_dictionary_filename = build_package_filename(
        created_date=created_date,
        suffix="FieldDictionary",
        extension="csv",
    )

    processing = numbered_steps(
        PROCESSING_STEPS
    )
    storage_notes = markdown_list(
        STORAGE_INTERPRETATION
    )
    registered_contents = markdown_list(
        REGISTERED_CONTENT_DESCRIPTIONS
    )

    classification = "\n\n".join(
        (
            f"`assessment_type`: `{metadata['assessment_type']}`",
            f"`data_class`: `{metadata['data_class']}`",
            f"`capacity_data`: `{metadata['capacity_data']}`",
            f"`injectivity_status`: `{metadata['injectivity_status']}`",
        )
    )

    return f"""# {TITLE}

## CanCO₂Re submission metadata

**Who:** {metadata['Who']}

**What:** {metadata['What']}

**When:** {metadata['When']}

**Where:** {metadata['Where']}

**How:** {metadata['How']}

## Dataset role

{DATASET_ROLE}

{PACKAGE_PURPOSE}

## Source / Bronze data

Source title:

{metadata['source_title']}

Source organization:

{metadata['source_organization']}

Source version:

{metadata['source_version']}

Source publication date:

{metadata['source_publication_date']}

Source page:

{SOURCE_PAGE}

Version resource page:

{SOURCE_RESOURCE_PAGE}

The Bronze source consists of the original NATCARB v1502 File Geodatabase and
associated provider metadata products. The original Bronze products are retained
unchanged and are not modified by harmonization.

## Silver output

GeoPackage:

`{gpkg_path.name}`

Registered contents:

{registered_contents}

Total spatial features:

{format_int(int_value(qa, 'total_spatial_features'))}

Feature layers:

{format_int(int_value(qa, 'feature_layers'))}

Provider domain tables:

{format_int(int_value(qa, 'domain_tables'))}

CRS:

{metadata['silver_crs']} — NAD83 / Canada Atlas Lambert

This CRS follows the CanCO₂Re GIS project standard for processed and published
spatial data.

## Processing

The Silver package was produced by:

{processing}

The original Bronze products are not modified by harmonization.

## Storage representation and interpretation

{storage_notes}

## QA notes

- Total Silver spatial features: {format_int(int_value(qa, 'total_spatial_features'))}.
- Provider-flagged duplicate features retained: {format_int(int_value(qa, 'duplicate_flagged_features'))}.
- Provider-flagged overlapping features retained: {format_int(int_value(qa, 'overlap_flagged_features'))}.
- Features identified by NATCARB as assessed: {format_int(int_value(qa, 'assessed_features'))}.
- Unassessed features containing non-null capacity values: {format_int(int_value(qa, 'unassessed_with_capacity'))}.
- P10 > P50 ordering checks: {format_int(int_value(qa, 'p10_gt_p50'))}.
- P50 > P90 ordering checks: {format_int(int_value(qa, 'p50_gt_p90'))}.
- Final invalid geometries in the persisted GeoPackage: {format_int(int_value(qa, 'persisted_invalid_geometries'))}.
- Source-quality anomalies are reported rather than silently corrected.
- The source `FIELD_TYPE` value `STORAGE` is preserved where observed even
  though it is not listed in the accompanying documented oil/gas field-type domain.

## Data classification

{classification}

Keywords:

{KEYWORDS}

## Companion files

The standard Silver package is accompanied by:

- `{source_schema_filename}` — inventory of the NATCARB source FileGDB schemas used by the harmonizer.
- `{source_metadata_filename}` — human-readable export of the GeoPackage metadata table.
- `{qa_summary_filename}` — human-readable export of the GeoPackage QA table.
- `{field_dictionary_filename}` — combined field dictionary for the harmonized NATCARB Silver fields.

Detailed layer-inventory and capacity-QA diagnostics may also be generated under
the `inspection/` subdirectory. They are reproducible development/QA artifacts
rather than required Silver package sidecars.

## Use limitations

{USE_LIMITATIONS}
"""


def default_readme_path(
    gpkg_path: Path,
) -> Path:
    """Build the README path from persisted CanCO2Re submission metadata."""

    metadata = read_key_value_table(
        gpkg_path,
        table_name=METADATA_TABLE,
        key_column="key",
        key_aliases=("metadata_field",),
    )

    require_keys(
        metadata,
        {
            "When",
        },
        context=METADATA_TABLE,
    )

    created_date = date.fromisoformat(
        metadata["When"]
    )

    return gpkg_path.parent / build_package_filename(
        created_date=created_date,
        suffix="README",
        extension="md",
    )


def generate_readme(
    gpkg_path: Path,
    *,
    output_path: Path | None = None,
) -> Path:
    """Generate and write the README for one NATCARB Silver GeoPackage."""

    gpkg_path = Path(gpkg_path)

    readme_text = build_readme(
        gpkg_path
    )

    destination = (
        Path(output_path)
        if output_path is not None
        else default_readme_path(gpkg_path)
    )

    return write_readme(
        destination,
        readme_text,
    )


# =============================================================================
# CLI
# =============================================================================

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Generate the NATCARB v1502 README from metadata and QA stored "
            "inside the persisted Silver GeoPackage."
        )
    )

    parser.add_argument(
        "--gpkg",
        type=Path,
        default=None,
        help=(
            "Path to the NATCARB Silver GeoPackage. If omitted, the most recent "
            "matching GeoPackage in data/processed/natcarb_doe is used."
        ),
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Optional README output path. By default the CanCO2Re-compliant "
            "README filename is written beside the GeoPackage."
        ),
    )

    return parser.parse_args()


def main() -> None:
    """Generate the NATCARB v1502 README."""

    args = parse_args()

    gpkg_path = (
        args.gpkg
        if args.gpkg is not None
        else discover_silver_gpkg()
    )

    readme_path = generate_readme(
        gpkg_path,
        output_path=args.output,
    )

    print("NATCARB v1502 metadata")
    print("----------------------")
    print(f"GeoPackage: {gpkg_path}")
    print(f"README:     {readme_path}")


if __name__ == "__main__":
    main()
