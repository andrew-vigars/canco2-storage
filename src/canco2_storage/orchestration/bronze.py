"""Bronze acquisition orchestration for CANCO2-Storage.

This module coordinates the independent acquisition workflows under
``canco2_storage.acquisition``. It contains orchestration logic only; individual
dataset modules remain responsible for downloading, extracting, validating, and
organizing their own Bronze inputs.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence


ACQUISITION_MODULES: dict[str, str] = {
    "statcan_digital_boundaries": (
        "canco2_storage.acquisition.statcan_digital_boundaries"
    ),
    "aer_agreements": "canco2_storage.acquisition.aer_agreements",
    "gbc_ne_atlas": "canco2_storage.acquisition.gbc_ne_atlas",
    "gsc_atlantic": "canco2_storage.acquisition.gsc_atlantic",
    "natcarb_doe": "canco2_storage.acquisition.natcarb_doe",
}


def resolve_datasets(
    requested: Sequence[str] | None = None,
) -> list[str]:
    """Resolve requested dataset IDs to an ordered acquisition queue."""

    if not requested:
        return list(ACQUISITION_MODULES)

    unknown = sorted(set(requested) - set(ACQUISITION_MODULES))

    if unknown:
        raise ValueError(
            "Unknown acquisition dataset ID(s): "
            f"{unknown}. Available datasets: {sorted(ACQUISITION_MODULES)}"
        )

    requested_set = set(requested)

    return [
        dataset_id
        for dataset_id in ACQUISITION_MODULES
        if dataset_id in requested_set
    ]


def run_acquisition_module(
    dataset_id: str,
) -> None:
    """Run one registered acquisition workflow."""

    module_name = ACQUISITION_MODULES[dataset_id]

    print(f"\n[Bronze] {dataset_id}")
    print("-" * (9 + len(dataset_id)))
    print(f"Module: {module_name}")

    subprocess.run(
        [
            sys.executable,
            "-m",
            module_name,
        ],
        check=True,
    )


def run_bronze(
    datasets: Sequence[str] | None = None,
) -> None:
    """Run the requested Bronze acquisition workflows.

    When ``datasets`` is omitted, all registered acquisition workflows run in
    registry order.
    """

    selected = resolve_datasets(datasets)

    print("CANCO2-Storage Bronze acquisition")
    print("--------------------------------")
    print(f"Datasets: {', '.join(selected)}")

    for dataset_id in selected:
        run_acquisition_module(dataset_id)

    print("\nBronze acquisition complete.")
    print("----------------------------")
    print(f"Completed datasets: {len(selected)}")



# =============================================================================
# CLI
# =============================================================================


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for Bronze acquisition orchestration."""

    parser = argparse.ArgumentParser(
        description=(
            "Run one or more registered CANCO2-Storage Bronze acquisition workflows."
        )
    )

    parser.add_argument(
        "--datasets",
        nargs="+",
        choices=tuple(ACQUISITION_MODULES),
        help=(
            "Dataset IDs to acquire. Omit to run all registered Bronze workflows "
            "in registry order."
        ),
    )

    return parser.parse_args()


def main() -> None:
    """Run Bronze acquisition from the command line."""

    args = parse_args()
    run_bronze(args.datasets)


if __name__ == "__main__":
    main()
