"""Acquire the Statistics Canada 2021 digital province/territory boundary file.

This module performs Bronze-layer acquisition only for the Statistics Canada
2021 Census digital boundary file used by the CANCO2-Storage unified atlas.

The workflow:

- downloads the official Statistics Canada ZIP archive;
- validates that the download is a ZIP file;
- calculates the archive SHA-256 checksum;
- extracts the provider files without altering their contents;
- places the shapefile and associated sidecars directly under
  ``data/raw/basemaps/digital``;
- validates the required shapefile components; and
- returns the validated Bronze paths required by downstream harmonization.

It does not reproject, simplify, clip, rename source fields, or otherwise
transform the provider dataset.

Source
------
Statistics Canada, 2021 Census of Population.
Digital boundary file — provinces and territories.

Official archive:
https://www12.statcan.gc.ca/census-recensement/2021/geo/sip-pis/
boundary-limites/files-fichiers/lpr_000a21a_e.zip
"""

from __future__ import annotations

import argparse
import shutil
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

RAW_BASEMAPS = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "basemaps"
)

RAW_DIGITAL_BASEMAP = RAW_BASEMAPS / "digital"


# =============================================================================
# Source definition
# =============================================================================

DATASET_ID = "statcan_2021_digital_province_boundaries"

SOURCE_ORGANIZATION = "Statistics Canada"

SOURCE_TITLE = (
    "2021 Census Digital Boundary File - Provinces and Territories"
)

SOURCE_YEAR = 2021

SOURCE_PAGE_URL = (
    "https://www12.statcan.gc.ca/census-recensement/2021/geo/"
    "sip-pis/boundary-limites/index-eng.cfm"
)

# Statistics Canada browser redirect / alternative-download endpoint.
ARCHIVE_FRONTEND_URL = (
    "https://www12.statcan.gc.ca/census-recensement/alternative_alternatif.cfm"
    "?l=eng&dispext=zip&teng=lpr_000a21a_e.zip&k=%20%20%20%20%202712"
    "&loc=//www12.statcan.gc.ca/census-recensement/2021/geo/sip-pis/"
    "boundary-limites/files-fichiers/lpr_000a21a_e.zip"
)

# Direct binary download used by the acquisition workflow.
ARCHIVE_URL = (
    "https://www12.statcan.gc.ca/census-recensement/2021/geo/"
    "sip-pis/boundary-limites/files-fichiers/lpr_000a21a_e.zip"
)

ARCHIVE_NAME = "lpr_000a21a_e.zip"
EXPECTED_STEM = "lpr_000a21a_e"
EXPECTED_SHAPEFILE = f"{EXPECTED_STEM}.shp"

# These files are required for a complete ESRI Shapefile dataset.
REQUIRED_SIDECAR_SUFFIXES = (
    ".dbf",
    ".shx",
    ".prj",
)

# Provider archives may also contain these files. They are retained when present,
# but their absence does not make the spatial dataset unusable.
OPTIONAL_SIDECAR_SUFFIXES = (
    ".cpg",
    ".xml",
    ".sbn",
    ".sbx",
)


# =============================================================================
# Acquisition result
# =============================================================================


@dataclass(frozen=True)
class DigitalBoundaryAcquisitionResult:
    """Validated Bronze products from the Statistics Canada boundary archive."""

    raw_dir: Path
    shapefile_path: Path
    sidecar_paths: tuple[Path, ...]
    archive_sha256: str
    source_files: tuple[Path, ...]


# =============================================================================
# Validation and file organization
# =============================================================================


def expected_required_paths(raw_dir: Path) -> tuple[Path, ...]:
    """Return the required shapefile component paths for the Bronze dataset."""

    shapefile = raw_dir / EXPECTED_SHAPEFILE

    return (
        shapefile,
        *(
            shapefile.with_suffix(suffix)
            for suffix in REQUIRED_SIDECAR_SUFFIXES
        ),
    )


def validate_dataset_outputs(
    raw_dir: Path,
) -> tuple[Path, tuple[Path, ...], tuple[Path, ...]]:
    """Validate the extracted Statistics Canada digital boundary dataset.

    Parameters
    ----------
    raw_dir : pathlib.Path
        Bronze directory expected to contain the provider shapefile components.

    Returns
    -------
    tuple
        Validated shapefile path, associated sidecar paths, and all provider files
        sharing the expected basename.

    Raises
    ------
    FileNotFoundError
        If any required shapefile component is missing.
    ValueError
        If an unexpected additional shapefile is present in the Bronze directory.
    """

    required_paths = expected_required_paths(raw_dir)
    missing = [
        path
        for path in required_paths
        if not path.is_file()
    ]

    if missing:
        raise FileNotFoundError(
            "Statistics Canada digital boundary acquisition is incomplete. "
            "Missing required file(s): "
            + ", ".join(path.name for path in missing)
        )

    shapefiles = sorted(raw_dir.glob("*.shp"))

    unexpected_shapefiles = [
        path
        for path in shapefiles
        if path.name != EXPECTED_SHAPEFILE
    ]

    if unexpected_shapefiles:
        raise ValueError(
            "Unexpected additional shapefile(s) found in the digital basemap "
            f"directory: {[path.name for path in unexpected_shapefiles]}"
        )

    shapefile_path = raw_dir / EXPECTED_SHAPEFILE

    source_files = tuple(
        sorted(
            path
            for path in raw_dir.glob(f"{EXPECTED_STEM}.*")
            if path.is_file()
        )
    )

    sidecar_paths = tuple(
        path
        for path in source_files
        if path != shapefile_path
    )

    return (
        shapefile_path,
        sidecar_paths,
        source_files,
    )


def flatten_provider_files(
    extraction_dir: Path,
    raw_dir: Path,
    *,
    overwrite: bool,
) -> None:
    """Move provider files sharing the expected basename into ``raw_dir``.

    The Statistics Canada archive is expected to contain one shapefile dataset.
    This helper is deliberately restricted to files whose basename matches
    ``EXPECTED_STEM`` so unrelated archive content is not silently promoted into
    the Bronze directory.
    """

    matches = sorted(
        path
        for path in extraction_dir.rglob(f"{EXPECTED_STEM}.*")
        if path.is_file()
    )

    if not matches:
        raise FileNotFoundError(
            f"No files matching {EXPECTED_STEM}.* were found after extraction."
        )

    for source_path in matches:
        destination = raw_dir / source_path.name

        if destination.exists():
            if overwrite:
                destination.unlink()
            else:
                continue

        shutil.move(
            str(source_path),
            str(destination),
        )


# =============================================================================
# Acquisition workflow
# =============================================================================


def acquire_digital_boundaries(
    raw_dir: Path = RAW_DIGITAL_BASEMAP,
    *,
    overwrite: bool = False,
) -> DigitalBoundaryAcquisitionResult:
    """Acquire the Statistics Canada 2021 digital province boundary dataset.

    Existing validated Bronze outputs are reused unless ``overwrite`` is true.
    The ZIP archive is downloaded to the Bronze directory, extracted into a
    temporary child directory, flattened into the requested Bronze layout, and
    removed after successful validation.

    Parameters
    ----------
    raw_dir : pathlib.Path, default=RAW_DIGITAL_BASEMAP
        Destination directory for the provider shapefile and sidecars.
    overwrite : bool, default=False
        Whether existing Bronze files should be replaced.

    Returns
    -------
    DigitalBoundaryAcquisitionResult
        Paths and provenance information for the validated Bronze dataset.
    """

    raw_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not overwrite:
        try:
            (
                shapefile_path,
                sidecar_paths,
                source_files,
            ) = validate_dataset_outputs(raw_dir)

            print(
                "[Reuse] Valid Statistics Canada digital boundary dataset "
                f"already exists at {raw_dir}"
            )

            return DigitalBoundaryAcquisitionResult(
                raw_dir=raw_dir,
                shapefile_path=shapefile_path,
                sidecar_paths=sidecar_paths,
                archive_sha256="not_recomputed_existing_outputs",
                source_files=source_files,
            )

        except FileNotFoundError:
            pass

    print("Acquiring Statistics Canada 2021 digital boundary file...\n")
    print(f"Dataset:       {DATASET_ID}")
    print(f"Organization:  {SOURCE_ORGANIZATION}")
    print(f"Source title:  {SOURCE_TITLE}")
    print(f"Source page:   {SOURCE_PAGE_URL}")
    print(f"Archive URL:   {ARCHIVE_URL}")
    print(f"Raw folder:    {raw_dir}\n")

    archive_path = raw_dir / ARCHIVE_NAME

    downloaded_archive = download_file(
        url=ARCHIVE_URL,
        destination=archive_path,
        overwrite=overwrite,
    )

    if not zipfile.is_zipfile(downloaded_archive):
        raise ValueError(
            "Downloaded Statistics Canada boundary dataset is not a valid ZIP "
            f"archive: {downloaded_archive}"
        )

    archive_hash = sha256_file(
        downloaded_archive
    )

    extraction_dir = raw_dir / "_extract"

    extract_zip(
        zip_path=downloaded_archive,
        output_dir=extraction_dir,
        overwrite=True,
    )

    flatten_provider_files(
        extraction_dir,
        raw_dir,
        overwrite=overwrite,
    )

    (
        shapefile_path,
        sidecar_paths,
        source_files,
    ) = validate_dataset_outputs(raw_dir)

    shutil.rmtree(
        extraction_dir,
        ignore_errors=True,
    )

    downloaded_archive.unlink(
        missing_ok=True
    )

    result = DigitalBoundaryAcquisitionResult(
        raw_dir=raw_dir,
        shapefile_path=shapefile_path,
        sidecar_paths=sidecar_paths,
        archive_sha256=archive_hash,
        source_files=source_files,
    )

    print("\nStatistics Canada digital boundary acquisition complete.")
    print(f"Shapefile:     {result.shapefile_path}")
    print(f"Source files:  {len(result.source_files)}")
    print(f"Archive SHA256:{result.archive_sha256}")

    return result


# =============================================================================
# CLI
# =============================================================================


def parse_args() -> argparse.Namespace:
    """Parse command-line options for Bronze boundary acquisition."""

    parser = argparse.ArgumentParser(
        description=(
            "Acquire the Statistics Canada 2021 digital province and territory "
            "boundary shapefile."
        )
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Redownload and replace existing Bronze boundary files.",
    )

    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=RAW_DIGITAL_BASEMAP,
        help=(
            "Destination directory for the extracted provider files. Defaults "
            "to data/raw/basemaps/digital."
        ),
    )

    return parser.parse_args()


def main() -> None:
    """Run Statistics Canada digital-boundary Bronze acquisition."""

    args = parse_args()

    acquire_digital_boundaries(
        raw_dir=args.raw_dir.resolve(),
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    main()
