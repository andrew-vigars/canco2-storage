"""Silver package orchestration for CANCO2-Storage.

This module coordinates dataset-specific Silver build workflows while leaving
all harmonization, validation, metadata, QA, and documentation logic inside the
existing ``harmonize`` and ``metadata`` modules.

A Silver workflow may contain one or more package modules. For example, the
Northeast BC atlas harmonizer writes the authoritative GeoPackage first and its
metadata module then renders the README from the persisted artifact.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence


SILVER_WORKFLOWS: dict[str, tuple[str, ...]] = {
    "aer_agreements": (
        "canco2_storage.harmonize.aer_agreements",
    ),
    "gbc_ne_atlas": (
        "canco2_storage.harmonize.gbc_ne_atlas",
        "canco2_storage.metadata.gbc_ne_atlas",
    ),
    "gsc_atlantic": (
        "canco2_storage.harmonize.gsc_atlantic",
    ),
}


def resolve_datasets(
    requested: Sequence[str] | None = None,
) -> list[str]:
    """Resolve requested dataset IDs to an ordered Silver build queue."""

    if not requested:
        return list(SILVER_WORKFLOWS)

    unknown = sorted(set(requested) - set(SILVER_WORKFLOWS))

    if unknown:
        raise ValueError(
            "Unknown Silver dataset ID(s): "
            f"{unknown}. Available datasets: {sorted(SILVER_WORKFLOWS)}"
        )

    requested_set = set(requested)

    return [
        dataset_id
        for dataset_id in SILVER_WORKFLOWS
        if dataset_id in requested_set
    ]


def run_module(
    module_name: str,
) -> None:
    """Run one package module in the active Python environment."""

    print(f"  [Run] {module_name}")

    subprocess.run(
        [
            sys.executable,
            "-m",
            module_name,
        ],
        check=True,
    )


def run_silver_dataset(
    dataset_id: str,
) -> None:
    """Run the complete Silver workflow for one registered dataset."""

    modules = SILVER_WORKFLOWS[dataset_id]

    print(f"\n[Silver] {dataset_id}")
    print("-" * (9 + len(dataset_id)))

    for module_name in modules:
        run_module(module_name)


def run_silver(
    datasets: Sequence[str] | None = None,
) -> None:
    """Run the requested independent Silver package workflows.

    When ``datasets`` is omitted, all registered Silver workflows run in
    registry order.
    """

    selected = resolve_datasets(datasets)

    print("CANCO2-Storage Silver build")
    print("--------------------------")
    print(f"Datasets: {', '.join(selected)}")

    for dataset_id in selected:
        run_silver_dataset(dataset_id)

    print("\nSilver build complete.")
    print("----------------------")
    print(f"Completed datasets: {len(selected)}")
