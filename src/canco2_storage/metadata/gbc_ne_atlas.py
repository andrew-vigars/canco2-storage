"""Generate the Northeast BC Storage Atlas README from the persisted Silver GeoPackage.

The GeoPackage is the authoritative documentation source for dataset-level
metadata and QA. This module reads the registered ``metadata_gbc_ne_atlas`` and
``qa_gbc_ne_atlas`` attribute tables, validates the expected CANCO2Re package
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

DATA_TYPE = "BCStorageAtlas"
DATASET_ID = "gbc_ne_atlas"

METADATA_TABLE = "metadata_gbc_ne_atlas"
QA_TABLE = "qa_gbc_ne_atlas"

EXPECTED_GPKG_CONTENTS = {
    "pool_features": "features",
    "aquifer_features": "features",
    "pool_units": "attributes",
    "aquifer_units": "attributes",
    METADATA_TABLE: "attributes",
    QA_TABLE: "attributes",
}

PROJECT_ROOT = find_project_root()

PROCESSED_GBC_NE_ATLAS = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / DATASET_ID
)


# =============================================================================
# Documentation text that is structural rather than dataset-instance metadata
# =============================================================================

DATASET_ROLE = (
    "Silver-layer harmonization of the Northeast BC Geological Carbon Capture "
    "and Storage Atlas published as Geoscience BC Report 2023-04. The Silver "
    "artifact represents selected depleted or near-depleted pools and saline "
    "aquifers as logical storage units linked to their published spatial "
    "representation."
)

PROCESSING_STEPS = (
    "Inventorying the Appendix E shapefiles and Appendix C workbook structure.",
    "Classifying published Appendix E layers by their role in the source atlas.",
    "Using Appendix C as the logical pool selection and classification source.",
    "Linking selected Appendix C pool records to the canonical Appendix E master "
    "pool geometry through the published link code.",
    "Using Appendix C as the preferred logical and tabular aquifer source and "
    "linking the 25 published aquifer shapefiles through the reconciled source-name mapping.",
    "Preserving multiple spatial features where one logical storage unit is "
    "represented by more than one source geometry.",
    "Preserving source-native storage values and explicit source-quality flags "
    "rather than silently replacing discrepant source values.",
    "Repairing invalid geometries when required and reprojecting Silver spatial "
    "layers to EPSG:3978.",
    "Writing spatial layers, logical-unit tables, dataset metadata, and QA into "
    "one GeoPackage and reopening the persisted artifact for validation.",
    "Exporting standardized source-schema, source-metadata, QA-summary, and "
    "combined field-dictionary sidecars.",
)

STORAGE_INTERPRETATION = (
    "Pool and aquifer capacities are attached to logical storage units. Repeated "
    "or multi-part spatial features must not be treated as additive capacity.",
    "Pool logical attributes and classifications are taken from Appendix C; "
    "the master pool shapefile supplies the canonical spatial representation.",
    "Aquifer logical attributes and standardized effective-storage estimates are "
    "taken from Appendix C; source shapefile values are retained separately for provenance and QA.",
    "Aquifer theoretical storage in the standardized logical table is derived "
    "from the Appendix C P50 effective-storage value divided by 0.02.",
    "Source storage estimates are regional screening values and do not represent "
    "demonstrated injectivity, permitted injection capacity, or project-ready capacity.",
)


# =============================================================================
# GeoPackage readers and validation
# =============================================================================

def discover_silver_gpkg(
    processed_dir: Path = PROCESSED_GBC_NE_ATLAS,
) -> Path:
    """Return the most recent BC Storage Atlas Silver GeoPackage by filename."""

    candidates = sorted(
        processed_dir.glob(
            f"*_{CANCO2RE_SUBMISSION.activity_code}_"
            f"{DATA_TYPE}_{CANCO2RE_SUBMISSION.creator_initials}.gpkg"
        )
    )

    if not candidates:
        raise FileNotFoundError(
            "No Northeast BC Storage Atlas Silver GeoPackage found under "
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
    """Require the CANCO2Re BC Storage Atlas GeoPackage table contract."""

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
            "GeoPackage contents do not satisfy the expected BC Storage Atlas "
            f"contract: {missing_or_wrong}"
        )

    return contents


def read_key_value_table(
    gpkg_path: Path,
    *,
    table_name: str,
    key_column: str,
) -> dict[str, str]:
    """Read one registered key/value attribute table as a dictionary."""

    with sqlite3.connect(gpkg_path) as conn:
        frame = pd.read_sql_query(
            f'SELECT * FROM "{table_name}"',
            conn,
        )

    required = {key_column, "value"}
    missing = required - set(frame.columns)

    if missing:
        raise ValueError(
            f"{table_name} is missing required columns: {sorted(missing)}"
        )

    if frame[key_column].isna().any():
        raise ValueError(
            f"{table_name}.{key_column} contains null keys."
        )

    if frame[key_column].duplicated().any():
        duplicates = (
            frame.loc[
                frame[key_column].duplicated(keep=False),
                key_column,
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
            frame[key_column],
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
    """Build one companion filename using the CANCO2Re submission convention."""

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
    """Render the README from metadata and QA stored in the Silver GeoPackage."""

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
    )
    qa = read_key_value_table(
        gpkg_path,
        table_name=QA_TABLE,
        key_column="check",
    )

    require_keys(
        metadata,
        {
            "title",
            "who",
            "when",
            "submission_filename",
            "activity_code",
            "creator_initials",
            "dataset_id",
            "data_class",
            "assessment_type",
            "capacity_data",
            "injectivity_status",
            "source_title",
            "source_organization",
            "source_preparer",
            "source_publication",
            "source_year",
            "source_url",
            "source_parent_url",
            "what",
            "where",
            "how",
            "use_limitations",
            "keywords",
            "silver_crs",
            "bronze_shapefile_count",
            "pool_logical_unit_count",
            "aquifer_logical_unit_count",
        },
        context=METADATA_TABLE,
    )

    require_keys(
        qa,
        {
            "pool_logical_unit_count",
            "pool_spatial_feature_count",
            "pool_multi_feature_unit_count",
            "pool_unmatched_link_code_count",
            "pool_invalid_native_before_repair",
            "pool_invalid_native_after_repair",
            "pool_invalid_projected_after_repair",
            "aquifer_logical_unit_count",
            "aquifer_spatial_feature_count",
            "aquifer_multi_feature_unit_count",
            "aquifer_zero_theoretical_anomaly_count",
            "aquifer_source_storage_mismatch_count",
            "aquifer_invalid_native_before_repair",
            "aquifer_invalid_native_after_repair",
            "aquifer_invalid_projected_after_repair",
            "aquifer_read_warning_count",
            "silver_crs",
            "pool_null_geometry_count",
            "aquifer_null_geometry_count",
            "pool_final_invalid_geometry_count",
            "aquifer_final_invalid_geometry_count",
        },
        context=QA_TABLE,
    )

    if metadata["dataset_id"] != DATASET_ID:
        raise ValueError(
            f"Expected dataset_id {DATASET_ID!r}, found "
            f"{metadata['dataset_id']!r}."
        )

    if metadata["activity_code"] != CANCO2RE_SUBMISSION.activity_code:
        raise ValueError(
            "GeoPackage activity code does not match the configured "
            "CANCO2Re submission metadata."
        )

    if metadata["creator_initials"] != CANCO2RE_SUBMISSION.creator_initials:
        raise ValueError(
            "GeoPackage creator initials do not match the configured "
            "CANCO2Re submission metadata."
        )

    if metadata["silver_crs"] != qa["silver_crs"]:
        raise ValueError(
            "Metadata and QA tables disagree on the Silver CRS: "
            f"{metadata['silver_crs']} != {qa['silver_crs']}."
        )

    if (
        int_value(metadata, "pool_logical_unit_count")
        != int_value(qa, "pool_logical_unit_count")
    ):
        raise ValueError(
            "Metadata and QA tables disagree on pool logical-unit count."
        )

    if (
        int_value(metadata, "aquifer_logical_unit_count")
        != int_value(qa, "aquifer_logical_unit_count")
    ):
        raise ValueError(
            "Metadata and QA tables disagree on aquifer logical-unit count."
        )

    created_date = date.fromisoformat(
        metadata["when"]
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

    pool_logical = int_value(
        qa,
        "pool_logical_unit_count",
    )
    pool_features = int_value(
        qa,
        "pool_spatial_feature_count",
    )
    aquifer_logical = int_value(
        qa,
        "aquifer_logical_unit_count",
    )
    aquifer_features = int_value(
        qa,
        "aquifer_spatial_feature_count",
    )

    final_invalid = (
        int_value(
            qa,
            "pool_final_invalid_geometry_count",
        )
        + int_value(
            qa,
            "aquifer_final_invalid_geometry_count",
        )
    )

    classification = "\n\n".join(
        (
            f"`assessment_type`: `{metadata['assessment_type']}`",
            f"`data_class`: `{metadata['data_class']}`",
            f"`capacity_data`: `{metadata['capacity_data']}`",
            f"`injectivity_status`: `{metadata['injectivity_status']}`",
        )
    )

    return f"""# {metadata['title']}

## CanCO₂Re submission metadata

**Who:** {metadata['who']}

**What:** {metadata['what']}

**When:** {metadata['when']}

**Where:** {metadata['where']}

**How:** {metadata['how']}

## Dataset role

{DATASET_ROLE}

This package is intended for regional-scale geological storage screening and
comparative analysis of published storage resources.

## Source / Bronze data

Source title:

{metadata['source_title']}

Source organization:

{metadata['source_organization']}

Prepared by:

{metadata['source_preparer']}

Publication:

{metadata['source_publication']} ({metadata['source_year']})

Project page:

{metadata['source_url']}

Parent information page:

{metadata['source_parent_url']}

The Bronze spatial archive contains {format_int(int_value(metadata, 'bronze_shapefile_count'))} shapefiles. Appendix C and Appendix E are retained as complementary Bronze source products: Appendix C provides the principal logical/tabular storage records used by the Silver workflow, while Appendix E supplies the published spatial representation and supporting map layers.

## Silver output

GeoPackage:

`{metadata['submission_filename']}`

Registered contents:

- `pool_features` — spatial features representing selected logical pool units.
- `aquifer_features` — spatial features representing logical saline-aquifer units.
- `pool_units` — one logical record per selected pool.
- `aquifer_units` — one logical record per saline aquifer.
- `{METADATA_TABLE}` — dataset-level provenance, interpretation, and submission metadata.
- `{QA_TABLE}` — dataset-level quality-assurance summary.

Pool logical units:

{format_int(pool_logical)}

Pool spatial features:

{format_int(pool_features)}

Aquifer logical units:

{format_int(aquifer_logical)}

Aquifer spatial features:

{format_int(aquifer_features)}

CRS:

{metadata['silver_crs']} — NAD83 / Canada Atlas Lambert

This CRS follows the CanCO₂Re GIS project standard for processed and published spatial data.

## Processing

The Silver package was produced by:

{processing}

The original Bronze products are not modified by harmonization.

## Storage representation and interpretation

{storage_notes}

## QA notes

- Pool logical units represented: {format_int(pool_logical)}.
- Pool spatial features preserved: {format_int(pool_features)}.
- Pools represented by more than one spatial feature: {format_int(int_value(qa, 'pool_multi_feature_unit_count'))}.
- Pool link codes unmatched to the canonical master geometry: {format_int(int_value(qa, 'pool_unmatched_link_code_count'))}.
- Aquifer logical units represented: {format_int(aquifer_logical)}.
- Aquifer spatial features preserved: {format_int(aquifer_features)}.
- Aquifers represented by more than one spatial feature: {format_int(int_value(qa, 'aquifer_multi_feature_unit_count'))}.
- Aquifers with the known zero-theoretical / nonzero-effective source anomaly: {format_int(int_value(qa, 'aquifer_zero_theoretical_anomaly_count'))}.
- Aquifers whose source-shapefile P10/P50/P90 values do not match Appendix C within the harmonization tolerance: {format_int(int_value(qa, 'aquifer_source_storage_mismatch_count'))}.
- Invalid aquifer source geometries detected before native-CRS repair: {format_int(int_value(qa, 'aquifer_invalid_native_before_repair'))}.
- Invalid aquifer geometries remaining after native-CRS repair: {format_int(int_value(qa, 'aquifer_invalid_native_after_repair'))}.
- Source-read warnings captured for aquifer layers: {format_int(int_value(qa, 'aquifer_read_warning_count'))}.
- Final invalid geometries in the persisted GeoPackage: {format_int(final_invalid)}.

Known source anomalies and cross-product differences are retained as explicit QA information rather than silently overwritten.

## Data classification

{classification}

Keywords:

{metadata['keywords']}

## Companion files

The standard Silver package is accompanied by:

- `{source_schema_filename}` — inventory of the published Appendix E source schemas.
- `{source_metadata_filename}` — human-readable export of the GeoPackage metadata table.
- `{qa_summary_filename}` — human-readable export of the GeoPackage QA table.
- `{field_dictionary_filename}` — combined field dictionary for `pool_units`, `pool_features`, `aquifer_units`, and `aquifer_features`.

Workbook-schema and pool-reconciliation diagnostics may also be generated under the `inspection/` subdirectory with `--inspect-only`; they are reproducible development/QA artifacts rather than required Silver package sidecars.

## Use limitations

{metadata['use_limitations']}
"""


def default_readme_path(
    gpkg_path: Path,
) -> Path:
    """Build the README path from persisted CANCO2Re submission metadata."""

    metadata = read_key_value_table(
        gpkg_path,
        table_name=METADATA_TABLE,
        key_column="key",
    )

    require_keys(
        metadata,
        {
            "when",
            "activity_code",
            "creator_initials",
        },
        context=METADATA_TABLE,
    )

    created_date = date.fromisoformat(
        metadata["when"]
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
    """Generate and write the README for one BC Storage Atlas GeoPackage."""

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
            "Generate the Northeast BC Storage Atlas README from metadata and "
            "QA stored inside the persisted Silver GeoPackage."
        )
    )

    parser.add_argument(
        "--gpkg",
        type=Path,
        default=None,
        help=(
            "Path to the BC Storage Atlas Silver GeoPackage. If omitted, the "
            "most recent matching GeoPackage in data/processed/gbc_ne_atlas is used."
        ),
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Optional README output path. By default the CANCO2Re-compliant "
            "README filename is written beside the GeoPackage."
        ),
    )

    return parser.parse_args()


def main() -> None:
    """Generate the Northeast BC Storage Atlas README."""

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

    print("Northeast BC Storage Atlas metadata")
    print("-----------------------------------")
    print(f"GeoPackage: {gpkg_path}")
    print(f"README:     {readme_path}")


if __name__ == "__main__":
    main()
