"""Acquire the Northeast BC Geological Carbon Capture and Storage Atlas.

The source dataset is Geoscience BC Report 2023-04, prepared by
Canadian Discovery Ltd. for Geoscience BC. The digital atlas products used
by the CANCO2-Storage workflow consist of:

- Appendix C — Pool Storage Database & Aquifer Storage Summary
- Appendix E — Additional Maps and Shapefiles

This module performs Bronze-layer acquisition only:

- download the official Appendix C workbook,
- download the official Appendix E ZIP archive,
- extract Appendix E while preserving the provider directory structure,
- validate the downloaded workbook and extracted shapefile datasets,
- calculate SHA-256 checksums for the retained source artifacts,
- return paths required by downstream harmonization.

It does not rename source fields, classify geological layers, reconcile
Appendix C and Appendix E records, reproject geometries, modify source
attributes, infer storage properties, or construct Silver-layer products.

Source
------
Geoscience BC Report 2023-04.

Northeast BC Geological Carbon Capture and Storage Atlas.

Prepared by Canadian Discovery Ltd. for Geoscience BC.
"""

from __future__ import annotations

import argparse
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

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
RAW_GBC_NE_ATLAS = RAW_STORAGE / "gbc_ne_atlas"


# =============================================================================
# Source definition
# =============================================================================

DATASET_ID = "gbc_ne_atlas"

SOURCE_ORGANIZATION = "Geoscience BC"
SOURCE_PREPARER = "Canadian Discovery Ltd."

SOURCE_TITLE = (
    "Northeast BC Geological Carbon Capture and Storage Atlas"
)

SOURCE_PUBLICATION = "Geoscience BC Report 2023-04"
SOURCE_YEAR = 2023

SOURCE_PROJECT_URL = (
    "https://www.geosciencebc.com/projects/2022-001/"
)

SOURCE_PARENT_URL = (
    "https://www2.gov.bc.ca/gov/content/industry/"
    "natural-gas-oil/responsible-oil-gas-development/"
    "carbon-capture-storage/geological-potential"
)

APPENDIX_C_URL = (
    "https://www.geosciencebc.com/i/project_data/"
    "GBCReport2023-04/"
    "Appendix%20C%20-%20Pool%20Storage%20Database%20%26%20"
    "Aquifer%20Storage%20Summary.xlsx"
)

APPENDIX_E_URL = (
    "https://www.geosciencebc.com/i/project_data/"
    "GBCReport2023-04/"
    "APPENDIX%20E%20-%20ADDITIONAL%20MAPS%20AND%20SHAPEFILES.zip"
)

APPENDIX_C_NAME = (
    "Appendix C - Pool Storage Database & Aquifer Storage Summary.xlsx"
)

APPENDIX_E_ARCHIVE_NAME = (
    "APPENDIX E - ADDITIONAL MAPS AND SHAPEFILES.zip"
)


# =============================================================================
# Acquisition result
# =============================================================================


@dataclass(frozen=True)
class BCNEAtlasAcquisitionResult:
    """Validated Bronze products from Geoscience BC Report 2023-04."""

    raw_dir: Path

    appendix_c_path: Path
    appendix_c_sha256: str
    appendix_c_sheets: tuple[str, ...]

    appendix_e_archive_path: Path
    appendix_e_archive_sha256: str

    extraction_dir: Path
    source_directories: tuple[Path, ...]
    shapefiles: tuple[Path, ...]
    source_files: tuple[Path, ...]




# =============================================================================
# Structural validation requirements
# =============================================================================


REQUIRED_SHAPEFILE_SIDECARS: tuple[str, ...] = (
    ".shx",
    ".dbf",
    ".prj",
)


# =============================================================================
# Validation helpers
# =============================================================================


def validate_appendix_c(path: Path) -> tuple[str, ...]:
    """Validate that Appendix C is a readable Excel workbook."""

    if not path.is_file():
        raise FileNotFoundError(
            f"Appendix C workbook not found: {path}"
        )

    workbook = pd.ExcelFile(path, engine="openpyxl")

    sheet_names = tuple(
        str(sheet_name)
        for sheet_name in workbook.sheet_names
    )

    if not sheet_names:
        raise ValueError(
            f"Appendix C workbook contains no worksheets: {path}"
        )

    return sheet_names


def validate_shapefile(path: Path) -> None:
    """Validate required components of one Appendix E shapefile."""

    if not path.is_file():
        raise FileNotFoundError(
            f"Shapefile not found: {path}"
        )

    missing = [
        suffix
        for suffix in REQUIRED_SHAPEFILE_SIDECARS
        if not path.with_suffix(suffix).is_file()
    ]

    if missing:
        raise FileNotFoundError(
            f"Missing required sidecar file(s) for {path.name}: "
            f"{missing}"
        )


def validate_appendix_e(
    extraction_dir: Path,
) -> tuple[
    tuple[Path, ...],
    tuple[Path, ...],
    tuple[Path, ...],
]:
    """Validate and inventory the extracted Appendix E source archive."""

    if not extraction_dir.is_dir():
        raise FileNotFoundError(
            f"Appendix E extraction directory not found: {extraction_dir}"
        )

    source_directories = tuple(
        sorted(
            path
            for path in extraction_dir.rglob("*")
            if path.is_dir()
        )
    )

    shapefiles = tuple(
        sorted(extraction_dir.rglob("*.shp"))
    )

    if not shapefiles:
        raise FileNotFoundError(
            "No shapefiles were found in the extracted Appendix E dataset."
        )

    for shapefile in shapefiles:
        validate_shapefile(shapefile)

    source_files = tuple(
        sorted(
            path
            for path in extraction_dir.rglob("*")
            if path.is_file()
        )
    )

    if not source_files:
        raise FileNotFoundError(
            f"No source files found under {extraction_dir}."
        )

    return source_directories, shapefiles, source_files

# =============================================================================
# Acquisition workflow
# =============================================================================


def acquire(
    raw_dir: Path = RAW_GBC_NE_ATLAS,
    *,
    overwrite: bool = False,
) -> BCNEAtlasAcquisitionResult:
    """Acquire and validate Geoscience BC Report 2023-04 source data."""

    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    appendix_c_path = raw_dir / APPENDIX_C_NAME
    appendix_e_archive_path = raw_dir / APPENDIX_E_ARCHIVE_NAME
    extraction_dir = raw_dir / "source"

    print("Acquiring Northeast BC Geological Carbon Capture and Storage Atlas...\n")
    print(f"Dataset:       {DATASET_ID}")
    print(f"Organization:  {SOURCE_ORGANIZATION}")
    print(f"Prepared by:   {SOURCE_PREPARER}")
    print(f"Publication:   {SOURCE_PUBLICATION}")
    print(f"Project page:  {SOURCE_PROJECT_URL}")
    print(f"Parent page:   {SOURCE_PARENT_URL}")
    print(f"Appendix C:    {APPENDIX_C_URL}")
    print(f"Appendix E:    {APPENDIX_E_URL}")
    print(f"Raw folder:    {raw_dir}\n")

    # -------------------------------------------------------------------------
    # Appendix C
    # -------------------------------------------------------------------------

    downloaded_appendix_c = download_file(
        url=APPENDIX_C_URL,
        destination=appendix_c_path,
        overwrite=overwrite,
    )

    appendix_c_sheets = validate_appendix_c(
        downloaded_appendix_c
    )

    appendix_c_hash = sha256_file(
        downloaded_appendix_c
    )

    # -------------------------------------------------------------------------
    # Appendix E
    # -------------------------------------------------------------------------

    downloaded_appendix_e = download_file(
        url=APPENDIX_E_URL,
        destination=appendix_e_archive_path,
        overwrite=overwrite,
    )

    if not zipfile.is_zipfile(downloaded_appendix_e):
        raise ValueError(
            "Downloaded Appendix E dataset is not a valid ZIP archive. "
            "The configured Geoscience BC resource may have changed or "
            f"returned non-binary content: {downloaded_appendix_e}"
        )

    appendix_e_hash = sha256_file(
        downloaded_appendix_e
    )

    extract_zip(
        zip_path=downloaded_appendix_e,
        output_dir=extraction_dir,
        overwrite=overwrite,
    )

    source_directories, shapefiles, source_files = validate_appendix_e(
        extraction_dir
    )

    # -------------------------------------------------------------------------
    # Acquisition result
    # -------------------------------------------------------------------------

    result = BCNEAtlasAcquisitionResult(
        raw_dir=raw_dir,
        appendix_c_path=downloaded_appendix_c,
        appendix_c_sha256=appendix_c_hash,
        appendix_c_sheets=appendix_c_sheets,
        appendix_e_archive_path=downloaded_appendix_e,
        appendix_e_archive_sha256=appendix_e_hash,
        extraction_dir=extraction_dir,
        source_directories=source_directories,
        shapefiles=shapefiles,
        source_files=source_files,
    )

    print_summary(result)

    return result


# =============================================================================
# Console summary
# =============================================================================


def print_summary(
    result: BCNEAtlasAcquisitionResult,
) -> None:
    """Print a concise Northeast BC atlas acquisition summary."""

    print("\nNortheast BC atlas acquisition summary")
    print("--------------------------------------")

    print(f"Appendix C:      {result.appendix_c_path.name}")
    print(f"Appendix C SHA:  {result.appendix_c_sha256}")
    print(f"Workbook sheets: {len(result.appendix_c_sheets)}")

    print("\nAppendix C worksheets:")
    for sheet_name in result.appendix_c_sheets:
        print(f"- {sheet_name}")

    print(f"\nAppendix E:      {result.appendix_e_archive_path.name}")
    print(f"Appendix E SHA:  {result.appendix_e_archive_sha256}")

    print(f"Directories:     {len(result.source_directories)}")
    print(f"Shapefiles:      {len(result.shapefiles)}")
    print(f"Source files:    {len(result.source_files)}")

    print("\nAppendix E directory structure:")

    for directory in result.source_directories:
        relative_path = directory.relative_to(
            result.extraction_dir
        )
        print(f"- {relative_path}")


# =============================================================================
# CLI
# =============================================================================


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Download, extract, and validate the Northeast BC Geological "
            "Carbon Capture and Storage Atlas source data."
        )
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help=(
            "Redownload and re-extract the source datasets even when "
            "existing files are present."
        ),
    )

    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=RAW_GBC_NE_ATLAS,
        help=(
            "Bronze output directory. "
            "Defaults to data/raw/gbc_ne_atlas."
        ),
    )

    return parser.parse_args()


def main() -> None:
    """Run the Northeast BC atlas Bronze acquisition workflow."""

    args = parse_args()

    acquire(
        raw_dir=args.raw_dir,
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    main()
