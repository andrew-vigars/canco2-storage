"""Generate the unified Canadian geological storage README.

The unified GeoPackage is the authoritative documentation source. This module
reads its persisted metadata, QA, and source-catalog tables and does not modify
the GeoPackage.
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd

from canco2_storage.metadata.common import (
    format_int,
    markdown_list,
    numbered_steps,
    write_readme,
)
from canco2_storage.paths import find_project_root


DATASET_ID = "canada_geological_storage_unified"
DATA_TYPE = "CanadaGeologicalStorageUnified"
BUILD_VARIANT = "v2"

METADATA_TABLE = f"metadata_{DATASET_ID}"
QA_TABLE = f"qa_{DATASET_ID}"
SOURCE_CATALOG_TABLE = f"source_catalog_{DATASET_ID}"
SOURCE_METADATA_TABLE = f"source_metadata_{DATASET_ID}"
SOURCE_QA_TABLE = f"source_qa_{DATASET_ID}"
COMPANION_SUFFIXES = {
    "source_schema": "SourceSchema_AV.csv",
    "source_metadata": "SourceMetadata_AV.csv",
    "qa_summary": "QASummary_AV.csv",
    "field_dictionary": "FieldDictionary_AV.csv",
}

PROJECT_ROOT = find_project_root()
PROCESSED_UNIFIED = PROJECT_ROOT / "data" / "processed" / "unified_storage"

EXPECTED_GPKG_CONTENTS = {
    "storage_units": "attributes",
    "storage_features": "features",
    "storage_assessments": "attributes",
    "administrative_features": "features",
    SOURCE_CATALOG_TABLE: "attributes",
    SOURCE_METADATA_TABLE: "attributes",
    SOURCE_QA_TABLE: "attributes",
    METADATA_TABLE: "attributes",
    QA_TABLE: "attributes",
}

PROCESSING_STEPS = (
    "Reading the four precursor Silver GeoPackages and their persisted metadata and QA tables.",
    "Mapping precursor records into canonical storage-unit, spatial-feature, and assessment schemas.",
    "Preserving source dataset, source layer, and source-derived identifier provenance.",
    "Separating logical storage units from their spatial representations and assessments.",
    "Retaining regulatory tenure polygons as administrative features separate from geological storage objects.",
    "Subsetting NATCARB saline and coal grid cells to Canadian provinces and territories.",
    "Writing canonical spatial and attribute tables to one unified GeoPackage in EPSG:3978.",
    "Persisting normalized source lineage, dataset metadata, and unified QA tables.",
    "Reopening the persisted GeoPackage and validating identifiers, relationships, geometry, and field types.",
)


def discover_unified_gpkg(
    processed_dir: Path = PROCESSED_UNIFIED,
) -> Path:
    """Return the most recent v2 unified GeoPackage by filename."""

    candidates = sorted(
        processed_dir.glob(f"*_13_{DATA_TYPE}_AV_{BUILD_VARIANT}.gpkg")
    )
    if not candidates:
        raise FileNotFoundError(
            f"No unified GeoPackage found under {processed_dir}."
        )
    return candidates[-1]


def read_registered_contents(gpkg_path: Path) -> pd.DataFrame:
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


def companion_paths(gpkg_path: Path) -> dict[str, Path]:
    """Return the four documented CSV companion paths for a GeoPackage."""

    gpkg_path = Path(gpkg_path)
    return {
        role: gpkg_path.with_name(gpkg_path.stem + suffix)
        for role, suffix in COMPANION_SUFFIXES.items()
    }


def _read_table(gpkg_path: Path, table_name: str) -> pd.DataFrame:
    """Read one SQLite table from the unified GeoPackage."""

    with sqlite3.connect(gpkg_path) as conn:
        return pd.read_sql_query(f'SELECT * FROM "{table_name}"', conn)


def build_companion_tables(gpkg_path: Path) -> dict[str, pd.DataFrame]:
    """Build the documented CSV companion tables from a unified GeoPackage."""

    gpkg_path = Path(gpkg_path)
    contents = read_registered_contents(gpkg_path)
    registered = contents.set_index("table_name").to_dict("index")

    with sqlite3.connect(gpkg_path) as conn:
        table_names = [
            row[0]
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name NOT LIKE 'gpkg_%'
                  AND name NOT LIKE 'rtree_%'
                  AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            )
        ]

        schema_rows: list[dict[str, object]] = []
        field_rows: list[dict[str, object]] = []
        for table_name in table_names:
            columns = conn.execute(
                f'PRAGMA table_info("{table_name}")'
            ).fetchall()
            table_info = registered.get(table_name, {})
            schema_rows.append(
                {
                    "table_name": table_name,
                    "data_type": table_info.get("data_type", "attributes"),
                    "identifier": table_info.get("identifier", table_name),
                    "description": table_info.get("description", ""),
                    "column_count": len(columns),
                    "columns": ", ".join(column[1] for column in columns),
                }
            )
            for _, field, data_type, not_null, _, primary_key in columns:
                if field == "fid":
                    continue
                field_rows.append(
                    {
                        "table_name": table_name,
                        "field": field,
                        "data_type": data_type or "",
                        "nullable": not not_null,
                        "primary_key": bool(primary_key),
                        "definition": _field_definition(field),
                        "units": _field_units(field),
                        "origin": _field_origin(field),
                        "notes": _field_notes(field),
                    }
                )

    source_metadata = _read_table(gpkg_path, SOURCE_METADATA_TABLE)
    unified_metadata = _read_table(gpkg_path, METADATA_TABLE).assign(
        source_key="unified",
        dataset_id=DATASET_ID,
        source_table=METADATA_TABLE,
    )
    source_metadata = pd.concat(
        [source_metadata, unified_metadata[source_metadata.columns]],
        ignore_index=True,
    )

    source_qa = _read_table(gpkg_path, SOURCE_QA_TABLE)
    unified_qa = _read_table(gpkg_path, QA_TABLE).assign(
        source_key="unified",
        dataset_id=DATASET_ID,
        source_table=QA_TABLE,
    )
    source_qa = pd.concat(
        [source_qa, unified_qa[source_qa.columns]],
        ignore_index=True,
    )

    return {
        "source_schema": pd.DataFrame(schema_rows),
        "source_metadata": source_metadata.sort_values(
            ["source_key", "dataset_id", "key"]
        ).reset_index(drop=True),
        "qa_summary": source_qa.sort_values(
            ["source_key", "dataset_id", "check"]
        ).reset_index(drop=True),
        "field_dictionary": pd.DataFrame(field_rows),
    }


def _field_definition(field: str) -> str:
    definitions = {
        "storage_unit_id": "Stable identifier for one logical storage unit.",
        "storage_feature_id": "Stable identifier for one spatial representation.",
        "storage_assessment_id": "Stable identifier for one assessment record.",
        "source_dataset": "Identifier for the contributing source dataset.",
        "source_layer": "Source layer or representation name.",
        "source_unit_id": "Source identifier for the logical storage unit.",
        "source_feature_id": "Source identifier for the spatial feature.",
        "assessment_type": "Type of assessment represented by the record.",
        "data_class": "Semantic role of the record in the unified product.",
        "capacity_data": "Whether quantitative source capacity data are present.",
        "injectivity_status": "Source-dependent injectivity information status.",
        "geometry_area_m2": "Area of the persisted geometry.",
        "geometry_area_ha": "Area of the persisted geometry.",
        "geometry_perimeter_m": "Perimeter of the persisted geometry.",
        "geom": "Persisted GeoPackage geometry.",
    }
    return definitions.get(field, "Persisted field in the unified canonical schema.")


def _field_units(field: str) -> str:
    units = {
        "geometry_area_m2": "m2",
        "geometry_area_ha": "ha",
        "geometry_perimeter_m": "m",
        "storage_p10_tonnes": "tonnes",
        "storage_p50_tonnes": "tonnes",
        "storage_p90_tonnes": "tonnes",
        "theoretical_storage_tonnes": "tonnes",
        "effective_storage_tonnes": "tonnes",
        "depth_m": "m",
        "thickness_m": "m",
        "pressure_mpa": "MPa",
        "temperature_c": "degC",
        "porosity_fraction": "fraction",
        "permeability_md": "mD",
        "salinity_tds_ppm": "ppm",
        "reservoir_cos": "fraction",
        "seal_cos": "fraction",
        "trap_cos": "fraction",
        "total_cos": "fraction",
    }
    return units.get(field, "")


def _field_origin(field: str) -> str:
    if field.startswith("source_") or field in {"storage_unit_id", "storage_feature_id", "storage_assessment_id"}:
        return "provenance"
    if field in {"assessment_type", "data_class", "capacity_data", "injectivity_status"}:
        return "harmonized"
    return "source-dependent"


def _field_notes(field: str) -> str:
    if field in {"storage_p10_tonnes", "storage_p50_tonnes", "storage_p90_tonnes"}:
        return "Null means the source did not provide that estimate; null is not zero."
    if field in {"reservoir_cos", "seal_cos", "trap_cos", "total_cos"}:
        return "Chance-of-success measure where supplied; not storage capacity."
    if field == "capacity_data":
        return "False does not permit capacity to be inferred."
    return ""


def export_companion_files(gpkg_path: Path) -> dict[str, Path]:
    """Write the four documented CSV companions beside a unified GeoPackage."""

    tables = build_companion_tables(gpkg_path)
    paths = companion_paths(gpkg_path)
    for role, frame in tables.items():
        frame.to_csv(paths[role], index=False)
    return paths


def validate_registered_contents(gpkg_path: Path) -> pd.DataFrame:
    """Require the unified GeoPackage table contract."""

    contents = read_registered_contents(gpkg_path)
    actual = dict(
        zip(contents["table_name"], contents["data_type"], strict=False)
    )
    missing_or_wrong = {
        table_name: data_type
        for table_name, data_type in EXPECTED_GPKG_CONTENTS.items()
        if actual.get(table_name) != data_type
    }
    if missing_or_wrong:
        raise ValueError(
            "GeoPackage contents do not satisfy the unified package contract: "
            f"{missing_or_wrong}"
        )
    return contents


def read_key_value_table(
    gpkg_path: Path,
    *,
    table_name: str,
    key_column: str,
) -> dict[str, str]:
    """Read and validate a persisted two-column key/value table."""

    with sqlite3.connect(gpkg_path) as conn:
        frame = pd.read_sql_query(f'SELECT * FROM "{table_name}"', conn)

    required = {key_column, "value"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{table_name} is missing required columns: {sorted(missing)}")
    if frame[key_column].isna().any() or frame[key_column].duplicated().any():
        raise ValueError(f"{table_name} contains null or duplicate keys.")
    return {
        str(key): "" if pd.isna(value) else str(value)
        for key, value in zip(frame[key_column], frame["value"], strict=True)
    }


def read_source_catalog(gpkg_path: Path) -> pd.DataFrame:
    """Read the normalized precursor source catalog."""

    with sqlite3.connect(gpkg_path) as conn:
        catalog = pd.read_sql_query(
            f'SELECT * FROM "{SOURCE_CATALOG_TABLE}" ORDER BY dataset_id',
            conn,
        )
    required = {"source_key", "dataset_id", "source_title", "source_organization"}
    missing = required - set(catalog.columns)
    if missing:
        raise ValueError(
            f"{SOURCE_CATALOG_TABLE} is missing required columns: {sorted(missing)}"
        )
    if catalog.empty:
        raise ValueError(f"{SOURCE_CATALOG_TABLE} is empty.")
    return catalog


def require_keys(values: dict[str, str], required: set[str], *, context: str) -> None:
    """Require documentation keys before rendering the README."""

    missing = sorted(key for key in required if not values.get(key, ""))
    if missing:
        raise ValueError(f"{context} is missing required documentation keys: {missing}")


def int_value(values: dict[str, str], key: str) -> int:
    """Read one integer-valued QA entry."""

    try:
        return int(float(values[key]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"Expected integer value for {key!r}, found {values.get(key)!r}."
        ) from exc


def build_readme(gpkg_path: Path) -> str:
    """Render a README from the persisted unified GeoPackage."""

    gpkg_path = Path(gpkg_path)
    if not gpkg_path.is_file():
        raise FileNotFoundError(f"Unified GeoPackage not found: {gpkg_path}")

    validate_registered_contents(gpkg_path)
    metadata = read_key_value_table(
        gpkg_path, table_name=METADATA_TABLE, key_column="key"
    )
    qa = read_key_value_table(gpkg_path, table_name=QA_TABLE, key_column="check")
    catalog = read_source_catalog(gpkg_path)

    require_keys(
        metadata,
        {
            "title", "dataset_id", "who", "what", "when", "where", "how",
            "dataset_role", "package_purpose", "silver_crs", "assessment_type",
            "data_class", "capacity_data", "capacity_status", "injectivity_status",
            "interpretation_note", "processing_summary", "use_limitations", "keywords",
            "submission_filename", "source_catalog_table", "source_metadata_table",
            "source_qa_table", "precursor_dataset_count",
        },
        context=METADATA_TABLE,
    )
    require_keys(
        qa,
        {
            "feature_layers", "storage_units_count", "storage_features_count",
            "storage_assessments_count", "administrative_features_count",
            "storage_features_invalid_geometry_count",
            "administrative_features_invalid_geometry_count", "silver_crs",
        },
        context=QA_TABLE,
    )

    if metadata["dataset_id"] != DATASET_ID:
        raise ValueError(
            f"Expected dataset_id {DATASET_ID!r}, found {metadata['dataset_id']!r}."
        )
    if metadata["submission_filename"] != gpkg_path.name:
        raise ValueError(
            "Metadata submission filename does not match the supplied GeoPackage: "
            f"{metadata['submission_filename']!r} != {gpkg_path.name!r}"
        )
    if metadata["silver_crs"] != qa["silver_crs"]:
        raise ValueError("Metadata and QA tables disagree on the Silver CRS.")
    if int_value(metadata, "precursor_dataset_count") != len(catalog):
        raise ValueError("Metadata and source catalog disagree on precursor count.")

    created_date = date.fromisoformat(metadata["when"])
    companion_stem = (
        f"{created_date:%Y%m%d}_13_{DATA_TYPE}_AV_{BUILD_VARIANT}"
    )
    source_schema_filename = f"{companion_stem}SourceSchema_AV.csv"
    source_metadata_filename = f"{companion_stem}SourceMetadata_AV.csv"
    qa_summary_filename = f"{companion_stem}QASummary_AV.csv"
    field_dictionary_filename = f"{companion_stem}FieldDictionary_AV.csv"

    source_lines = "\n".join(
        f"- `{str(row.dataset_id)}` - {str(row.source_title)} "
        f"({str(row.source_organization)})."
        for row in catalog.itertuples(index=False)
    )
    registered_contents = markdown_list(
        [
            f"`{str(row.table_name)}` - "
            f"{str(row.description or row.identifier or 'registered GeoPackage table').rstrip('.')}."
            for row in read_registered_contents(gpkg_path).itertuples(index=False)
            if str(row.table_name) in EXPECTED_GPKG_CONTENTS
        ]
    )
    classification = "\n\n".join(
        f"`{key}`: `{metadata[key]}`"
        for key in ("assessment_type", "data_class", "capacity_data", "capacity_status", "injectivity_status")
    )

    return f"""# {metadata['title']}

## CanCO2Re submission metadata

**Who:** {metadata['who']}

**What:** {metadata['what']}

**When:** {metadata['when']}

**Where:** {metadata['where']}

**How:** {metadata['how']}

## Dataset role

{metadata['dataset_role']}

{metadata['package_purpose']}

## Precursor Silver datasets

{source_lines}

The complete precursor metadata and QA tables are retained as key/value lineage
in `{metadata['source_metadata_table']}` and `{metadata['source_qa_table']}`.

## Unified output

GeoPackage:

`{metadata['submission_filename']}`

Registered contents:

{registered_contents}

Spatial feature layers: {format_int(int_value(qa, 'feature_layers'))}

Storage units: {format_int(int_value(qa, 'storage_units_count'))}

Storage features: {format_int(int_value(qa, 'storage_features_count'))}

Storage assessments: {format_int(int_value(qa, 'storage_assessments_count'))}

Administrative features: {format_int(int_value(qa, 'administrative_features_count'))}

CRS: {metadata['silver_crs']} - NAD83 / Canada Atlas Lambert

## Processing

{numbered_steps(PROCESSING_STEPS)}

{metadata['processing_summary']}

## QA notes

- Invalid `storage_features` geometries: {format_int(int_value(qa, 'storage_features_invalid_geometry_count'))}.
- Invalid `administrative_features` geometries: {format_int(int_value(qa, 'administrative_features_invalid_geometry_count'))}.
- Storage-feature null geometries: {format_int(int_value(qa, 'storage_features_null_geometry_count'))}.
- Administrative-feature null geometries: {format_int(int_value(qa, 'administrative_features_null_geometry_count'))}.
- Storage-feature orphan units: {format_int(int_value(qa, 'storage_features_orphan_unit_count'))}.
- Storage-assessment orphan features: {format_int(int_value(qa, 'storage_assessments_orphan_feature_count'))}.
- Storage-assessment orphan units: {format_int(int_value(qa, 'storage_assessments_orphan_unit_count'))}.

## Data classification

{classification}

Keywords:

{metadata['keywords']}

## Companion files

- `{source_schema_filename}` - unified canonical source-schema inventory.
- `{source_metadata_filename}` - persisted precursor and unified metadata export.
- `{qa_summary_filename}` - persisted precursor and unified QA export.
- `{field_dictionary_filename}` - unified canonical field dictionary.

## Researcher quickstart

The repository includes `docs/quickstart.md` and an executable
`examples/unified_quickstart.py` for opening this GeoPackage, joining
assessments at the correct grain, filtering NATCARB representations, and
separating capacity, prospectivity, and tenure. The GeoPackage is the primary
data artifact; the quickstart does not create a second database or a
pre-aggregated capacity layer.

## Use limitations

{metadata['interpretation_note']}

{metadata['use_limitations']}
"""


def default_readme_path(gpkg_path: Path) -> Path:
    """Return a README path derived from the persisted package filename."""

    return Path(gpkg_path).with_suffix(".md")


def generate_readme(gpkg_path: Path, *, output_path: Path | None = None) -> Path:
    """Render and write one unified GeoPackage README."""

    destination = Path(output_path) if output_path is not None else default_readme_path(gpkg_path)
    export_companion_files(gpkg_path)
    return write_readme(destination, build_readme(gpkg_path))


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description="Generate the unified atlas README from its GeoPackage metadata."
    )
    parser.add_argument("--gpkg", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    """Generate the unified atlas README."""

    args = parse_args()
    gpkg_path = args.gpkg if args.gpkg is not None else discover_unified_gpkg()
    readme_path = generate_readme(gpkg_path, output_path=args.output)
    print("Unified atlas metadata")
    print("----------------------")
    print(f"GeoPackage: {gpkg_path}")
    print(f"README:     {readme_path}")


if __name__ == "__main__":
    main()
