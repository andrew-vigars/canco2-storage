"""Generated README metadata for GSC Open File 8996."""

from __future__ import annotations

from datetime import date

from canco2_storage.metadata.common import (
    CANCO2RE_SUBMISSION,
    format_int,
    markdown_list,
    numbered_steps,
)


TITLE = "Atlantic Canada CO₂ Storage Chance of Success"

DATA_TYPE = "AtlanticStorageCOS"

SOURCE_CITATION = (
    "Carey et al. (2023), *Preliminary assessment of geological carbon-storage "
    "potential of Atlantic Canada*, Geological Survey of Canada Open File 8996."
)

SOURCE_DOI = "10.4095/332145"

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
    "Reprojecting harmonized geometries to EPSG:3978.",
    "Repairing and validating geometries again after reprojection.",
    "Appending the harmonized datasets row-wise into one feature layer.",
    "Writing the Silver GeoPackage and reopening the persisted artifact for validation.",
    "Exporting source schema, source metadata, and QA summaries alongside the GeoPackage.",
)

COS_INTERPRETATION = (
    "`reservoir_cos` represents the source reservoir Chance of Success.",
    "`seal_cos` represents the source seal Chance of Success.",
    "`trap_cos` is populated only where an explicit source trap COS field exists.",
    "`total_cos` preserves the combined COS value published by the source dataset.",
    "A null `trap_cos` means that no explicit trap COS attribute was supplied by that "
    "source dataset; it must not be interpreted as a trap COS of zero.",
    "COS should be interpreted as geological prospectivity / chance of success, not "
    "storage capacity.",
)

CLASSIFICATION = (
    ("assessment_type", "qualitative_chance_of_success"),
    ("data_class", "geological_prospectivity"),
    ("capacity_data", "False"),
    ("capacity_status", "not_quantitatively_assessed"),
    ("injectivity_status", "not_quantitatively_assessed"),
)


def build_readme(
    *,
    output_filename: str,
    layer_name: str,
    feature_count: int,
    storage_unit_count: int,
    target_crs: str,
    source_warning_count: int,
    final_invalid_geometry_count: int,
    trap_cos_null_count: int,
    created_date: date,
    source_archive_sha256: str | None = None,
) -> str:
    """Render the GSC Atlantic processed-dataset README.

    Parameters
    ----------
    output_filename : str
        Filename of the generated Silver GeoPackage.
    layer_name : str
        Name of the harmonized Atlantic storage spatial layer.
    feature_count : int
        Number of features preserved in the persisted Silver layer.
    storage_unit_count : int
        Number of distinct storage units represented in the Silver layer.
    target_crs : str
        Coordinate reference system of the Silver output.
    source_warning_count : int
        Number of source-read warnings captured during harmonization.
    final_invalid_geometry_count : int
        Number of invalid geometries remaining in the persisted GeoPackage.
    trap_cos_null_count : int
        Number of features with no explicit source trap COS value.
    created_date : datetime.date
        Date on which the processed submission artifact was generated.
    source_archive_sha256 : str, optional
        SHA-256 checksum of the Bronze source archive, when available.

    Returns
    -------
    str
        Rendered Markdown README content for the GSC Atlantic processed dataset.
    """

    source_hash = (
        f"\nArchive SHA-256:\n\n`{source_archive_sha256}`\n"
        if source_archive_sha256
        else ""
    )

    processing = numbered_steps(PROCESSING_STEPS)
    cos_notes = markdown_list(COS_INTERPRETATION)
    classification = "\n\n".join(
        f"`{key}`: `{value}`"
        for key, value in CLASSIFICATION
    )

    return f"""# {TITLE}

## CanCO₂Re submission metadata

**Who:** {CANCO2RE_SUBMISSION.creator_name}, CanCO₂Re Activity {CANCO2RE_SUBMISSION.activity_code}

**What:** Harmonized Geological Survey of Canada Open File 8996 regional
geological CO₂ storage Chance of Success (COS) mapping. The dataset represents
qualitative geological prospectivity rather than quantified storage capacity
or injectivity.

**When:** {created_date.isoformat()}

**Where:** Atlantic Canada and adjacent offshore assessment areas represented by
Open File 8996. NAD83 / Canada Atlas Lambert, EPSG:3978.

**How:** Derived from 15 Geological Survey of Canada Open File 8996 source
shapefiles. Source COS fields are mapped to a common schema, source feature
provenance is preserved, invalid geometries are repaired when required,
geometries are reprojected to EPSG:3978, and all harmonized source features are
combined into one validated Silver layer without dissolving or spatially
aggregating source polygons.

## Dataset role

{DATASET_ROLE}

{INTERPRETATION}

## Source / Bronze data

Source publication:

{SOURCE_CITATION}

DOI:

{SOURCE_DOI}

The Bronze source consists of 15 shapefile datasets:

- 10 Mesozoic–Cenozoic COS layers
- 5 Upper Paleozoic COS layers

The original shapefiles are retained unchanged as Bronze source data.
{source_hash}
## Silver output

File:

`{output_filename}`

Layer:

`{layer_name}`

Features:

{format_int(feature_count)}

Storage units:

{format_int(storage_unit_count)}

CRS:

{target_crs} — NAD83 / Canada Atlas Lambert

This CRS follows the CanCO₂Re GIS project standard for processed and published spatial data.

## Processing

The Silver layer was produced by:

{processing}

No source polygons are intentionally dissolved, spatially unioned, or aggregated during source harmonization.

## COS interpretation

{cos_notes}

## QA notes

- Source features preserved in Silver: {format_int(feature_count)}.
- Source storage units represented: {format_int(storage_unit_count)}.
- Source read warnings captured: {format_int(source_warning_count)}.
- Final invalid geometries in the persisted GeoPackage: {format_int(final_invalid_geometry_count)}.
- Null `trap_cos` values: {format_int(trap_cos_null_count)}.
- Source-reported `total_cos` values are preserved rather than recomputed.
- Similar mapped areas across some source datasets may represent overlapping or vertically stacked geological plays and should not be summed to infer unique storage area or storage capacity.

## Data classification

{classification}

The dataset should be used as a geological screening or prospectivity layer. Quantified storage-capacity assessment should be represented separately using datasets containing explicit volumetric or mass-based storage-resource estimates.
"""
