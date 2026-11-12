"""Acquire the Statistics Canada 2021 cartographic province boundaries.

This module performs Bronze-layer acquisition only for the Statistics Canada
2021 Census cartographic province/territory boundary file used to render
CANCO2-Storage documentation previews and README maps.

The workflow:

- records Statistics Canada as the authoritative upstream source;
- downloads the Data for Canada archive hosted by Source Cooperative because
  Cloudflare challenges automated clients on the upstream host;
- validates that the download is a ZIP file;
- calculates the archive SHA-256 checksum;
- extracts the provider files without altering their contents;
- places the shapefile and associated sidecars directly under
  ``data/raw/basemaps/cartographic``; and
- validates the required shapefile components.

It does not reproject, simplify, clip, rename source fields, or otherwise
transform the provider dataset. The cartographic boundaries are a
documentation-only basemap and must not replace the digital boundaries used by
the analytical mapping workflow.

Source
------
Statistics Canada, 2021 Census of Population.
Cartographic boundary file — provinces and territories.

Official archive:
https://www12.statcan.gc.ca/census-recensement/2021/geo/sip-pis/
boundary-limites/files-fichiers/lpr_000b21a_e.zip

Download mirror:
https://data.source.coop/dataforcanada/d4c-datapkg-statistical/archive/
statcan/boundaries/2021/lpr_000b21a_e.zip
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

RAW_BASEMAPS = PROJECT_ROOT / "data" / "raw" / "basemaps"

RAW_CARTOGRAPHIC_BASEMAP = RAW_BASEMAPS / "cartographic"


# =============================================================================
# Source definition
# =============================================================================

DATASET_ID = "statcan_2021_cartographic_province_boundaries"

SOURCE_ORGANIZATION = "Statistics Canada"

SOURCE_TITLE = (
    "2021 Census Cartographic Boundary File - Provinces and Territories"
)

SOURCE_YEAR = 2021

SOURCE_PAGE_URL = (
    "https://www12.statcan.gc.ca/census-recensement/2021/geo/"
    "sip-pis/boundary-limites/index-eng.cfm"
)

# Statistics Canada browser redirect / alternative-download endpoint. This is
# retained for provenance; it resolves to ARCHIVE_UPSTREAM_URL and is not a
# second source archive.
ARCHIVE_FRONTEND_URL = (
    "https://www12.statcan.gc.ca/census-recensement/alternative_alternatif.cfm"
    "?l=eng&dispext=zip&teng=lpr_000b21a_e.zip&k=%20%20%20130596"
    "&loc=//www12.statcan.gc.ca/census-recensement/2021/geo/sip-pis/"
    "boundary-limites/files-fichiers/lpr_000b21a_e.zip"
)

# Authoritative upstream resource. Cloudflare currently challenges automated
# clients, so the acquisition workflow records this URL but downloads the Data
# for Canada archived copy from Source Cooperative below.
ARCHIVE_UPSTREAM_URL = (
    "https://www12.statcan.gc.ca/census-recensement/2021/geo/"
    "sip-pis/boundary-limites/files-fichiers/lpr_000b21a_e.zip"
)

ARCHIVE_URL = (
    "https://data.source.coop/dataforcanada/d4c-datapkg-statistical/"
    "archive/statcan/boundaries/2021/lpr_000b21a_e.zip"
)

ARCHIVE_NAME = "lpr_000b21a_e.zip"
EXPECTED_STEM = "lpr_000b21a_e"
EXPECTED_SHAPEFILE = f"{EXPECTED_STEM}.shp"

REQUIRED_SIDECAR_SUFFIXES = (
    ".dbf",
    ".shx",
    ".prj",
)

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
class CartographicBoundaryAcquisitionResult:
    """Validated Bronze products from the cartographic boundary archive."""

    raw_dir: Path
    shapefile_path: Path
    sidecar_paths: tuple[Path, ...]
    archive_sha256: str
    source_files: tuple[Path, ...]


# =============================================================================
# Validation and file organization
# =============================================================================


def expected_required_paths(raw_dir: Path) -> tuple[Path, ...]:
    """Return required shapefile component paths for the Bronze dataset."""

    shapefile = raw_dir / EXPECTED_SHAPEFILE
    return (
        shapefile,
        *(shapefile.with_suffix(suffix) for suffix in REQUIRED_SIDECAR_SUFFIXES),
    )


def validate_dataset_outputs(
    raw_dir: Path,
) -> tuple[Path, tuple[Path, ...], tuple[Path, ...]]:
    """Validate the extracted cartographic province boundary dataset."""

    required_paths = expected_required_paths(raw_dir)
    missing = [path for path in required_paths if not path.is_file()]

    if missing:
        raise FileNotFoundError(
            "Statistics Canada cartographic boundary acquisition is incomplete. "
            "Missing required file(s): "
            + ", ".join(path.name for path in missing)
        )

    shapefiles = sorted(raw_dir.glob("*.shp"))
    unexpected_shapefiles = [
        path for path in shapefiles if path.name != EXPECTED_SHAPEFILE
    ]

    if unexpected_shapefiles:
        raise ValueError(
            "Unexpected additional shapefile(s) found in the cartographic "
            "basemap directory: "
            f"{[path.name for path in unexpected_shapefiles]}"
        )

    shapefile_path = raw_dir / EXPECTED_SHAPEFILE
    source_files = tuple(
        sorted(
            path
            for path in raw_dir.glob(f"{EXPECTED_STEM}.*")
            if path.is_file() and path.name != ARCHIVE_NAME
        )
    )
    sidecar_paths = tuple(
        path for path in source_files if path != shapefile_path
    )

    return shapefile_path, sidecar_paths, source_files


def flatten_provider_files(
    extraction_dir: Path,
    raw_dir: Path,
    *,
    overwrite: bool,
) -> None:
    """Move expected provider files into the cartographic Bronze directory."""

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

        shutil.move(str(source_path), str(destination))


# =============================================================================
# Acquisition workflow
# =============================================================================


def acquire_cartographic_boundaries(
    raw_dir: Path = RAW_CARTOGRAPHIC_BASEMAP,
    *,
    overwrite: bool = False,
) -> CartographicBoundaryAcquisitionResult:
    """Acquire the 2021 cartographic province/territory boundary dataset."""

    raw_dir.mkdir(parents=True, exist_ok=True)

    if not overwrite:
        try:
            shapefile_path, sidecar_paths, source_files = (
                validate_dataset_outputs(raw_dir)
            )

            print(
                "[Reuse] Valid Statistics Canada cartographic boundary dataset "
                f"already exists at {raw_dir}"
            )

            return CartographicBoundaryAcquisitionResult(
                raw_dir=raw_dir,
                shapefile_path=shapefile_path,
                sidecar_paths=sidecar_paths,
                archive_sha256="not_recomputed_existing_outputs",
                source_files=source_files,
            )
        except FileNotFoundError:
            pass

    print("Acquiring Statistics Canada 2021 cartographic boundary file...\n")
    print(f"Dataset:       {DATASET_ID}")
    print(f"Organization:  {SOURCE_ORGANIZATION}")
    print(f"Source title:  {SOURCE_TITLE}")
    print(f"Source page:   {SOURCE_PAGE_URL}")
    print(f"Upstream URL:  {ARCHIVE_UPSTREAM_URL}")
    print(f"Download URL:  {ARCHIVE_URL}")
    print(f"Raw folder:    {raw_dir}\n")

    archive_path = raw_dir / ARCHIVE_NAME
    downloaded_archive = download_file(
        url=ARCHIVE_URL,
        destination=archive_path,
        overwrite=overwrite,
    )

    if not zipfile.is_zipfile(downloaded_archive):
        raise ValueError(
            "Downloaded Statistics Canada cartographic boundary dataset is not "
            f"a valid ZIP archive: {downloaded_archive}"
        )

    archive_hash = sha256_file(downloaded_archive)
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

    shapefile_path, sidecar_paths, source_files = validate_dataset_outputs(raw_dir)

    shutil.rmtree(extraction_dir, ignore_errors=True)
    downloaded_archive.unlink(missing_ok=True)

    result = CartographicBoundaryAcquisitionResult(
        raw_dir=raw_dir,
        shapefile_path=shapefile_path,
        sidecar_paths=sidecar_paths,
        archive_sha256=archive_hash,
        source_files=source_files,
    )

    print("\nStatistics Canada cartographic boundary acquisition complete.")
    print(f"Shapefile:      {result.shapefile_path}")
    print(f"Source files:   {len(result.source_files)}")
    print(f"Archive SHA256: {result.archive_sha256}")

    return result


# =============================================================================
# CLI
# =============================================================================


def parse_args() -> argparse.Namespace:
    """Parse command-line options for Bronze boundary acquisition."""

    parser = argparse.ArgumentParser(
        description=(
            "Acquire the Statistics Canada 2021 cartographic province and "
            "territory boundary shapefile for documentation previews."
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
        default=RAW_CARTOGRAPHIC_BASEMAP,
        help=(
            "Destination directory for the extracted provider files. Defaults "
            "to data/raw/basemaps/cartographic."
        ),
    )
    return parser.parse_args()


def main() -> None:
    """Run Statistics Canada cartographic-boundary Bronze acquisition."""

    args = parse_args()
    acquire_cartographic_boundaries(
        raw_dir=args.raw_dir.resolve(),
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    main()
