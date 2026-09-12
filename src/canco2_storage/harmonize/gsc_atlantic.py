"""
Harmonize Geological Survey of Canada Open File 8996.

This module converts the original Atlantic Canada Chance of Success (COS)
shapefiles into a standardized Silver representation.

Open File 8996 is a qualitative geological-storage suitability assessment.
The COS attributes must not be interpreted as quantitative CO2 storage
capacity or injectivity estimates.

Workflow
--------
1. Discover and validate the 15 source shapefiles.
2. Inventory the original source schemas.
3. Validate each layer against an explicit source-field mapping.
4. Standardize geological-unit, COS, provenance, and assessment metadata.
5. Repair invalid geometries when required and reproject to EPSG:3978.
6. Concatenate all source layers into one Silver GeoPackage layer.
7. Export source metadata and QA summaries alongside the GeoPackage.

The original Bronze files are never modified.
"""

from __future__ import annotations

import argparse
import warnings
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import make_valid

from canco2_storage.paths import find_project_root

from canco2_storage.metadata.common import (
    CANCO2RE_SUBMISSION,
    build_submission_stem,
    write_readme,
)

from canco2_storage.metadata.gsc_atlantic import (
    DATA_TYPE,
    build_readme,
)



# =============================================================================
# Project paths
# =============================================================================

PROJECT_ROOT = find_project_root()

RAW_GSC_ATLANTIC = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "gsc_atlantic"
    / "source"
)

PROCESSED_GSC_ATLANTIC = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "gsc_atlantic"
)

CREATED_DATE = date.today()

SUBMISSION_STEM = build_submission_stem(
    data_type=DATA_TYPE,
    created_date=CREATED_DATE,
)

README_PATH = (
    PROCESSED_GSC_ATLANTIC
    / (
        f"{CREATED_DATE:%Y%m%d}_{CANCO2RE_SUBMISSION.activity_code}_"
        f"{DATA_TYPE}README_{CANCO2RE_SUBMISSION.creator_initials}.md"
    )
)

MESOZOIC_DIR = RAW_GSC_ATLANTIC / "Mesozoic-Cenozoic COS Mapping"
PALEOZOIC_DIR = RAW_GSC_ATLANTIC / "Upper Paleozoic COS Mapping"

SILVER_GPKG_PATH = (
    PROCESSED_GSC_ATLANTIC
    / f"{SUBMISSION_STEM}.gpkg"
)

SCHEMA_INVENTORY_PATH = (
    PROCESSED_GSC_ATLANTIC
    / (
        f"{CREATED_DATE:%Y%m%d}_{CANCO2RE_SUBMISSION.activity_code}_"
        f"{DATA_TYPE}SourceSchema_{CANCO2RE_SUBMISSION.creator_initials}.csv"
    )
)

SOURCE_METADATA_PATH = (
    PROCESSED_GSC_ATLANTIC
    / (
        f"{CREATED_DATE:%Y%m%d}_{CANCO2RE_SUBMISSION.activity_code}_"
        f"{DATA_TYPE}SourceMetadata_{CANCO2RE_SUBMISSION.creator_initials}.csv"
    )
)

QA_SUMMARY_PATH = (
    PROCESSED_GSC_ATLANTIC
    / (
        f"{CREATED_DATE:%Y%m%d}_{CANCO2RE_SUBMISSION.activity_code}_"
        f"{DATA_TYPE}QASummary_{CANCO2RE_SUBMISSION.creator_initials}.csv"
    )
)

TARGET_CRS = "EPSG:3978"
EXPECTED_SHAPEFILE_COUNT = 15


# =============================================================================
# Source metadata
# =============================================================================

DATASET_ID = "gsc_atlantic"

SOURCE_ORGANIZATION = "Natural Resources Canada, Geological Survey of Canada"
SOURCE_TITLE = (
    "Preliminary assessment of geological carbon-storage potential "
    "of Atlantic Canada"
)
SOURCE_PUBLICATION = "Geological Survey of Canada Open File 8996"
SOURCE_YEAR = 2023
SOURCE_DOI = "10.4095/332145"
SOURCE_URL = (
    "https://ostrnrcan-dostrncan.canada.ca/entities/publication/"
    "b6140ab8-c5fd-4ad2-b9ed-65c32ff2bb17"
)

LICENCE_NAME = "Open Government Licence - Canada"
LICENCE_URL = "https://open.canada.ca/en/open-government-licence-canada"

ATTRIBUTION_TEXT = (
    "Derived from Carey, J.S., Skinner, C.H., Giles, P.S., Durling, P., "
    "Plourde, A.P., Jauer, C., and Desroches, K. (2023), Preliminary "
    "assessment of geological carbon-storage potential of Atlantic Canada, "
    "Geological Survey of Canada, Open File 8996, Natural Resources Canada. "
    "https://doi.org/10.4095/332145"
)

NON_ENDORSEMENT_STATEMENT = (
    "This derivative dataset is based on an official work published by "
    "Natural Resources Canada and has not been produced in affiliation with, "
    "or with the endorsement of, Natural Resources Canada."
)

ASSESSMENT_TYPE = "qualitative_chance_of_success"
DATA_CLASS = "geological_prospectivity"
CAPACITY_DATA = False
CAPACITY_STATUS = "not_quantitatively_assessed"
INJECTIVITY_STATUS = "not_quantitatively_assessed"


# =============================================================================
# Explicit source-layer mappings
# =============================================================================


@dataclass(frozen=True)
class LayerMapping:
    """Semantic mapping from one provider shapefile to the Silver schema."""

    storage_unit_id: str
    storage_unit_name: str
    assessment_area: str
    geological_group: str
    reservoir_cos: str
    seal_cos: str
    trap_cos: str | None
    total_cos: str
    cos_components: str


LAYER_MAPPINGS: dict[str, LayerMapping] = {
    "ALBIAN_LOGAN_CANYON_TOTAL.shp": LayerMapping(
        storage_unit_id="gsc8996_logan_canyon",
        storage_unit_name="Logan Canyon Formation",
        assessment_area="Scotian Margin",
        geological_group="Mesozoic-Cenozoic",
        reservoir_cos="COS_RES",
        seal_cos="COS_SEAL",
        trap_cos=None,
        total_cos="Total_COS",
        cos_components="reservoir_seal",
    ),
    "BARREMIAN_UPPER_MISSISAUGA_TOTAL.shp": LayerMapping(
        storage_unit_id="gsc8996_upper_missisauga",
        storage_unit_name="Upper Missisauga Formation",
        assessment_area="Scotian Margin",
        geological_group="Mesozoic-Cenozoic",
        reservoir_cos="COS_RES",
        seal_cos="COS_SEAL",
        trap_cos=None,
        total_cos="Total_COS",
        cos_components="reservoir_seal",
    ),
    "BERRIASIAN_LOWER_MISSISAUGA_TOTAL.shp": LayerMapping(
        storage_unit_id="gsc8996_lower_missisauga",
        storage_unit_name="Lower Missisauga Formation",
        assessment_area="Scotian Margin",
        geological_group="Mesozoic-Cenozoic",
        reservoir_cos="COS_RES",
        seal_cos="COS_SEAL",
        trap_cos=None,
        total_cos="TotalCOS",
        cos_components="reservoir_seal",
    ),
    "Bjarni.shp": LayerMapping(
        storage_unit_id="gsc8996_bjarni",
        storage_unit_name="Bjarni Formation",
        assessment_area="Labrador Margin",
        geological_group="Mesozoic-Cenozoic",
        reservoir_cos="COS_Reserv",
        seal_cos="COS_Seal",
        trap_cos="COS_Trap",
        total_cos="TCOS_CCUS",
        cos_components="reservoir_seal_trap",
    ),
    "Fundy.shp": LayerMapping(
        storage_unit_id="gsc8996_fundy",
        storage_unit_name="Fundy Basin",
        assessment_area="Fundy Basin",
        geological_group="Mesozoic-Cenozoic",
        reservoir_cos="Reservoir_",
        seal_cos="Seal_COS",
        trap_cos="Trap_COS",
        total_cos="Combined_C",
        cos_components="reservoir_seal_trap",
    ),
    "Gudrid.shp": LayerMapping(
        storage_unit_id="gsc8996_gudrid",
        storage_unit_name="Gudrid Formation",
        assessment_area="Labrador Margin",
        geological_group="Mesozoic-Cenozoic",
        reservoir_cos="COS_Reserv",
        seal_cos="COS_Seal",
        trap_cos="COS_Trap",
        total_cos="CCOS",
        cos_components="reservoir_seal_trap",
    ),
    "LATE_ALBIAN_CREE_TOTAL.shp": LayerMapping(
        storage_unit_id="gsc8996_cree",
        storage_unit_name="Cree Formation",
        assessment_area="Scotian Margin",
        geological_group="Mesozoic-Cenozoic",
        reservoir_cos="COS_RES",
        seal_cos="COS_SEAL",
        trap_cos=None,
        total_cos="TotalCOS",
        cos_components="reservoir_seal",
    ),
    "Leif.shp": LayerMapping(
        storage_unit_id="gsc8996_leif",
        storage_unit_name="Leif Member",
        assessment_area="Labrador Margin",
        geological_group="Mesozoic-Cenozoic",
        reservoir_cos="COS_Reserv",
        seal_cos="COS_Seal",
        trap_cos="COS_Trap",
        total_cos="CCOS",
        cos_components="reservoir_seal_trap",
    ),
    "UPPER_JURASSIC_MOHAWK_MIC_MAC_TOTAL.shp": LayerMapping(
        storage_unit_id="gsc8996_mohawk_mic_mac",
        storage_unit_name="Mohawk and Mic Mac formations",
        assessment_area="Scotian Margin",
        geological_group="Mesozoic-Cenozoic",
        reservoir_cos="COS_RES",
        seal_cos="COS_SEAL",
        trap_cos=None,
        total_cos="Total_COS",
        cos_components="reservoir_seal",
    ),
    "VALANGINIAN_HAUTERIVIAN_MID_MISSISAUGA_TOTAL.shp": LayerMapping(
        storage_unit_id="gsc8996_middle_missisauga",
        storage_unit_name="Middle Missisauga Formation",
        assessment_area="Scotian Margin",
        geological_group="Mesozoic-Cenozoic",
        reservoir_cos="COS_RES",
        seal_cos="COS_SEAL",
        trap_cos=None,
        total_cos="TotalCOS",
        cos_components="reservoir_seal",
    ),
    "Cumberland_non_Magdalen.shp": LayerMapping(
        storage_unit_id="gsc8996_cumberland_non_magdalen",
        storage_unit_name="Cumberland Group",
        assessment_area="Upper Paleozoic AOIs outside Magdalen",
        geological_group="Upper Paleozoic",
        reservoir_cos="Res_COS",
        seal_cos="Sea_COS",
        trap_cos="Tr_COS",
        total_cos="CCOS_CCUS",
        cos_components="reservoir_seal_trap",
    ),
    "Horton_non_Magdalen.shp": LayerMapping(
        storage_unit_id="gsc8996_horton_non_magdalen",
        storage_unit_name="Horton Group",
        assessment_area="Upper Paleozoic AOIs outside Magdalen",
        geological_group="Upper Paleozoic",
        reservoir_cos="Horton_R_8",
        seal_cos="Horton_Sea",
        trap_cos="Horton_Tra",
        total_cos="Horton_TCO",
        cos_components="reservoir_seal_trap",
    ),
    "Magdalen_Cumberland.shp": LayerMapping(
        storage_unit_id="gsc8996_magdalen_cumberland",
        storage_unit_name="Cumberland Group",
        assessment_area="Magdalen AOI",
        geological_group="Upper Paleozoic",
        reservoir_cos="COS_Reserv",
        seal_cos="COS_Seal",
        trap_cos="COS_Trap",
        total_cos="CCOS_CCUS",
        cos_components="reservoir_seal_trap",
    ),
    "Magdalen_Horton.shp": LayerMapping(
        storage_unit_id="gsc8996_magdalen_horton",
        storage_unit_name="Horton Group",
        assessment_area="Magdalen AOI",
        geological_group="Upper Paleozoic",
        reservoir_cos="COS_Reserv",
        seal_cos="COS_Seal",
        trap_cos="COS_Trap",
        total_cos="COS_CCUS",
        cos_components="reservoir_seal_trap",
    ),
    "Pictou.shp": LayerMapping(
        storage_unit_id="gsc8996_pictou",
        storage_unit_name="Pictou Group",
        assessment_area="Magdalen AOI",
        geological_group="Upper Paleozoic",
        reservoir_cos="COS_Reserv",
        seal_cos="COS_Seal",
        trap_cos="COS_Trap",
        total_cos="CCOS_CCUS",
        cos_components="reservoir_seal_trap",
    ),
}


# =============================================================================
# Source discovery and inspection
# =============================================================================


def discover_shapefiles() -> list[Path]:
    """Discover and validate the 15 GSC Open File 8996 COS shapefiles."""

    shapefiles = sorted(
        [
            *MESOZOIC_DIR.glob("*.shp"),
            *PALEOZOIC_DIR.glob("*.shp"),
        ]
    )

    if len(shapefiles) != EXPECTED_SHAPEFILE_COUNT:
        raise ValueError(
            "Unexpected number of Atlantic COS shapefiles. "
            f"Expected {EXPECTED_SHAPEFILE_COUNT}, "
            f"found {len(shapefiles)}."
        )

    discovered_names = {path.name for path in shapefiles}
    mapped_names = set(LAYER_MAPPINGS)

    missing_mappings = discovered_names - mapped_names
    stale_mappings = mapped_names - discovered_names

    if missing_mappings or stale_mappings:
        raise ValueError(
            "GSC Atlantic layer registry does not match the Bronze dataset. "
            f"Unmapped source files: {sorted(missing_mappings)}; "
            f"mapped but missing files: {sorted(stale_mappings)}."
        )

    return shapefiles


def read_source_layer(
    path: Path,
) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Read one source layer and capture provider/driver geometry warnings."""

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        gdf = gpd.read_file(path)

    warning_messages = [str(item.message) for item in caught]

    if gdf.crs is None:
        raise ValueError(f"Source shapefile has no CRS: {path}")

    return gdf, warning_messages


def inspect_shapefile(path: Path) -> dict[str, object]:
    """Inspect one source shapefile without modifying the Bronze data."""

    gdf, warning_messages = read_source_layer(path)
    crs = gdf.crs
    if crs is None:
        raise ValueError(f"Source shapefile has no CRS: {path}")

    geometry_types = sorted(
        str(value)
        for value in gdf.geometry.geom_type.dropna().unique()
    )

    return {
        "source_file": path.name,
        "geological_group": LAYER_MAPPINGS[path.name].geological_group,
        "feature_count": len(gdf),
        "source_crs": crs.to_string(),
        "geometry_types": ", ".join(geometry_types),
        "column_count": len(gdf.columns),
        "columns": ", ".join(gdf.columns),
        "read_warnings": " | ".join(warning_messages),
    }


def build_schema_inventory(
    shapefiles: list[Path],
) -> pd.DataFrame:
    """Build a source-schema inventory for all Atlantic COS layers."""

    return (
        pd.DataFrame(
            [inspect_shapefile(path) for path in shapefiles]
        )
        .sort_values(
            by=[
                "geological_group",
                "source_file",
            ]
        )
        .reset_index(drop=True)
    )


# =============================================================================
# Source-schema validation
# =============================================================================


def required_mapping_columns(mapping: LayerMapping) -> set[str]:
    """Return the source columns required by one explicit layer mapping."""

    required = {
        mapping.reservoir_cos,
        mapping.seal_cos,
        mapping.total_cos,
    }

    if mapping.trap_cos is not None:
        required.add(mapping.trap_cos)

    return required


def validate_source_schema(
    path: Path,
    gdf: gpd.GeoDataFrame,
) -> None:
    """Validate that one Bronze layer contains its explicitly mapped fields."""

    mapping = LAYER_MAPPINGS[path.name]
    required = required_mapping_columns(mapping)
    missing = required - set(gdf.columns)

    if missing:
        raise ValueError(
            f"{path.name} is missing required mapped field(s): "
            f"{sorted(missing)}"
        )

    if gdf.empty:
        raise ValueError(f"{path.name} contains no features.")

    if gdf.geometry.isna().all():
        raise ValueError(f"{path.name} contains no usable geometry.")


def numeric_cos(
    frame: gpd.GeoDataFrame,
    column: str,
    *,
    layer_name: str,
) -> pd.Series:
    """Convert a mapped COS field to numeric values and validate [0, 1]."""

    raw = frame[column]
    numeric = pd.to_numeric(raw, errors="coerce")

    invalid_conversion = raw.notna() & numeric.isna()
    if invalid_conversion.any():
        examples = raw.loc[invalid_conversion].astype(str).unique()[:5]
        raise ValueError(
            f"{layer_name}.{column} contains non-numeric COS values: "
            f"{examples.tolist()}"
        )

    outside_range = numeric.notna() & (
        (numeric < 0.0) | (numeric > 1.0)
    )
    if outside_range.any():
        examples = numeric.loc[outside_range].unique()[:5]
        raise ValueError(
            f"{layer_name}.{column} contains COS values outside [0, 1]: "
            f"{examples.tolist()}"
        )

    return numeric.astype("Float64")


# =============================================================================
# Geometry normalization
# =============================================================================


def repair_geometries(
    gdf: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, int, int]:
    """Repair topologically invalid geometries without altering Bronze files.

    Parameters
    ----------
    gdf : geopandas.GeoDataFrame
        Geospatial layer to validate and repair.

    Returns
    -------
    tuple
        Repaired GeoDataFrame, invalid count before repair, and invalid count
        after repair.

    Raises
    ------
    ValueError
        If geometries remain invalid after repair.
    """

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
    """Validate that a GeoDataFrame uses the project Silver CRS."""

    if gdf.crs is None or gdf.crs.to_epsg() != 3978:
        raise ValueError(
            f"Expected Silver CRS {TARGET_CRS}, found {gdf.crs}."
        )


# =============================================================================
# Layer harmonization
# =============================================================================


SILVER_COLUMNS = [
    "feature_id",
    "storage_unit_id",
    "storage_unit_name",
    "assessment_area",
    "geological_group",
    "reservoir_cos",
    "seal_cos",
    "trap_cos",
    "total_cos",
    "cos_components",
    "assessment_type",
    "data_class",
    "capacity_data",
    "capacity_status",
    "injectivity_status",
    "source_dataset",
    "source_file",
    "source_feature_id",
    "source_organization",
    "source_title",
    "source_publication",
    "source_year",
    "source_doi",
    "source_url",
    "licence_name",
    "licence_url",
    "geometry",
]


def harmonize_layer(
    path: Path,
) -> tuple[gpd.GeoDataFrame, dict[str, object]]:
    """Harmonize one GSC Atlantic COS shapefile to the Silver schema."""

    mapping = LAYER_MAPPINGS[path.name]
    source, warning_messages = read_source_layer(path)

    validate_source_schema(path, source)

    source_geometry_types = sorted(
        source.geometry.geom_type.dropna().unique().tolist()
    )
    if source.crs is None:
        raise ValueError(f"{path.name} has no CRS after source read.")
    source_crs = source.crs.to_string()

    # Repair provider geometries in their native CRS before reprojection.
    source, invalid_native_before, invalid_native_after = repair_geometries(
        source
    )

    source_feature_id = pd.Series(
        range(len(source)),
        index=source.index,
        dtype="Int64",
    )

    silver = gpd.GeoDataFrame(
        {
            "feature_id": [
                f"{mapping.storage_unit_id}_f{index:06d}"
                for index in range(len(source))
            ],
            "storage_unit_id": mapping.storage_unit_id,
            "storage_unit_name": mapping.storage_unit_name,
            "assessment_area": mapping.assessment_area,
            "geological_group": mapping.geological_group,
            "reservoir_cos": numeric_cos(
                source,
                mapping.reservoir_cos,
                layer_name=path.name,
            ),
            "seal_cos": numeric_cos(
                source,
                mapping.seal_cos,
                layer_name=path.name,
            ),
            "trap_cos": (
                numeric_cos(
                    source,
                    mapping.trap_cos,
                    layer_name=path.name,
                )
                if mapping.trap_cos is not None
                else pd.Series(
                    pd.array([pd.NA] * len(source), dtype="Float64"),
                    index=source.index,
                )
            ),
            "total_cos": numeric_cos(
                source,
                mapping.total_cos,
                layer_name=path.name,
            ),
            "cos_components": mapping.cos_components,
            "assessment_type": ASSESSMENT_TYPE,
            "data_class": DATA_CLASS,
            "capacity_data": CAPACITY_DATA,
            "capacity_status": CAPACITY_STATUS,
            "injectivity_status": INJECTIVITY_STATUS,
            "source_dataset": DATASET_ID,
            "source_file": path.name,
            "source_feature_id": source_feature_id,
            "source_organization": SOURCE_ORGANIZATION,
            "source_title": SOURCE_TITLE,
            "source_publication": SOURCE_PUBLICATION,
            "source_year": SOURCE_YEAR,
            "source_doi": SOURCE_DOI,
            "source_url": SOURCE_URL,
            "licence_name": LICENCE_NAME,
            "licence_url": LICENCE_URL,
        },
        geometry=source.geometry,
        crs=source.crs,
    )

    silver = silver[SILVER_COLUMNS].to_crs(TARGET_CRS)
    validate_target_crs(silver)

    # Reprojection itself can expose or create topology issues. Repair again in
    # the canonical Silver CRS so the in-memory artifact is valid before export.
    silver, invalid_projected_before, invalid_projected_after = (
        repair_geometries(silver)
    )

    if silver["feature_id"].duplicated().any():
        raise ValueError(
            f"{path.name} generated duplicate feature_id values."
        )

    output_geometry_types = sorted(
        silver.geometry.geom_type.dropna().unique().tolist()
    )

    qa = {
        "source_file": path.name,
        "storage_unit_id": mapping.storage_unit_id,
        "storage_unit_name": mapping.storage_unit_name,
        "source_feature_count": len(source),
        "silver_feature_count": len(silver),
        "source_crs": source_crs,
        "target_crs": TARGET_CRS,
        "source_geometry_types": ", ".join(source_geometry_types),
        "silver_geometry_types": ", ".join(output_geometry_types),
        "invalid_geometry_count_native_before_repair": (
            invalid_native_before
        ),
        "invalid_geometry_count_native_after_repair": (
            invalid_native_after
        ),
        "invalid_geometry_count_projected_before_repair": (
            invalid_projected_before
        ),
        "invalid_geometry_count_projected_after_repair": (
            invalid_projected_after
        ),
        "null_geometry_count": int(silver.geometry.isna().sum()),
        "reservoir_cos_null_count": int(
            silver["reservoir_cos"].isna().sum()
        ),
        "seal_cos_null_count": int(
            silver["seal_cos"].isna().sum()
        ),
        "trap_cos_null_count": int(
            silver["trap_cos"].isna().sum()
        ),
        "total_cos_null_count": int(
            silver["total_cos"].isna().sum()
        ),
        "read_warning_count": len(warning_messages),
        "read_warnings": " | ".join(warning_messages),
    }

    return silver, qa

def harmonize_all_layers(
    shapefiles: list[Path],
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Harmonize all 15 source layers and combine them into one Silver layer."""

    frames: list[gpd.GeoDataFrame] = []
    qa_rows: list[dict[str, object]] = []

    for path in shapefiles:
        print(f"[Harmonize] {path.name}")

        silver, qa = harmonize_layer(path)
        frames.append(silver)
        qa_rows.append(qa)

    combined = gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True),
        geometry="geometry",
        crs=TARGET_CRS,
    )

    if combined["feature_id"].duplicated().any():
        duplicates = (
            combined.loc[
                combined["feature_id"].duplicated(keep=False),
                "feature_id",
            ]
            .astype(str)
            .unique()
            .tolist()
        )
        raise ValueError(
            "Combined Silver layer contains duplicate feature IDs: "
            f"{duplicates[:10]}"
        )

    qa_summary = (
        pd.DataFrame(qa_rows)
        .sort_values("source_file")
        .reset_index(drop=True)
    )

    return combined, qa_summary


# =============================================================================
# Metadata
# =============================================================================


def build_source_metadata(
    archive_sha256: str | None = None,
) -> pd.DataFrame:
    """Build one-row source, licence, and interpretation metadata."""

    return pd.DataFrame(
        [
            {
                "dataset_id": DATASET_ID,
                "who": (
                    f"{CANCO2RE_SUBMISSION.creator_name}, "
                    f"CanCO2Re Activity {CANCO2RE_SUBMISSION.activity_code}"
                ),
                "when": CREATED_DATE.isoformat(),
                "submission_filename": SILVER_GPKG_PATH.name,
                "activity_code": CANCO2RE_SUBMISSION.activity_code,
                "creator_initials": CANCO2RE_SUBMISSION.creator_initials,
                "source_organization": SOURCE_ORGANIZATION,
                "source_title": SOURCE_TITLE,
                "source_publication": SOURCE_PUBLICATION,
                "source_year": SOURCE_YEAR,
                "source_doi": SOURCE_DOI,
                "source_url": SOURCE_URL,
                "licence_name": LICENCE_NAME,
                "licence_url": LICENCE_URL,
                "attribution_text": ATTRIBUTION_TEXT,
                "non_endorsement_statement": NON_ENDORSEMENT_STATEMENT,
                "assessment_type": ASSESSMENT_TYPE,
                "data_class": DATA_CLASS,
                "capacity_data": CAPACITY_DATA,
                "capacity_status": CAPACITY_STATUS,
                "injectivity_status": INJECTIVITY_STATUS,
                "target_crs": TARGET_CRS,
                "source_archive_sha256": archive_sha256,
                "interpretation_note": (
                    "Open File 8996 provides qualitative Chance of Success "
                    "mapping. COS values are not quantitative CO2 storage "
                    "capacity or injectivity estimates. Source-reported total "
                    "COS values are preserved rather than recomputed."
                ),
            }
        ]
    )


# =============================================================================
# Export
# =============================================================================


def validate_written_storage_layer(
    expected: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Reopen and validate the written Silver GeoPackage artifact.

    The final file on disk is treated as the authoritative deliverable. If
    serialization leaves invalid geometries, those geometries are repaired in
    EPSG:3978, the layer is rewritten once, and the rewritten artifact is
    validated again.

    Parameters
    ----------
    expected : geopandas.GeoDataFrame
        In-memory Silver layer used to validate feature and identifier counts.

    Returns
    -------
    tuple
        Validated on-disk GeoDataFrame and per-source post-export QA table.

    Raises
    ------
    ValueError
        If the written layer has the wrong CRS, feature count, identifiers,
        null geometries, or geometries that remain invalid after one repair.
    """

    written = gpd.read_file(
        SILVER_GPKG_PATH,
        layer="storage_units",
    )
    validate_target_crs(written)

    if len(written) != len(expected):
        raise ValueError(
            "Written Silver layer feature count does not match the "
            f"in-memory layer: {len(written)} != {len(expected)}."
        )

    if written["feature_id"].duplicated().any():
        raise ValueError(
            "Written Silver layer contains duplicate feature_id values."
        )

    if set(written["feature_id"]) != set(expected["feature_id"]):
        raise ValueError(
            "Written Silver layer feature_id values do not match the "
            "in-memory Silver layer."
        )

    null_geometry_count = int(written.geometry.isna().sum())
    if null_geometry_count:
        raise ValueError(
            "Written Silver layer contains "
            f"{null_geometry_count} null geometries."
        )

    invalid_mask = ~written.geometry.is_valid
    invalid_before = int(invalid_mask.sum())

    invalid_by_source_before = (
        written.loc[invalid_mask]
        .groupby("source_file")
        .size()
        .to_dict()
    )

    if invalid_before:
        print(
            "\n[Post-export repair] "
            f"{invalid_before} invalid geometries detected in the written "
            "GeoPackage."
        )

        written.loc[invalid_mask, "geometry"] = (
            written.loc[invalid_mask, "geometry"]
            .apply(make_valid)
        )

        invalid_after_memory = int(
            (~written.geometry.is_valid).sum()
        )
        if invalid_after_memory:
            raise ValueError(
                "Post-export repair left "
                f"{invalid_after_memory} invalid geometries in memory."
            )

        # Rewrite the authoritative layer once, then reopen it again.
        if SILVER_GPKG_PATH.exists():
            SILVER_GPKG_PATH.unlink()

        written.to_file(
            SILVER_GPKG_PATH,
            layer="storage_units",
            driver="GPKG",
        )

        written = gpd.read_file(
            SILVER_GPKG_PATH,
            layer="storage_units",
        )
        validate_target_crs(written)

    invalid_after = int((~written.geometry.is_valid).sum())

    if invalid_after:
        invalid_sources = (
            written.loc[~written.geometry.is_valid, "source_file"]
            .value_counts()
            .to_dict()
        )
        raise ValueError(
            "Final written GeoPackage still contains invalid geometries "
            f"after repair: {invalid_sources}"
        )

    post_export_rows = []
    for source_file, group in written.groupby("source_file"):
        post_export_rows.append(
            {
                "source_file": source_file,
                "post_export_feature_count": len(group),
                "post_export_invalid_before_repair": int(
                    invalid_by_source_before.get(source_file, 0)
                ),
                "post_export_invalid_after_repair": 0,
                "post_export_null_geometry_count": int(
                    group.geometry.isna().sum()
                ),
            }
        )

    post_export_qa = (
        pd.DataFrame(post_export_rows)
        .sort_values("source_file")
        .reset_index(drop=True)
    )

    return written, post_export_qa


def export_outputs(
    storage_units: gpd.GeoDataFrame,
    schema_inventory: pd.DataFrame,
    qa_summary: pd.DataFrame,
    source_metadata: pd.DataFrame,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Write and validate the Atlantic Silver products."""

    PROCESSED_GSC_ATLANTIC.mkdir(
        parents=True,
        exist_ok=True,
    )

    if SILVER_GPKG_PATH.exists():
        SILVER_GPKG_PATH.unlink()

    storage_units.to_file(
        SILVER_GPKG_PATH,
        layer="storage_units",
        driver="GPKG",
    )

    final_storage_units, post_export_qa = validate_written_storage_layer(
        expected=storage_units,
    )

    qa_summary = qa_summary.merge(
        post_export_qa,
        on="source_file",
        how="left",
        validate="one_to_one",
    )

    schema_inventory.to_csv(
        SCHEMA_INVENTORY_PATH,
        index=False,
    )
    source_metadata.to_csv(
        SOURCE_METADATA_PATH,
        index=False,
    )
    qa_summary.to_csv(
        QA_SUMMARY_PATH,
        index=False,
    )

    print("\nSilver outputs")
    print("--------------")
    print(f"GeoPackage:       {SILVER_GPKG_PATH}")
    print(f"Schema inventory: {SCHEMA_INVENTORY_PATH}")
    print(f"Source metadata:  {SOURCE_METADATA_PATH}")
    print(f"QA summary:       {QA_SUMMARY_PATH}")

    return final_storage_units, qa_summary


# =============================================================================
# Workflow
# =============================================================================


def run_harmonization(
    *,
    inspect_only: bool = False,
) -> None:
    """Run source inspection or the complete Atlantic Silver build."""

    shapefiles = discover_shapefiles()

    print("GSC Atlantic storage harmonization")
    print("---------------------------------")
    print(f"Source root: {RAW_GSC_ATLANTIC}")
    print(f"Shapefiles: {len(shapefiles)}")
    print(f"Target CRS: {TARGET_CRS}\n")

    schema_inventory = build_schema_inventory(shapefiles)

    PROCESSED_GSC_ATLANTIC.mkdir(
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

    storage_units, qa_summary = harmonize_all_layers(shapefiles)

    # The acquisition layer owns hashing. The harmonizer records the checksum
    # only when a sidecar text file is eventually supplied; it does not
    # duplicate acquisition logic here.
    archive_sha256 = None

    source_metadata = build_source_metadata(
        archive_sha256=archive_sha256,
    )

    final_storage_units, qa_summary = export_outputs(
        storage_units=storage_units,
        schema_inventory=schema_inventory,
        qa_summary=qa_summary,
        source_metadata=source_metadata,
    )

    readme_text = build_readme(
        output_filename=SILVER_GPKG_PATH.name,
        layer_name="storage_units",
        feature_count=len(final_storage_units),
        storage_unit_count=final_storage_units["storage_unit_id"].nunique(),
        target_crs=TARGET_CRS,
        source_warning_count=int(
            qa_summary["read_warning_count"].sum()
        ),
        final_invalid_geometry_count=int(
            (~final_storage_units.geometry.is_valid).sum()
        ),
        trap_cos_null_count=int(
            final_storage_units["trap_cos"].isna().sum()
        ),
        created_date=CREATED_DATE,
    )

    write_readme(
        README_PATH,
        readme_text,
    )

    print(f"README:        {README_PATH}")

    print("\nHarmonization summary")
    print("---------------------")
    print(f"Features:      {len(final_storage_units):,}")
    print(
        "Storage units: "
        f"{final_storage_units['storage_unit_id'].nunique():,}"
    )
    print(f"CRS:           {final_storage_units.crs}")
    print(
        "Source warnings: "
        f"{int(qa_summary['read_warning_count'].sum()):,}"
    )
    print(
        "Final invalid geometries: "
        f"{int((~final_storage_units.geometry.is_valid).sum()):,}"
    )


# =============================================================================
# CLI
# =============================================================================


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Inspect or harmonize GSC Open File 8996 Atlantic Canada "
            "geological-storage Chance of Success layers."
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
    """Run the Atlantic harmonization workflow."""

    args = parse_args()

    run_harmonization(
        inspect_only=args.inspect_only,
    )


if __name__ == "__main__":
    main()
