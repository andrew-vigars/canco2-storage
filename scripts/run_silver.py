"""CLI wrapper for CANCO2-Storage Silver package construction."""

from __future__ import annotations

import argparse

from canco2_storage.orchestration.silver import (
    SILVER_WORKFLOWS,
    run_silver,
)


def parse_args() -> argparse.Namespace:
    """Parse Silver build command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Build CANCO2-Storage independent Silver dataset packages. "
            "By default, all registered Silver workflows run."
        )
    )

    parser.add_argument(
        "--dataset",
        action="append",
        choices=tuple(SILVER_WORKFLOWS),
        dest="datasets",
        help=(
            "Build only the selected Silver dataset. May be supplied multiple "
            "times. If omitted, all registered Silver workflows run."
        ),
    )

    return parser.parse_args()


def main() -> None:
    """Run the Silver build workflow."""

    args = parse_args()
    run_silver(datasets=args.datasets)


if __name__ == "__main__":
    main()
