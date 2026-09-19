"""First-five-minutes researcher workflow for the unified GeoPackage."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UNIFIED_DIR = PROJECT_ROOT / "data" / "processed" / "unified_storage"
EXPECTED_LAYERS = {
    "storage_units",
    "storage_features",
    "storage_assessments",
    "administrative_features",
}


def find_package() -> Path:
    """Return the newest dated unified GeoPackage."""

    candidates = sorted(
        UNIFIED_DIR.glob("*_13_CanadaGeologicalStorageUnified_AV_v2.gpkg")
    )
    if not candidates:
        raise FileNotFoundError(
            f"No unified GeoPackage found under {UNIFIED_DIR}. "
            "Build it with canco2-build-unified first."
        )
    return candidates[-1]


def read_package(package: Path) -> dict[str, gpd.GeoDataFrame]:
    """Read the canonical tables directly from one GeoPackage."""

    layers = set(gpd.list_layers(package).iloc[:, 0])
    missing = EXPECTED_LAYERS - layers
    if missing:
        raise ValueError(f"Unified GeoPackage is missing layers: {sorted(missing)}")

    return {
        "units": gpd.read_file(package, layer="storage_units", ignore_geometry=True),
        "features": gpd.read_file(package, layer="storage_features"),
        "assessments": gpd.read_file(
            package,
            layer="storage_assessments",
            ignore_geometry=True,
        ),
        "tenure": gpd.read_file(package, layer="administrative_features"),
    }


def main() -> None:
    """Print safe first-pass summaries without writing derived data."""

    package = find_package()
    tables = read_package(package)
    units = tables["units"]
    features = tables["features"]
    assessments = tables["assessments"]
    tenure = tables["tenure"]

    feature_assessments = assessments.loc[
        assessments["assessment_scope"].eq("feature")
    ].merge(
        features[["storage_feature_id", "storage_unit_id", "source_layer"]],
        on="storage_feature_id",
        how="left",
        validate="many_to_one",
    )
    unit_assessments = assessments.loc[
        assessments["assessment_scope"].eq("unit")
    ].merge(
        units[
            [
                "storage_unit_id",
                "storage_name",
                "data_class",
                "capacity_data",
            ]
        ],
        on="storage_unit_id",
        how="left",
        validate="many_to_one",
    )

    capacity = unit_assessments.loc[
        unit_assessments["data_class"].eq("geological_storage_capacity")
        & unit_assessments["capacity_data"].fillna(False).astype(bool)
        & unit_assessments["storage_p50_tonnes"].notna()
    ]
    capacity_summary = (
        capacity.groupby(["source_dataset", "source_layer"], dropna=False)
        .agg(
            assessment_count=("storage_assessment_id", "size"),
            p50_tonnes=("storage_p50_tonnes", "sum"),
        )
        .reset_index()
    )

    natcarb = features.loc[features["source_dataset"].eq("NATCARB")]
    natcarb_summary = (
        natcarb.groupby(["source_layer", "representation"], dropna=False)
        .size()
        .rename("feature_count")
        .reset_index()
    )
    role_summary = (
        assessments.merge(
            units[["storage_unit_id", "data_class", "capacity_data"]],
            on="storage_unit_id",
            how="left",
            validate="many_to_one",
        ).groupby(
            ["data_class", "assessment_type", "capacity_data"],
            dropna=False,
        )
        .size()
        .rename("record_count")
        .reset_index()
    )

    print(f"GeoPackage: {package}")
    print(f"Logical units: {len(units):,}")
    print(f"Spatial features: {len(features):,}")
    print(f"Assessments: {len(assessments):,}")
    print(f"Administrative features: {len(tenure):,}")
    print(f"Feature-scoped assessments joined: {len(feature_assessments):,}")
    print(f"Unit-scoped assessments joined: {len(unit_assessments):,}")
    print("\nUnit-scoped capacity summary:")
    print(capacity_summary.to_string(index=False))
    print("\nNATCARB representations:")
    print(natcarb_summary.to_string(index=False))
    print("\nAssessment semantic roles:")
    print(role_summary.to_string(index=False))


if __name__ == "__main__":
    main()
