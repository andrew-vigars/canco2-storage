"""Generate the GSC Atlantic README from the persisted Silver GeoPackage.

The GeoPackage is the authoritative documentation source for dataset-level
metadata and QA. This module reads the registered ``metadata_gsc_atlantic`` and
``qa_gsc_atlantic`` attribute tables, validates the expected package contract,
and renders the human-readable README without modifying the GeoPackage.
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


TITLE = "Atlantic Canada CO₂ Storage Chance of Success"

DATA_TYPE = "AtlanticStorageCOS"
DATASET_ID = "gsc_atlantic"

SOURCE_CITATION = (
    "Carey et al. (2023), *Preliminary assessment of geological carbon-storage "
    "potential of Atlantic Canada*, Geological Survey of Canada Open File 8996."
)
SOURCE_DOI = "10.4095/332145"

METADATA_TABLE = "metadata_gsc_atlantic"
QA_TABLE = "qa_gsc_atlantic"

EXPECTED_GPKG_CONTENTS = {
    "storage_units": "features",
    METADATA_TABLE: "attributes",
    QA_TABLE: "attributes",
}

PROJECT_ROOT = find_project_root()
PROCESSED_GSC_ATLANTIC = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / DATASET_ID
)

DATASET_ROLE = (
    "Silver-layer harmonization of Geological Survey of Canada Open File 8996 "
    "regional geological CO₂ storage Chance of Success (COS) mapping."
)

INTERPRETATION = (
    "This dataset represents geological prospectivity and does not represent "
    "quantified CO₂ storage capacity, injectivity, permitted storage resource, "
    "or project-ready storage capacity."
)

PROCESSING_STEPS = (
    "Reading all 15 source shapefiles.",
    "Preserving each source feature as an individual feature.",
    "Validating each source layer against an explicit source-field mapping.",
    "Harmonizing heterogeneous source attribute names into a common COS schema.",
    "Preserving source dataset and feature provenance.",
    "Repairing invalid source geometries when required in the native source CRS.",
    "Reprojecting harmonized geometries to the repository Silver CRS.",
    "Repairing and validating geometries again after reprojection.",
    "Appending the harmonized datasets row-wise into one feature layer.",
    "Writing and reopening the Silver GeoPackage for persisted-artifact validation.",
    "Registering dataset-level metadata and QA as GeoPackage attribute tables.",
    "Exporting reproducible source-schema, metadata, QA, and field-dictionary sidecars.",
)

COS_INTERPRETATION = (
    "`reservoir_cos` represents the source reservoir Chance of Success.",
    "`seal_cos` represents the source seal Chance of Success.",
    "`trap_cos` is populated only where an explicit source trap COS field exists.",
    "`total_cos` preserves the combined COS value published by the source dataset.",
    "A null `trap_cos` means that no explicit trap COS attribute was supplied by "
    "that source dataset; it must not be interpreted as a trap COS of zero.",
    "COS should be interpreted as geological prospectivity / chance of success, "
    "not storage capacity.",
)

REGISTERED_CONTENT_DESCRIPTIONS = (
    "`storage_units` — harmonized Atlantic geological prospectivity polygons.",
    f"`{METADATA_TABLE}` — authoritative dataset-level provenance, classification, "
    "interpretation, and submission metadata.",
    f"`{QA_TABLE}` — authoritative dataset-level quality-assurance summary.",
)


def discover_silver_gpkg(
    processed_dir: Path = PROCESSED_GSC_ATLANTIC,
) -> Path:
    """Return the most recent Atlantic Silver GeoPackage by filename."""

    candidates = sorted(
        processed_dir.glob(
            f"*_{CANCO2RE_SUBMISSION.activity_code}_"
            f"{DATA_TYPE}_{CANCO2RE_SUBMISSION.creator_initials}.gpkg"
        )
    )

    if not candidates:
        raise FileNotFoundError(
            f"No GSC Atlantic Silver GeoPackage found under {processed_dir}."
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
    """Require the expected Atlantic GeoPackage table contract."""

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
            "GeoPackage contents do not satisfy the expected GSC Atlantic "
            f"package contract: {missing_or_wrong}"
        )

    return contents


def read_key_value_table(
    gpkg_path: Path,
    *,
    table_name: str,
    key_column: str,
) -> dict[str, str]:
    """Read one registered key/value attribute table."""

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
    """Build one companion filename using the submission convention."""

    return (
        f"{created_date:%Y%m%d}_"
        f"{CANCO2RE_SUBMISSION.activity_code}_"
        f"{DATA_TYPE}{suffix}_"
        f"{CANCO2RE_SUBMISSION.creator_initials}."
        f"{extension}"
    )


def build_readme(
    gpkg_path: Path,
) -> str:
    """Render the README from persisted Atlantic metadata and QA tables."""

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
            "Who",
            "What",
            "When",
            "Where",
            "How",
            "dataset_id",
            "source_organization",
            "source_title",
            "source_publication",
            "source_year",
            "source_doi",
            "source_url",
            "licence_name",
            "licence_url",
            "assessment_type",
            "data_class",
            "capacity_data",
            "capacity_status",
            "injectivity_status",
            "silver_crs",
        },
        context=METADATA_TABLE,
    )

    require_keys(
        qa,
        {
            "feature_layers",
            "total_spatial_features",
            "storage_units",
            "source_layers",
            "source_read_warnings",
            "reservoir_cos_null",
            "seal_cos_null",
            "trap_cos_null",
            "total_cos_null",
            "persisted_invalid_geometries",
            "persisted_null_geometries",
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

    created_date = date.fromisoformat(metadata["When"])

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

    processing = numbered_steps(PROCESSING_STEPS)
    cos_notes = markdown_list(COS_INTERPRETATION)
    registered_contents = markdown_list(REGISTERED_CONTENT_DESCRIPTIONS)

    classification = "\n\n".join(
        (
            f"`assessment_type`: `{metadata['assessment_type']}`",
            f"`data_class`: `{metadata['data_class']}`",
            f"`capacity_data`: `{metadata['capacity_data']}`",
            f"`capacity_status`: `{metadata['capacity_status']}`",
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

{INTERPRETATION}

## Source / Bronze data

Source publication:

{SOURCE_CITATION}

DOI:

{SOURCE_DOI}

Source organization:

{metadata['source_organization']}

Source URL:

{metadata['source_url']}

Licence:

{metadata['licence_name']}

The Bronze source consists of 15 shapefile datasets: 10 Mesozoic–Cenozoic COS
layers and 5 Upper Paleozoic COS layers. The original shapefiles are retained
unchanged as Bronze source data.

## Silver output

GeoPackage:

`{gpkg_path.name}`

Registered contents:

{registered_contents}

Total spatial features:

{format_int(int_value(qa, 'total_spatial_features'))}

Storage units:

{format_int(int_value(qa, 'storage_units'))}

Source layers:

{format_int(int_value(qa, 'source_layers'))}

CRS:

{metadata['silver_crs']} — NAD83 / Canada Atlas Lambert

## Processing

The Silver package was produced by:

{processing}

No source polygons are intentionally dissolved, spatially unioned, or aggregated
during source harmonization.

## COS interpretation

{cos_notes}

## QA notes

- Source features preserved in Silver: {format_int(int_value(qa, 'total_spatial_features'))}.
- Source storage units represented: {format_int(int_value(qa, 'storage_units'))}.
- Source read warnings captured: {format_int(int_value(qa, 'source_read_warnings'))}.
- Null `reservoir_cos` values: {format_int(int_value(qa, 'reservoir_cos_null'))}.
- Null `seal_cos` values: {format_int(int_value(qa, 'seal_cos_null'))}.
- Null `trap_cos` values: {format_int(int_value(qa, 'trap_cos_null'))}.
- Null `total_cos` values: {format_int(int_value(qa, 'total_cos_null'))}.
- Final invalid geometries: {format_int(int_value(qa, 'persisted_invalid_geometries'))}.
- Final null geometries: {format_int(int_value(qa, 'persisted_null_geometries'))}.
- Source-reported `total_cos` values are preserved rather than recomputed.
- Similar mapped areas may represent overlapping or vertically stacked geological
  plays and should not be summed to infer unique storage area or storage capacity.

## Data classification

{classification}

## Companion files

- `{source_schema_filename}` — inventory of source shapefile schemas.
- `{source_metadata_filename}` — export of authoritative GeoPackage metadata.
- `{qa_summary_filename}` — detailed per-source harmonization and geometry QA.
- `{field_dictionary_filename}` — field dictionary for the harmonized Silver layer.

## Use limitations

This dataset should be used as a geological screening or prospectivity layer.
Quantified storage-capacity assessment should be represented separately using
datasets containing explicit volumetric or mass-based storage-resource estimates.
"""


def default_readme_path(
    gpkg_path: Path,
) -> Path:
    """Build the README path from persisted submission metadata."""

    metadata = read_key_value_table(
        gpkg_path,
        table_name=METADATA_TABLE,
        key_column="key",
    )

    require_keys(
        metadata,
        {"When"},
        context=METADATA_TABLE,
    )

    created_date = date.fromisoformat(metadata["When"])

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
    """Generate and write the README for one Atlantic Silver GeoPackage."""

    gpkg_path = Path(gpkg_path)
    readme_text = build_readme(gpkg_path)

    destination = (
        Path(output_path)
        if output_path is not None
        else default_readme_path(gpkg_path)
    )

    return write_readme(
        destination,
        readme_text,
    )


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Generate the GSC Atlantic README from metadata and QA stored "
            "inside the persisted Silver GeoPackage."
        )
    )

    parser.add_argument(
        "--gpkg",
        type=Path,
        default=None,
        help=(
            "Path to the Atlantic Silver GeoPackage. If omitted, the most recent "
            "matching GeoPackage in data/processed/gsc_atlantic is used."
        ),
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional README output path.",
    )

    return parser.parse_args()


def main() -> None:
    """Generate the GSC Atlantic README."""

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

    print("GSC Atlantic metadata")
    print("---------------------")
    print(f"GeoPackage: {gpkg_path}")
    print(f"README:     {readme_path}")


if __name__ == "__main__":
    main()
