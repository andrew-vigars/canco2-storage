"""Shared harmonization utilities for CANCO2-Storage Silver workflows.

This module contains dataset-agnostic mechanics that are reused by multiple
harmonizers. Dataset-specific geological interpretation, source mappings,
reconciliation rules, and ontology decisions must remain in the individual
harmonization modules.

The helpers here cover:

- reading geospatial source layers while capturing provider/driver warnings;
- repairing invalid geometries without modifying Bronze inputs;
- validating the canonical Silver CRS;
- optional reprojection plus geometry measurements;
- validating persisted GeoPackage feature layers;
- registering nonspatial attribute tables in a GeoPackage; and
- validating the registered GeoPackage layer/table contract.
"""

from __future__ import annotations

import sqlite3
import warnings
from pathlib import Path
from typing import Mapping

import geopandas as gpd
import pandas as pd
from pyproj import CRS
from shapely import make_valid


SILVER_CRS = "EPSG:3978"


def read_source_layer(
    path: Path,
) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Read one geospatial source layer and capture provider/driver warnings.

    Parameters
    ----------
    path : pathlib.Path
        Path to the source vector dataset.

    Returns
    -------
    tuple
        GeoDataFrame and captured warning messages.

    Raises
    ------
    ValueError
        If the source layer does not declare a coordinate reference system.
    """

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        gdf = gpd.read_file(path)

    warning_messages = [
        str(item.message)
        for item in caught
    ]

    if gdf.crs is None:
        raise ValueError(
            f"Source geospatial layer has no CRS: {path}"
        )

    return gdf, warning_messages


def repair_geometries(
    gdf: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, int, int]:
    """Repair topologically invalid non-null geometries.

    The input GeoDataFrame is copied before repair, so Bronze-derived in-memory
    data are not modified in place.

    Returns
    -------
    tuple
        Repaired GeoDataFrame, invalid count before repair, and invalid count
        after repair.

    Raises
    ------
    ValueError
        If invalid non-null geometries remain after ``make_valid``.
    """

    result = gdf.copy()

    non_null = result.geometry.notna()
    invalid_before_mask = (
        non_null
        & ~result.geometry.is_valid
    )
    invalid_before = int(
        invalid_before_mask.sum()
    )

    if invalid_before:
        result.loc[
            invalid_before_mask,
            "geometry",
        ] = (
            result.loc[
                invalid_before_mask,
                "geometry",
            ]
            .apply(make_valid)
        )

    invalid_after_mask = (
        result.geometry.notna()
        & ~result.geometry.is_valid
    )
    invalid_after = int(
        invalid_after_mask.sum()
    )

    if invalid_after:
        raise ValueError(
            "Geometry repair left "
            f"{invalid_after} invalid geometries."
        )

    return (
        result,
        invalid_before,
        invalid_after,
    )


def validate_target_crs(
    gdf: gpd.GeoDataFrame,
    *,
    target_crs: str = SILVER_CRS,
) -> None:
    """Require a GeoDataFrame to use the requested Silver CRS."""

    crs = gdf.crs

    if crs is None:
        raise ValueError(
            "Silver spatial layer has no CRS."
        )

    expected = CRS.from_user_input(
        target_crs
    )

    if crs != expected:
        raise ValueError(
            f"Expected Silver CRS {target_crs}, found {crs}."
        )


def project_and_measure(
    gdf: gpd.GeoDataFrame,
    *,
    target_crs: str = SILVER_CRS,
) -> tuple[gpd.GeoDataFrame, int, int]:
    """Reproject, repair, validate, and calculate standard geometry measures.

    The returned GeoDataFrame contains ``geometry_area_m2``,
    ``geometry_area_ha``, and ``geometry_perimeter_m``.
    """

    if gdf.crs is None:
        raise ValueError(
            "Cannot reproject a spatial layer without a CRS."
        )

    projected = gdf.to_crs(
        target_crs
    )

    validate_target_crs(
        projected,
        target_crs=target_crs,
    )

    (
        projected,
        invalid_before,
        invalid_after,
    ) = repair_geometries(
        projected
    )

    projected["geometry_area_m2"] = (
        projected.geometry.area
    )
    projected["geometry_area_ha"] = (
        projected["geometry_area_m2"]
        / 10_000.0
    )
    projected["geometry_perimeter_m"] = (
        projected.geometry.length
    )

    return (
        projected,
        invalid_before,
        invalid_after,
    )


def validate_written_spatial_layer(
    *,
    gpkg_path: Path,
    layer_name: str,
    expected: gpd.GeoDataFrame,
    unique_id_field: str,
    target_crs: str = SILVER_CRS,
) -> gpd.GeoDataFrame:
    """Reopen and strictly validate one persisted GeoPackage feature layer.

    This validator does not repair the written artifact. Geometry repair should
    occur before export. A serialization-specific repair workflow, when needed,
    should remain explicit in the dataset harmonizer because rewriting one
    layer of a multi-layer GeoPackage can have dataset-specific consequences.
    """

    written = gpd.read_file(
        gpkg_path,
        layer=layer_name,
    )

    validate_target_crs(
        written,
        target_crs=target_crs,
    )

    if len(written) != len(expected):
        raise ValueError(
            f"{layer_name} feature count changed during export: "
            f"{len(written)} != {len(expected)}."
        )

    if unique_id_field not in written.columns:
        raise ValueError(
            f"{layer_name} is missing required identifier field "
            f"{unique_id_field!r} after export."
        )

    if written[
        unique_id_field
    ].duplicated().any():
        raise ValueError(
            f"{layer_name} contains duplicate "
            f"{unique_id_field} values."
        )

    if (
        set(written[unique_id_field])
        != set(expected[unique_id_field])
    ):
        raise ValueError(
            f"{layer_name} identifiers changed during export."
        )

    null_count = int(
        written.geometry.isna().sum()
    )
    empty_count = int(
        written.geometry.is_empty.sum()
    )
    invalid_count = int(
        (
            written.geometry.notna()
            & ~written.geometry.is_valid
        ).sum()
    )

    if null_count:
        raise ValueError(
            f"{layer_name} contains "
            f"{null_count} null geometries."
        )

    if empty_count:
        raise ValueError(
            f"{layer_name} contains "
            f"{empty_count} empty geometries."
        )

    if invalid_count:
        raise ValueError(
            f"{layer_name} contains "
            f"{invalid_count} invalid geometries "
            "after GeoPackage serialization."
        )

    return written


def register_attribute_table(
    conn: sqlite3.Connection,
    *,
    table_name: str,
    description: str,
) -> None:
    """Register one nonspatial table in ``gpkg_contents``."""

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
            table_name,
            table_name,
            description,
        ),
    )


def write_registered_attribute_table(
    conn: sqlite3.Connection,
    *,
    dataframe: pd.DataFrame,
    table_name: str,
    description: str,
) -> None:
    """Write one DataFrame to SQLite and register it as a GPKG attribute table."""

    dataframe.to_sql(
        table_name,
        conn,
        if_exists="replace",
        index=False,
    )

    register_attribute_table(
        conn,
        table_name=table_name,
        description=description,
    )


def validate_registered_tables(
    *,
    gpkg_path: Path,
    expected: Mapping[str, str],
) -> None:
    """Validate the required ``gpkg_contents`` layer/table contract.

    Parameters
    ----------
    gpkg_path : pathlib.Path
        GeoPackage to inspect.
    expected : Mapping[str, str]
        Mapping of expected table names to GeoPackage data types, typically
        ``"features"`` or ``"attributes"``.
    """

    with sqlite3.connect(
        gpkg_path
    ) as conn:
        contents = pd.read_sql_query(
            """
            SELECT table_name, data_type
            FROM gpkg_contents
            """,
            conn,
        )

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
            "GeoPackage contents are missing expected "
            "registered layers/tables: "
            f"{missing_or_wrong}"
        )
