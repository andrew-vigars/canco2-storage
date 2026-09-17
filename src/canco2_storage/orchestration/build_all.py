"""Complete CANCO2-Storage build orchestration."""

from __future__ import annotations

import argparse
from pathlib import Path

from canco2_storage.orchestration.geopackages import (
    BRONZE_DATASETS,
    build_geopackages,
)
from canco2_storage.orchestration.unified import build_unified


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the complete build."""

    parser = argparse.ArgumentParser(
        description="Build all CANCO2-Storage GeoPackages and the unified atlas."
    )
    parser.add_argument("--datasets", nargs="+", choices=BRONZE_DATASETS)
    parser.add_argument("--skip-bronze", action="store_true")
    parser.add_argument("--skip-silver", action="store_true")
    parser.add_argument("--project-root", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    """Run the GeoPackage build followed by the unified atlas build."""

    args = parse_args()
    build_geopackages(
        datasets=args.datasets,
        run_bronze_layer=not args.skip_bronze,
        run_silver_layer=not args.skip_silver,
    )
    build_unified(project_root=args.project_root, output=args.output)


if __name__ == "__main__":
    main()