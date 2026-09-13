"""
Acquire Geological Survey of Canada Open File 8996.

The source dataset contains regional geological CO2 storage Chance of Success
(COS) mapping for Atlantic Canada.

This module performs Bronze-layer acquisition only:

- download the official GSC dataset archive,
- extract the archive while preserving source structure,
- validate the expected source products,
- return paths required by downstream harmonization.

It does not rename source fields, harmonize schemas, calculate COS values,
reproject geometries, or construct Silver-layer products.

Source
------
Carey, J.S., Skinner, C.H., Giles, P.S., Durling, P., Plourde, A.P.,
Jauer, C., and Desroches, K. (2023).
Preliminary assessment of geological carbon-storage potential of Atlantic
Canada. Geological Survey of Canada, Open File 8996.

DOI
---
10.4095/332145
"""

from __future__ import annotations

import argparse
import zipfile
from dataclasses import dataclass
from pathlib import Path

from canco2_storage.acquisition.common import (
    download_file,
    extract_zip,
    sha256_file,
)
from canco2_storage.paths import find_project_root


# =============================================================================
# Project paths
# =============================================================================

PROJECT_ROOT = find_project_root()

RAW_STORAGE = PROJECT_ROOT / "data" / "raw"
RAW_GSC_ATLANTIC = RAW_STORAGE / "gsc_atlantic"


# =============================================================================
# Source definition
# =============================================================================

DATASET_ID = "gsc_atlantic"

SOURCE_TITLE = (
    "Preliminary assessment of geological carbon-storage potential "
    "of Atlantic Canada"
)

SOURCE_PUBLICATION = "Geological Survey of Canada Open File 8996"
SOURCE_YEAR = 2023
SOURCE_DOI = "10.4095/332145"

PUBLICATION_URL = (
    "https://ostrnrcan-dostrncan.canada.ca/entities/publication/"
    "b6140ab8-c5fd-4ad2-b9ed-65c32ff2bb17"
)

# The public OSTR Angular route below is useful for provenance and browser access,
# but a plain requests.get() call returns the OSTR HTML application rather than
# the ZIP payload.
ARCHIVE_FRONTEND_URL = (
    "https://ostrnrcan-dostrncan.canada.ca/bitstreams/"
    "5a707088-2799-4c70-94c3-656f80256612/download"
)

# OSTR is backed by DSpace. Binary bitstream content is served by the NRCan OSTR
# backend through the DSpace REST content endpoint.
ARCHIVE_URL = (
    "https://ostr-backend-prod.azure.cloud.nrcan-rncan.gc.ca/"
    "server/api/core/bitstreams/"
    "5a707088-2799-4c70-94c3-656f80256612/content"
)
ARCHIVE_NAME = "of_8996.zip"

EXPECTED_README_NAME = "of_8996_readme.rtf"

EXPECTED_GROUPS = (
    "Mesozoic-Cenozoic COS Mapping",
    "Upper Paleozoic COS Mapping",
)

EXPECTED_SHAPEFILE_COUNT = 15


# =============================================================================
# Acquisition result
# =============================================================================


@dataclass(frozen=True)
class AtlanticAcquisitionResult:
    """Validated Bronze products from GSC Open File 8996."""

    raw_dir: Path
    archive_path: Path
    archive_sha256: str
    extraction_dir: Path
    readme_path: Path
    mesozoic_cenozoic_dir: Path
    upper_paleozoic_dir: Path
    shapefiles: tuple[Path, ...]


# =============================================================================
# Validation helpers
# =============================================================================


def find_unique_path(
    root: Path,
    name: str,
    *,
    expect_directory: bool,
) -> Path:
    """Find exactly one source path with the requested name.

    Recursive discovery allows validation to tolerate a provider-supplied
    top-level archive directory while still preserving the original hierarchy.
    """

    matches = [
        path
        for path in root.rglob(name)
        if path.is_dir() == expect_directory
    ]

    if not matches:
        kind = "directory" if expect_directory else "file"
        raise FileNotFoundError(
            f"Expected {kind} not found under {root}: {name}"
        )

    if len(matches) > 1:
        raise ValueError(
            f"Expected exactly one path named {name!r}, "
            f"found {len(matches)}: {matches}"
        )

    return matches[0]


def validate_shapefile(path: Path) -> None:
    """Validate required sidecar files for one source shapefile."""

    if not path.is_file():
        raise FileNotFoundError(f"Shapefile not found: {path}")

    required_sidecars = (
        ".shx",
        ".dbf",
        ".prj",
    )

    missing = [
        suffix
        for suffix in required_sidecars
        if not path.with_suffix(suffix).is_file()
    ]

    if missing:
        raise FileNotFoundError(
            f"Missing required sidecar file(s) for {path.name}: "
            f"{missing}"
        )


def validate_dataset_outputs(
    extraction_dir: Path,
) -> tuple[
    Path,
    Path,
    Path,
    tuple[Path, ...],
]:
    """Validate the expected GSC Open File 8996 dataset products."""

    readme_path = find_unique_path(
        extraction_dir,
        EXPECTED_README_NAME,
        expect_directory=False,
    )

    mesozoic_dir = find_unique_path(
        extraction_dir,
        EXPECTED_GROUPS[0],
        expect_directory=True,
    )

    paleozoic_dir = find_unique_path(
        extraction_dir,
        EXPECTED_GROUPS[1],
        expect_directory=True,
    )

    shapefiles = tuple(
        sorted(
            [
                *mesozoic_dir.glob("*.shp"),
                *paleozoic_dir.glob("*.shp"),
            ]
        )
    )

    if len(shapefiles) != EXPECTED_SHAPEFILE_COUNT:
        raise ValueError(
            "Unexpected Open File 8996 shapefile count. "
            f"Expected {EXPECTED_SHAPEFILE_COUNT}, "
            f"found {len(shapefiles)}."
        )

    for shapefile in shapefiles:
        validate_shapefile(shapefile)

    return (
        readme_path,
        mesozoic_dir,
        paleozoic_dir,
        shapefiles,
    )


# =============================================================================
# Acquisition workflow
# =============================================================================


def acquire(
    raw_dir: Path = RAW_GSC_ATLANTIC,
    *,
    overwrite: bool = False,
) -> AtlanticAcquisitionResult:
    """Acquire and validate GSC Open File 8996.

    The original machine-readable dataset ZIP is retained after extraction
    so the exact source artifact can be hashed and audited.

    Parameters
    ----------
    raw_dir : Path, default=RAW_GSC_ATLANTIC
        Bronze directory used to store the source dataset files.
    overwrite : bool, default=False
        Whether to redownload and replace existing source files.

    Returns
    -------
    AtlanticAcquisitionResult
        Validated source paths and SHA-256 checksums.
    """

    raw_dir = Path(raw_dir)

    raw_dir.mkdir(parents=True, exist_ok=True)

    archive_path = raw_dir / ARCHIVE_NAME
    extraction_dir = raw_dir / "source"

    print("Acquiring GSC Atlantic Canada storage COS data...\n")
    print(f"Dataset:          {DATASET_ID}")
    print(f"Publication:      {SOURCE_PUBLICATION}")
    print(f"Source page:      {PUBLICATION_URL}")
    print(f"Dataset frontend: {ARCHIVE_FRONTEND_URL}")
    print(f"Dataset API:      {ARCHIVE_URL}")
    print(f"Raw folder:       {raw_dir}\n")

    downloaded_archive = download_file(
        url=ARCHIVE_URL,
        destination=archive_path,
        overwrite=overwrite,
    )

    if not zipfile.is_zipfile(downloaded_archive):
        raise ValueError(
            "Downloaded GSC Open File 8996 dataset is not a valid ZIP archive. "
            "The configured OSTR backend resource may have changed or returned "
            f"non-binary content: {downloaded_archive}"
        )

    archive_hash = sha256_file(downloaded_archive)

    extract_zip(
        zip_path=downloaded_archive,
        output_dir=extraction_dir,
        overwrite=overwrite,
    )

    (
        readme_path,
        mesozoic_dir,
        paleozoic_dir,
        shapefiles,
    ) = validate_dataset_outputs(extraction_dir)

    result = AtlanticAcquisitionResult(
        raw_dir=raw_dir,
        archive_path=downloaded_archive,
        archive_sha256=archive_hash,
        extraction_dir=extraction_dir,
        readme_path=readme_path,
        mesozoic_cenozoic_dir=mesozoic_dir,
        upper_paleozoic_dir=paleozoic_dir,
        shapefiles=shapefiles,
    )

    print_summary(result)

    return result


# =============================================================================
# Console summary
# =============================================================================


def print_summary(result: AtlanticAcquisitionResult) -> None:
    """Print a concise acquisition summary."""

    print("\nGSC Atlantic acquisition summary")
    print("--------------------------------")

    print(f"Archive:       {result.archive_path.name}")
    print(f"Archive SHA:   {result.archive_sha256}")
    print(f"README:        {result.readme_path.name}")
    print(f"Shapefiles:    {len(result.shapefiles)}")

    print("\nGeological groups:")
    print(f"- {result.mesozoic_cenozoic_dir.name}")
    print(f"- {result.upper_paleozoic_dir.name}")


# =============================================================================
# CLI
# =============================================================================


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Download, extract, and validate Geological Survey of Canada "
            "Open File 8996."
        )
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help=(
            "Redownload and re-extract the source dataset even when "
            "existing files are present."
        ),
    )

    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=RAW_GSC_ATLANTIC,
        help=(
            "Bronze output directory. "
            "Defaults to data/raw/gsc_atlantic."
        ),
    )

    return parser.parse_args()


def main() -> None:
    """Run the GSC Atlantic Bronze acquisition workflow."""

    args = parse_args()

    acquire(
        raw_dir=args.raw_dir,
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    main()
