"""
Acquire the U.S. DOE/NETL NATCARB All Data v1502 source dataset.

The source dataset is the NATCARB All Data v1502 release distributed by
the U.S. Department of Energy National Energy Technology Laboratory (NETL).

The provider archive contains:

- NATCARB_v1502.gdb — the source Esri File Geodatabase,
- Metadata_v1502 — provider metadata for the principal NATCARB datasets.

This module performs Bronze-layer acquisition only:

- download the official provider ZIP archive,
- extract the archive while preserving provider directory structure,
- validate the expected File Geodatabase and metadata products,
- validate the expected logical FileGDB datasets,
- calculate a SHA-256 checksum for the retained source archive,
- return paths required by downstream harmonization.

It does not rename source fields, harmonize schemas, reproject geometries,
filter geological storage resources, interpret assessment flags, reconcile
overlapping resource estimates, remove duplicate resource records, or
construct Silver-layer products.

Source
------
U.S. Department of Energy (DOE),
National Energy Technology Laboratory (NETL),
National Carbon Sequestration Database and Geographic Information System
(NATCARB).

OSTI record:
https://www.osti.gov/biblio/1474110

Dataset page:
https://edx.netl.doe.gov/dataset/natcarb

Version-specific resource page:
https://edx.netl.doe.gov/dataset/natcarb-alldata-v1502

Download:
https://edx.netl.doe.gov/resource/f7b936b3-b250-47e4-8475-e1c8474d9e22/download
"""

from __future__ import annotations

import argparse
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pyogrio

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
RAW_NATCARB_DOE = RAW_STORAGE / "natcarb_doe"


# =============================================================================
# Source definition
# =============================================================================

DATASET_ID = "natcarb_doe"

SOURCE_ORGANIZATION = (
    "U.S. Department of Energy, "
    "National Energy Technology Laboratory (NETL)"
)

SOURCE_TITLE = "NATCARB All Data v1502"
SOURCE_VERSION = "v1502"

OSTI_URL = "https://www.osti.gov/biblio/1474110"

SOURCE_PAGE_URL = (
    "https://edx.netl.doe.gov/dataset/natcarb"
)

RESOURCE_PAGE_URL = (
    "https://edx.netl.doe.gov/dataset/natcarb-alldata-v1502"
)

ARCHIVE_URL = (
    "https://edx.netl.doe.gov/resource/"
    "f7b936b3-b250-47e4-8475-e1c8474d9e22/download"
)

ARCHIVE_NAME = "natcarb-alldata-v1502.zip"

EXPECTED_GDB_NAME = "NATCARB_v1502.gdb"
EXPECTED_METADATA_DIR = "Metadata_v1502"


# =============================================================================
# Expected provider products
# =============================================================================

EXPECTED_METADATA_PRODUCTS = (
    "NATCARB_Coal_10K_v1502",
    "NATCARB_Coal_Poly_v1502",
    "NATCARB_OilGas_v1502",
    "NATCARB_Saline_10K_v1502",
    "NATCARB_Saline_Poly_v1502",
    "NATCARB_Sources2011_v1502",
    "NATCARB_Sources2012_v1502",
    "NATCARB_Sources2013_v1502",
)

EXPECTED_GDB_SPATIAL_LAYERS = (
    "NATCARB_Coal_10K_v1502",
    "NATCARB_Coal_Poly_v1502",
    "NATCARB_OilGas_v1502",
    "NATCARB_Saline_10K_v1502",
    "NATCARB_Saline_Poly_v1502",
    "NATCARB_Sources2011_v1502",
    "NATCARB_Sources2012_v1502",
    "NATCARB_Sources2013_v1502",
)

EXPECTED_GDB_DOMAIN_TABLES = (
    "Domain_State",
    "Domain_Fuel",
    "Domain_Overlap",
    "Domain_Duplicate",
    "Domain_ARRA",
    "Domain_Source_Types",
    "Domain_Med_Calced",
    "Domain_Partnership",
    "Domain_Oil_Gas",
    "Domain_Assessed",
)

EXPECTED_GDB_DATASETS = (
    *EXPECTED_GDB_SPATIAL_LAYERS,
    *EXPECTED_GDB_DOMAIN_TABLES,
)


# =============================================================================
# Acquisition result
# =============================================================================


@dataclass(frozen=True)
class NATCARBAcquisitionResult:
    """Validated Bronze products from NATCARB All Data v1502."""

    raw_dir: Path
    archive_path: Path
    archive_sha256: str

    extraction_dir: Path
    gdb_path: Path
    metadata_dir: Path

    metadata_files: tuple[Path, ...]
    gdb_datasets: tuple[str, ...]
    source_files: tuple[Path, ...]


# =============================================================================
# Path discovery helpers
# =============================================================================


def find_unique_path(
    root: Path,
    name: str,
    *,
    expect_directory: bool,
) -> Path:
    """Find exactly one source path with the requested name.

    Recursive discovery allows validation to tolerate a provider-supplied
    top-level archive directory while preserving the provider hierarchy.

    Parameters
    ----------
    root : Path
        Root directory to search recursively.
    name : str
        Exact source file or directory name to locate.
    expect_directory : bool
        Whether the expected path must be a directory.

    Returns
    -------
    Path
        Unique matching source path.

    Raises
    ------
    FileNotFoundError
        If no matching path is found.
    ValueError
        If more than one matching path is found.
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


# =============================================================================
# Metadata validation
# =============================================================================


def validate_metadata(
    metadata_dir: Path,
) -> tuple[Path, ...]:
    """Validate expected NATCARB provider metadata products.

    Each expected NATCARB dataset must have both an XML metadata document and
    a PDF metadata document in the provider metadata directory.

    Parameters
    ----------
    metadata_dir : Path
        Provider Metadata_v1502 directory.

    Returns
    -------
    tuple[Path, ...]
        Sorted paths to metadata files associated with the expected products.

    Raises
    ------
    FileNotFoundError
        If the metadata directory or any required XML/PDF metadata product is
        missing.
    """

    if not metadata_dir.is_dir():
        raise FileNotFoundError(
            f"NATCARB metadata directory not found: {metadata_dir}"
        )

    expected_files: list[Path] = []

    for product in EXPECTED_METADATA_PRODUCTS:
        for suffix in (".xml", ".pdf"):
            path = metadata_dir / f"{product}{suffix}"

            if not path.is_file():
                raise FileNotFoundError(
                    "Expected NATCARB metadata product not found: "
                    f"{path.name}"
                )

            expected_files.append(path)

    return tuple(sorted(expected_files))


# =============================================================================
# FileGDB validation
# =============================================================================


def inspect_gdb_datasets(
    gdb_path: Path,
) -> dict[str, str | None]:
    """Return logical NATCARB FileGDB datasets and geometry types.

    Spatial layers are returned with their geometry type. Non-spatial FileGDB
    tables are represented with ``None``.

    Parameters
    ----------
    gdb_path : Path
        NATCARB Esri File Geodatabase directory.

    Returns
    -------
    dict[str, str | None]
        Mapping from logical dataset name to geometry type.

    Raises
    ------
    FileNotFoundError
        If the expected FileGDB directory does not exist.
    ValueError
        If the FileGDB cannot be read or contains no logical datasets.
    """

    if not gdb_path.is_dir():
        raise FileNotFoundError(
            f"NATCARB FileGDB not found: {gdb_path}"
        )

    try:
        layers = pyogrio.list_layers(gdb_path)
    except Exception as exc:
        raise ValueError(
            f"Could not read NATCARB FileGDB: {gdb_path}"
        ) from exc

    if len(layers) == 0:
        raise ValueError(
            f"NATCARB FileGDB contains no logical datasets: {gdb_path}"
        )

    return {
        str(name): None if geometry is None else str(geometry)
        for name, geometry in layers
    }


def validate_gdb(
    gdb_path: Path,
) -> tuple[str, ...]:
    """Validate the expected NATCARB FileGDB logical dataset structure.

    The NATCARB v1502 FileGDB is expected to contain eight spatial datasets
    and ten non-spatial domain tables. Unexpected or missing datasets are
    treated as source-structure changes and reported explicitly.

    Parameters
    ----------
    gdb_path : Path
        NATCARB Esri File Geodatabase directory.

    Returns
    -------
    tuple[str, ...]
        Sorted logical dataset names present in the FileGDB.

    Raises
    ------
    ValueError
        If expected datasets are missing, unexpected datasets are present,
        spatial layers are non-spatial, or expected domain tables contain
        geometries.
    """

    available = inspect_gdb_datasets(gdb_path)

    available_names = set(available)
    expected_names = set(EXPECTED_GDB_DATASETS)

    missing = sorted(expected_names - available_names)
    unexpected = sorted(available_names - expected_names)

    if missing:
        raise ValueError(
            "NATCARB FileGDB is missing expected logical dataset(s): "
            f"{missing}"
        )

    if unexpected:
        raise ValueError(
            "NATCARB FileGDB contains unexpected logical dataset(s): "
            f"{unexpected}"
        )

    non_spatial_expected_layers = sorted(
        layer
        for layer in EXPECTED_GDB_SPATIAL_LAYERS
        if available[layer] is None
    )

    if non_spatial_expected_layers:
        raise ValueError(
            "Expected NATCARB spatial layer(s) have no geometry type: "
            f"{non_spatial_expected_layers}"
        )

    spatial_domain_tables = sorted(
        table
        for table in EXPECTED_GDB_DOMAIN_TABLES
        if available[table] is not None
    )

    if spatial_domain_tables:
        raise ValueError(
            "Expected NATCARB domain table(s) unexpectedly contain geometry: "
            f"{spatial_domain_tables}"
        )

    return tuple(sorted(available))


# =============================================================================
# Dataset validation
# =============================================================================


def validate_dataset_outputs(
    extraction_dir: Path,
) -> tuple[
    Path,
    Path,
    tuple[Path, ...],
    tuple[str, ...],
    tuple[Path, ...],
]:
    """Validate the expected NATCARB v1502 Bronze source products.

    Parameters
    ----------
    extraction_dir : Path
        Directory containing the extracted provider archive.

    Returns
    -------
    tuple
        Validated FileGDB path, metadata directory, metadata files,
        logical FileGDB dataset names, and complete extracted source-file
        inventory.

    Raises
    ------
    FileNotFoundError
        If required source directories or files are absent.
    ValueError
        If the FileGDB structure differs from the expected NATCARB v1502
        source contract.
    """

    if not extraction_dir.is_dir():
        raise FileNotFoundError(
            f"NATCARB extraction directory not found: {extraction_dir}"
        )

    gdb_path = find_unique_path(
        extraction_dir,
        EXPECTED_GDB_NAME,
        expect_directory=True,
    )

    metadata_dir = find_unique_path(
        extraction_dir,
        EXPECTED_METADATA_DIR,
        expect_directory=True,
    )

    metadata_files = validate_metadata(metadata_dir)

    gdb_datasets = validate_gdb(gdb_path)

    source_files = tuple(
        sorted(
            path
            for path in extraction_dir.rglob("*")
            if path.is_file()
        )
    )

    if not source_files:
        raise FileNotFoundError(
            f"No NATCARB source files found under {extraction_dir}."
        )

    return (
        gdb_path,
        metadata_dir,
        metadata_files,
        gdb_datasets,
        source_files,
    )


# =============================================================================
# Acquisition workflow
# =============================================================================


def acquire(
    raw_dir: Path = RAW_NATCARB_DOE,
    *,
    overwrite: bool = False,
) -> NATCARBAcquisitionResult:
    """Acquire and validate the DOE/NETL NATCARB All Data v1502 dataset.

    The original provider ZIP archive is retained after extraction so the
    exact Bronze source artifact can be hashed and audited.

    Parameters
    ----------
    raw_dir : Path, default=RAW_NATCARB_DOE
        Bronze directory used to store the NATCARB source archive and
        extracted source files.
    overwrite : bool, default=False
        Whether to redownload and re-extract existing source files.

    Returns
    -------
    NATCARBAcquisitionResult
        Validated Bronze paths, logical source datasets, and source archive
        checksum.
    """

    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    archive_path = raw_dir / ARCHIVE_NAME
    extraction_dir = raw_dir / "source"

    print("Acquiring DOE/NETL NATCARB All Data v1502...\n")
    print(f"Dataset:        {DATASET_ID}")
    print(f"Organization:   {SOURCE_ORGANIZATION}")
    print(f"Source title:   {SOURCE_TITLE}")
    print(f"Version:        {SOURCE_VERSION}")
    print(f"OSTI record:    {OSTI_URL}")
    print(f"Dataset page:   {SOURCE_PAGE_URL}")
    print(f"Resource page:  {RESOURCE_PAGE_URL}")
    print(f"Archive URL:    {ARCHIVE_URL}")
    print(f"Raw folder:     {raw_dir}\n")

    downloaded_archive = download_file(
        url=ARCHIVE_URL,
        destination=archive_path,
        overwrite=overwrite,
    )

    if not zipfile.is_zipfile(downloaded_archive):
        raise ValueError(
            "Downloaded NATCARB dataset is not a valid ZIP archive. "
            "The configured NETL EDX resource may have changed or returned "
            f"non-binary content: {downloaded_archive}"
        )

    archive_hash = sha256_file(
        downloaded_archive
    )

    extract_zip(
        zip_path=downloaded_archive,
        output_dir=extraction_dir,
        overwrite=overwrite,
    )

    (
        gdb_path,
        metadata_dir,
        metadata_files,
        gdb_datasets,
        source_files,
    ) = validate_dataset_outputs(
        extraction_dir
    )

    result = NATCARBAcquisitionResult(
        raw_dir=raw_dir,
        archive_path=downloaded_archive,
        archive_sha256=archive_hash,
        extraction_dir=extraction_dir,
        gdb_path=gdb_path,
        metadata_dir=metadata_dir,
        metadata_files=metadata_files,
        gdb_datasets=gdb_datasets,
        source_files=source_files,
    )

    print_summary(result)

    return result


# =============================================================================
# Console summary
# =============================================================================


def print_summary(
    result: NATCARBAcquisitionResult,
) -> None:
    """Print a concise NATCARB acquisition summary."""

    print("\nNATCARB acquisition summary")
    print("---------------------------")
    print(f"Archive:          {result.archive_path.name}")
    print(f"Archive SHA:      {result.archive_sha256}")
    print(f"FileGDB:          {result.gdb_path.name}")
    print(f"Metadata folder:  {result.metadata_dir.name}")
    print(f"Metadata files:   {len(result.metadata_files)}")
    print(f"GDB datasets:     {len(result.gdb_datasets)}")
    print(f"Source files:     {len(result.source_files)}")

    print("\nFileGDB datasets:")
    for dataset in result.gdb_datasets:
        print(f"- {dataset}")

    print("\nMetadata products:")
    for product in EXPECTED_METADATA_PRODUCTS:
        print(f"- {product}")


# =============================================================================
# CLI
# =============================================================================


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Download, extract, and validate the DOE/NETL "
            "NATCARB All Data v1502 source dataset."
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
        default=RAW_NATCARB_DOE,
        help=(
            "Bronze output directory. "
            "Defaults to data/raw/natcarb_doe."
        ),
    )

    return parser.parse_args()


def main() -> None:
    """Run the NATCARB Bronze acquisition workflow."""

    args = parse_args()

    acquire(
        raw_dir=args.raw_dir,
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    main()
