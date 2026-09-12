"""
Acquire Alberta Carbon Sequestration Agreement source data.

The source dataset represents regulatory / tenure boundaries associated with
carbon sequestration agreements in Alberta.

This module performs Bronze-layer acquisition only:

- download the official provider ZIP archive,
- extract the archive while preserving source structure,
- validate the expected shapefile dataset,
- calculate a SHA-256 checksum for the retained source archive,
- return paths required by downstream harmonization.

It does not rename source fields, harmonize schemas, reproject geometries,
dissolve agreement tracts, infer geological storage attributes, or construct
Silver-layer products.

Source
------
Alberta Energy Regulator (AER), Carbon Sequestration Agreements.

Source page:
https://gis.energy.gov.ab.ca/Geoview/CarbonSequestration

Parent page:
https://www.alberta.ca/carbon-capture-utilization-and-storage-carbon-sequestration-tenure

Download:
https://gis.energy.gov.ab.ca/GeoviewData/CS_Agreements_Shape.zip

Source disclaimer
-----------------
The provider states that Carbon Sequestration Agreement boundaries are shown
to the full ATS Landkey and may therefore appear to include minerals not owned
by the Alberta Crown and/or minerals reserved from disposition. Detailed
permit and lease searches should be confirmed with Alberta Crown Land Data
Support.
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
RAW_AER_AGREEMENTS = RAW_STORAGE / "aer_agreements"


# =============================================================================
# Source definition
# =============================================================================

DATASET_ID = "aer_agreements"

SOURCE_ORGANIZATION = "Alberta Energy Regulator (AER)"
SOURCE_TITLE = "Carbon Sequestration Agreements"

SOURCE_PAGE_URL = (
    "https://gis.energy.gov.ab.ca/Geoview/CarbonSequestration"
)

SOURCE_PARENT_URL = (
    "https://www.alberta.ca/"
    "carbon-capture-utilization-and-storage-carbon-sequestration-tenure"
)

ARCHIVE_URL = (
    "https://gis.energy.gov.ab.ca/"
    "GeoviewData/CS_Agreements_Shape.zip"
)

ARCHIVE_NAME = "CS_Agreements_Shape.zip"

SOURCE_DISCLAIMER = (
    "Carbon Sequestration Agreement boundaries are shown to the full ATS "
    "Landkey and may therefore appear to include minerals not owned by the "
    "Alberta Crown and/or minerals reserved from disposition. Detailed permit "
    "and lease searches should be confirmed with Alberta Crown Land Data "
    "Support."
)

EXPECTED_SHAPEFILE_COUNT = 1

REQUIRED_SIDECARS = (
    ".shx",
    ".dbf",
    ".prj",
)


# =============================================================================
# Acquisition result
# =============================================================================


@dataclass(frozen=True)
class AERAgreementAcquisitionResult:
    """Validated Bronze products from the AER agreement archive."""

    raw_dir: Path
    archive_path: Path
    archive_sha256: str
    extraction_dir: Path
    shapefile_path: Path
    source_files: tuple[Path, ...]


# =============================================================================
# Validation helpers
# =============================================================================


def validate_shapefile(path: Path) -> tuple[Path, ...]:
    """Validate the required components of the provider shapefile dataset."""

    if not path.is_file():
        raise FileNotFoundError(f"Shapefile not found: {path}")

    missing = [
        suffix
        for suffix in REQUIRED_SIDECARS
        if not path.with_suffix(suffix).is_file()
    ]

    if missing:
        raise FileNotFoundError(
            f"Missing required sidecar file(s) for {path.name}: "
            f"{missing}"
        )

    stem = path.stem

    source_files = tuple(
        sorted(
            candidate
            for candidate in path.parent.iterdir()
            if candidate.is_file()
            and candidate.stem == stem
        )
    )

    return source_files


def validate_dataset_outputs(
    extraction_dir: Path,
) -> tuple[Path, tuple[Path, ...]]:
    """Validate the expected AER Carbon Sequestration Agreement products."""

    shapefiles = tuple(
        sorted(extraction_dir.rglob("*.shp"))
    )

    if len(shapefiles) != EXPECTED_SHAPEFILE_COUNT:
        raise ValueError(
            "Unexpected AER Carbon Sequestration Agreement shapefile count. "
            f"Expected {EXPECTED_SHAPEFILE_COUNT}, "
            f"found {len(shapefiles)}: "
            f"{[path.name for path in shapefiles]}"
        )

    shapefile_path = shapefiles[0]
    source_files = validate_shapefile(shapefile_path)

    return shapefile_path, source_files


# =============================================================================
# Acquisition workflow
# =============================================================================


def acquire(
    raw_dir: Path = RAW_AER_AGREEMENTS,
    *,
    overwrite: bool = False,
) -> AERAgreementAcquisitionResult:
    """Acquire and validate the AER Carbon Sequestration Agreement dataset.

    The original provider ZIP is retained after extraction so the exact Bronze
    artifact can be hashed and audited.

    Parameters
    ----------
    raw_dir : Path, default=RAW_AER_AGREEMENTS
        Bronze directory used to store the source archive and extracted files.
    overwrite : bool, default=False
        Whether to redownload and replace existing source files.

    Returns
    -------
    AERAgreementAcquisitionResult
        Validated Bronze paths and source archive checksum.
    """

    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    archive_path = raw_dir / ARCHIVE_NAME
    extraction_dir = raw_dir / "source"

    print("Acquiring Alberta Carbon Sequestration Agreement data...\n")
    print(f"Dataset:      {DATASET_ID}")
    print(f"Organization: {SOURCE_ORGANIZATION}")
    print(f"Source title: {SOURCE_TITLE}")
    print(f"Source page:  {SOURCE_PAGE_URL}")
    print(f"Parent page:  {SOURCE_PARENT_URL}")
    print(f"Archive URL:  {ARCHIVE_URL}")
    print(f"Raw folder:   {raw_dir}\n")

    downloaded_archive = download_file(
        url=ARCHIVE_URL,
        destination=archive_path,
        overwrite=overwrite,
    )

    if not zipfile.is_zipfile(downloaded_archive):
        raise ValueError(
            "Downloaded AER Carbon Sequestration Agreement dataset is not "
            "a valid ZIP archive. The configured provider resource may have "
            f"changed or returned non-binary content: {downloaded_archive}"
        )

    archive_hash = sha256_file(downloaded_archive)

    extract_zip(
        zip_path=downloaded_archive,
        output_dir=extraction_dir,
        overwrite=overwrite,
    )

    shapefile_path, source_files = validate_dataset_outputs(
        extraction_dir
    )

    result = AERAgreementAcquisitionResult(
        raw_dir=raw_dir,
        archive_path=downloaded_archive,
        archive_sha256=archive_hash,
        extraction_dir=extraction_dir,
        shapefile_path=shapefile_path,
        source_files=source_files,
    )

    print_summary(result)

    return result


# =============================================================================
# Console summary
# =============================================================================


def print_summary(
    result: AERAgreementAcquisitionResult,
) -> None:
    """Print a concise AER acquisition summary."""

    print("\nAER agreement acquisition summary")
    print("---------------------------------")
    print(f"Archive:       {result.archive_path.name}")
    print(f"Archive SHA:   {result.archive_sha256}")
    print(f"Shapefile:     {result.shapefile_path.name}")
    print(f"Source files:  {len(result.source_files)}")

    print("\nShapefile components:")
    for path in result.source_files:
        print(f"- {path.name}")

    print("\nProvider disclaimer:")
    print(SOURCE_DISCLAIMER)


# =============================================================================
# CLI
# =============================================================================


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Download, extract, and validate Alberta Carbon Sequestration "
            "Agreement source data."
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
        default=RAW_AER_AGREEMENTS,
        help=(
            "Bronze output directory. "
            "Defaults to data/raw/aer_agreements."
        ),
    )

    return parser.parse_args()


def main() -> None:
    """Run the AER Bronze acquisition workflow."""

    args = parse_args()

    acquire(
        raw_dir=args.raw_dir,
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    main()
