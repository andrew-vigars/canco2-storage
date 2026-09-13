"""CLI wrapper for CANCO2-Storage Bronze acquisition."""

from __future__ import annotations

import argparse

from canco2_storage.orchestration.bronze import (
    ACQUISITION_MODULES,
    run_bronze,
)


def parse_args() -> argparse.Namespace:
    """Parse Bronze acquisition command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Run CANCO2-Storage Bronze acquisition workflows. "
            "By default, all registered datasets are acquired."
        )
    )

    parser.add_argument(
        "--dataset",
        action="append",
        choices=tuple(ACQUISITION_MODULES),
        dest="datasets",
        help=(
            "Run only the selected dataset. May be supplied multiple times. "
            "If omitted, all registered acquisition workflows run."
        ),
    )

    return parser.parse_args()


def main() -> None:
    """Run the Bronze acquisition workflow."""

    args = parse_args()
    run_bronze(datasets=args.datasets)


if __name__ == "__main__":
    main()
