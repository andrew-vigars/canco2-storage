"""Generated README metadata for AER Carbon Sequestration Agreements."""

from __future__ import annotations

from datetime import date

from canco2_storage.metadata.common import (
    CANCO2RE_SUBMISSION,
    format_int,
    markdown_list,
    numbered_steps,
)


TITLE = "Alberta Carbon Sequestration Agreements"

DATA_TYPE = "AERCarbonSequestrationAgreements"

SOURCE_ORGANIZATION = "Alberta Energy Regulator (AER)"
SOURCE_DATASET = "Carbon Sequestration Agreements"
SOURCE_ACCESS = "https://gis.energy.gov.ab.ca/Geoview/CarbonSequestration"
SOURCE_PARENT = (
    "https://www.alberta.ca/"
    "carbon-capture-utilization-and-storage-carbon-sequestration-tenure"
)

DATASET_ROLE = (
    "Silver-layer harmonization of Alberta Energy Regulator (AER) Carbon "
    "Sequestration Agreement spatial data."
)

INTERPRETATION = (
    "This dataset represents regulatory / tenure information associated with "
    "carbon sequestration pore-space agreements. It does not represent "
    "quantified geological CO₂ storage capacity, injectivity, geological "
    "prospectivity, storage probability, permitted injection capacity, or "
    "project-ready storage resource."
)

SOURCE_DISCLAIMER = (
    "AER states that Carbon Sequestration Agreement boundaries are shown to the "
    "full ATS Landkey and may therefore appear to include minerals not owned by "
    "the Alberta Crown and/or minerals reserved from disposition."
)

PROCESSING_STEPS = (
    "Reading the source AER Carbon Sequestration Agreements shapefile.",
    "Inspecting source fields, identifiers, categorical values, dates, and tract structure.",
    "Preserving agreement, tract, and agreement-type identifiers as text to retain leading zeros and source coding.",
    "Harmonizing source attribute names into descriptive Silver-layer field names.",
    "Converting source date fields into standardized datetime values.",
    "Preserving source agreement-area attributes and source geometry-derived area and length measurements.",
    "Preserving the source coordinate reference system in the `source_crs` provenance field.",
    "Repairing invalid source geometries when required.",
    "Reprojecting source geometries from EPSG:3400 to EPSG:3978.",
    "Repairing and validating geometries again after reprojection.",
    "Recalculating geometry area and perimeter in the Silver CRS.",
    "Constructing stable feature-level provenance identifiers for agreement-tract records.",
    "Adding CanCO₂Re dataset classification fields.",
    "Preserving one source feature per agreement tract.",
    "Validating agreement-level attribute consistency before tract dissolve.",
    "Dissolving tract features by `agreement_id` to create the agreement-level layer.",
    "Preserving distinct tract-level geological zone descriptions during agreement dissolve by concatenating unique values rather than discarding them.",
    "Generating dataset-level metadata and QA tables.",
    "Writing the GeoPackage and reopening the persisted spatial layers for validation.",
)

REGULATORY_LIMITATIONS = (
    "technically recoverable CO₂ storage capacity",
    "reservoir injectivity",
    "reservoir quality",
    "storage probability or chance of success",
    "allowable injection rate",
    "permitted injection capacity",
    "commercial project feasibility",
)

CLASSIFICATION = (
    ("assessment_type", "carbon_sequestration_agreement"),
    ("data_class", "regulatory_tenure"),
    ("capacity_data", "False"),
)


def build_readme(
    *,
    output_filename: str,
    tract_layer_name: str,
    agreement_layer_name: str,
    tract_dictionary_filename: str,
    agreement_dictionary_filename: str,
    tract_feature_count: int,
    agreement_feature_count: int,
    multi_tract_agreement_count: int,
    target_crs: str,
    tract_invalid_geometry_count: int,
    agreement_invalid_geometry_count: int,
    median_area_ratio: float,
    median_length_ratio: float,
    created_date: date,
    source_archive_sha256: str | None = None,
) -> str:
    """Render the AER processed-dataset README.

    Parameters
    ----------
    output_filename : str
        Filename of the generated Silver GeoPackage.
    tract_layer_name : str
        Name of the agreement-tract spatial layer.
    agreement_layer_name : str
        Name of the dissolved agreement-level spatial layer.
    tract_feature_count : int
        Number of features in the persisted tract layer.
    agreement_feature_count : int
        Number of unique agreement features in the persisted agreement layer.
    multi_tract_agreement_count : int
        Number of agreements composed of more than one source tract.
    target_crs : str
        Coordinate reference system of the Silver outputs.
    tract_invalid_geometry_count : int
        Number of invalid geometries remaining in the persisted tract layer.
    agreement_invalid_geometry_count : int
        Number of invalid geometries remaining in the persisted agreement layer.
    median_area_ratio : float
        Median ratio of source geometry area to Silver geometry area.
    median_length_ratio : float
        Median ratio of source geometry length to Silver geometry perimeter.
    created_date : datetime.date
        Date on which the processed submission artifact was generated.
    source_archive_sha256 : str, optional
        SHA-256 checksum of the Bronze source archive, when available.

    Returns
    -------
    str
        Rendered Markdown README content for the AER processed dataset.
    """

    source_hash = (
        f"\nSource archive SHA-256:\n\n`{source_archive_sha256}`\n"
        if source_archive_sha256
        else ""
    )

    processing = numbered_steps(PROCESSING_STEPS)
    limitations = markdown_list(REGULATORY_LIMITATIONS)
    classification = "\n\n".join(
        f"`{key}`: `{value}`"
        for key, value in CLASSIFICATION
    )

    return f"""# {TITLE}

## CanCO₂Re submission metadata

**Who:** {CANCO2RE_SUBMISSION.creator_name}, CanCO₂Re Activity {CANCO2RE_SUBMISSION.activity_code}

**What:** Harmonized Alberta Energy Regulator Carbon Sequestration Agreement
spatial data representing regulatory / tenure boundaries associated with carbon
sequestration pore-space agreements. Area attributes are reported in hectares
where applicable, and harmonized geometry measurements are reported in square
metres, hectares, and metres.

**When:** {created_date.isoformat()}

**Where:** Alberta, Canada. NAD83 / Canada Atlas Lambert, EPSG:3978.

**How:** Derived from the Alberta Energy Regulator Carbon Sequestration
Agreements shapefile. Source fields are standardized, identifiers and source
geometry measurements are retained, source geometry is validated and
reprojected from EPSG:3400 to EPSG:3978, and agreement-level polygons are
produced by dissolving agreement-tract records after validating agreement-level
attribute consistency.

## Dataset role

{DATASET_ROLE}

{INTERPRETATION}

## Source / Bronze data

Source organization:

{SOURCE_ORGANIZATION}

Source dataset:

*{SOURCE_DATASET}*

Source access:

{SOURCE_ACCESS}

Parent page:

{SOURCE_PARENT}

The Bronze source consists of one shapefile dataset and its associated sidecar files.

The original source files are retained unchanged as Bronze data.

The source coordinate reference system is:

EPSG:3400 — NAD83 / Alberta 10-TM (Forest).

{SOURCE_DISCLAIMER}
{source_hash}
## Silver output

File:

`{output_filename}`

Spatial layers:

`{tract_layer_name}`

- Features: {format_int(tract_feature_count)}
- Represents the source agreement-tract structure.
- Preserves one feature per source tract.
- Retains source geometry measurements and feature-level provenance.

`{agreement_layer_name}`

- Features: {format_int(agreement_feature_count)}
- Represents one feature per unique AER agreement.
- Derived by dissolving tract geometries using `agreement_id`.
- Multi-tract agreements: {format_int(multi_tract_agreement_count)}.

Supporting tables:

`metadata_aer_agreements`

- Dataset-level provenance, processing, source, use, and classification metadata.

`qa_aer_agreements`

- Dataset-level quality-assurance and validation summary.

Field dictionaries:

`{tract_dictionary_filename}`

`{agreement_dictionary_filename}`

CRS:

{target_crs} — NAD83 / Canada Atlas Lambert

This CRS follows the CanCO₂Re GIS project standard for processed and published spatial data.

## Processing

The Silver layers were produced by:

{processing}

No geological storage capacity, injectivity, probability, or reservoir-performance attributes are inferred from the agreement polygons.

## Agreement and tract interpretation

`agreement_id` represents the AER agreement identifier.

`tract_id` represents a tract within an agreement.

Agreement-level attributes are checked for consistency before tract dissolve.

`zone_description` may differ between tracts belonging to the same agreement. The tract layer preserves the original tract-specific value, while the agreement layer concatenates distinct tract-specific descriptions using ` | `.

The reported `original_area_ha` and `agreement_area_ha` fields are agreement-level source attributes and are therefore not summed when multiple tracts belong to one agreement.

## Area and geometry interpretation

The source geometry-derived fields are preserved separately from geometry measurements recalculated after reprojection to EPSG:3978.

Median source / Silver area ratio:

{median_area_ratio:.6f}

Median source / Silver length ratio:

{median_length_ratio:.6f}

These differences reflect measurement under different projected coordinate reference systems and do not indicate a change in the underlying source boundaries.

The AER-reported `agreement_area_ha` should be interpreted as a source administrative agreement-area attribute, while the `geometry_area_*` fields are calculated directly from the harmonized spatial geometry.

## Regulatory interpretation and limitations

The AER agreement polygons describe regulatory or tenure boundaries associated with carbon sequestration pore-space rights.

They should not be interpreted as direct evidence of:

{limitations}

Detailed legal interpretation of permit and lease rights should be confirmed against authoritative AER or Alberta Crown Land records.

This dataset is intended primarily as a regulatory / tenure layer that can later be spatially related to independent geological storage-resource datasets.

## QA notes

- Source / Silver tract features: {format_int(tract_feature_count)}.
- Unique Silver agreements: {format_int(agreement_feature_count)}.
- Multi-tract agreements: {format_int(multi_tract_agreement_count)}.
- Tract-layer invalid geometries in the persisted GeoPackage: {format_int(tract_invalid_geometry_count)}.
- Agreement-layer invalid geometries in the persisted GeoPackage: {format_int(agreement_invalid_geometry_count)}.
- Source CRS: EPSG:3400.
- Silver CRS: {target_crs}.
- Agreement-level attributes are checked for consistency before tract dissolve.
- Source geometry-derived measurements are retained separately from geometry measurements recalculated in EPSG:3978.
- Source values are preserved rather than altered to force agreement between reported administrative area and calculated geometry area.

## Data classification

{classification}

The dataset should be used as a regulatory / tenure layer for identifying the spatial extent and attributes of AER carbon sequestration agreements.

Geological storage prospectivity, storage capacity, injectivity, and other subsurface resource characteristics should be represented using separate geological datasets and linked to this layer through subsequent spatial integration.
"""
