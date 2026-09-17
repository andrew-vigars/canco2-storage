"""Unified atlas build orchestration for CANCO2-Storage."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


HARMONIZE_MODULE = "canco2_storage.harmonize.unified_atlas"
METADATA_MODULE = "canco2_storage.metadata.unified_atlas"


def run_module(module_name: str, arguments: list[str] | None = None) -> None:
    """Run one unified-atlas module in the active Python environment."""

    command = [sys.executable, "-m", module_name]
    if arguments:
        command.extend(arguments)
    subprocess.run(command, check=True)


def build_unified(
    *,
    project_root: Path | None = None,
    output: Path | None = None,
    validate_existing: Path | None = None,
) -> None:
    """Build the unified atlas and render its companion README."""

    if validate_existing is not None and (project_root is not None or output is not None):
        raise ValueError(
            "--validate-existing cannot be combined with --project-root or --output."
        )

    harmonize_arguments: list[str] = []
    if project_root is not None:
        harmonize_arguments.extend(["--project-root", str(project_root)])
    if output is not None:
        harmonize_arguments.extend(["--output", str(output)])
    if validate_existing is not None:
        harmonize_arguments.extend(["--validate-existing", str(validate_existing)])

    print("CANCO2-Storage unified atlas build")
    print("---------------------------------")
    run_module(HARMONIZE_MODULE, harmonize_arguments)

    if validate_existing is None:
        metadata_arguments = [] if output is None else ["--gpkg", str(output)]
        run_module(METADATA_MODULE, metadata_arguments)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for unified atlas orchestration."""

    parser = argparse.ArgumentParser(
        description="Build the unified CANCO2-Storage atlas and its README."
    )
    parser.add_argument("--project-root", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--validate-existing", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    """Build the unified atlas from the command line."""

    args = parse_args()
    build_unified(
        project_root=args.project_root,
        output=args.output,
        validate_existing=args.validate_existing,
    )


if __name__ == "__main__":
    main()