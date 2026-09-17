"""Top-level GeoPackage build orchestration for CANCO2-Storage.

This module composes the existing Bronze acquisition and Silver harmonization
orchestrators without duplicating dataset-specific logic.

Dataset implementations remain responsible for their own acquisition,
harmonization, validation, QA, metadata, and documentation behavior.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from canco2_storage.orchestration.bronze import (
    ACQUISITION_MODULES,
    run_bronze,
)
from canco2_storage.orchestration.silver import (
    SILVER_WORKFLOWS,
    run_silver,
)


PIPELINE_DATASETS = tuple(
    dataset_id
    for dataset_id in ACQUISITION_MODULES
    if dataset_id in SILVER_WORKFLOWS
)

BRONZE_DATASETS = tuple(ACQUISITION_MODULES)


def resolve_build_datasets(
    requested: Sequence[str] | None = None,
) -> list[str]:
    """Resolve datasets that can be acquired by the complete build."""

    if not requested:
        return list(BRONZE_DATASETS)

    unknown = sorted(set(requested) - set(BRONZE_DATASETS))

    if unknown:
        raise ValueError(
            "Unknown build dataset ID(s): "
            f"{unknown}. Available datasets: {list(BRONZE_DATASETS)}"
        )

    requested_set = set(requested)

    return [
        dataset_id
        for dataset_id in BRONZE_DATASETS
        if dataset_id in requested_set
    ]


def resolve_pipeline_datasets(
    requested: Sequence[str] | None = None,
) -> list[str]:
    """Resolve datasets that are registered in both Bronze and Silver layers."""

    if not requested:
        return list(PIPELINE_DATASETS)

    bronze_only = sorted(
        dataset_id
        for dataset_id in requested
        if dataset_id in ACQUISITION_MODULES
        and dataset_id not in SILVER_WORKFLOWS
    )
    silver_only = sorted(
        dataset_id
        for dataset_id in requested
        if dataset_id in SILVER_WORKFLOWS
        and dataset_id not in ACQUISITION_MODULES
    )
    unknown = sorted(
        dataset_id
        for dataset_id in requested
        if dataset_id not in ACQUISITION_MODULES
        and dataset_id not in SILVER_WORKFLOWS
    )

    if bronze_only or silver_only or unknown:
        problems: list[str] = []

        if bronze_only:
            problems.append(
                f"registered only for Bronze: {bronze_only}"
            )

        if silver_only:
            problems.append(
                f"registered only for Silver: {silver_only}"
            )

        if unknown:
            problems.append(
                f"not registered: {unknown}"
            )

        raise ValueError(
            "Pipeline datasets must be registered in both orchestration layers; "
            + "; ".join(problems)
            + f". Available pipeline datasets: {list(PIPELINE_DATASETS)}"
        )

    requested_set = set(requested)

    return [
        dataset_id
        for dataset_id in PIPELINE_DATASETS
        if dataset_id in requested_set
    ]


def build_geopackages(
    datasets: Sequence[str] | None = None,
    *,
    run_bronze_layer: bool = True,
    run_silver_layer: bool = True,
) -> None:
    """Build requested CANCO2-Storage GeoPackages through Bronze and Silver layers."""

    if not run_bronze_layer and not run_silver_layer:
        raise ValueError(
            "Pipeline must execute at least one layer."
        )

    selected_bronze = resolve_build_datasets(datasets)
    selected_silver = [
        dataset_id
        for dataset_id in selected_bronze
        if dataset_id in SILVER_WORKFLOWS
    ]

    print("CANCO2-Storage GeoPackage build")
    print("-----------------------")
    print(f"Datasets: {', '.join(selected_bronze)}")
    print(
        "Layers:   "
        + " → ".join(
            layer
            for layer, enabled in (
                ("Bronze", run_bronze_layer),
                ("Silver", run_silver_layer),
            )
            if enabled
        )
    )

    if run_bronze_layer:
        run_bronze(selected_bronze)

    if run_silver_layer and selected_silver:
        run_silver(selected_silver)

    print("\nCANCO2-Storage GeoPackage build complete.")
    print("---------------------------------")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for top-level pipeline orchestration."""

    parser = argparse.ArgumentParser(
        description=(
            "Build CANCO2-Storage GeoPackages through ordered Bronze acquisition "
            "and Silver harmonization."
        )
    )

    parser.add_argument(
        "--datasets",
        nargs="+",
        choices=BRONZE_DATASETS,
        help=(
            "Dataset IDs to process. Omit to run every dataset registered in "
            "both Bronze and Silver orchestration layers."
        ),
    )

    parser.add_argument(
        "--skip-bronze",
        action="store_true",
        help="Skip Bronze acquisition and run only the Silver layer.",
    )

    parser.add_argument(
        "--skip-silver",
        action="store_true",
        help="Skip Silver processing and run only the Bronze layer.",
    )

    return parser.parse_args()


def main() -> None:
    """Build CANCO2-Storage GeoPackages from the command line."""

    args = parse_args()

    build_geopackages(
        datasets=args.datasets,
        run_bronze_layer=not args.skip_bronze,
        run_silver_layer=not args.skip_silver,
    )


if __name__ == "__main__":
    main()
