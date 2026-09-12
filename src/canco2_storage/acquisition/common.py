"""
Shared raw-data acquisition utilities for CANCO2-Storage.

This module contains generic helpers used by source-specific acquisition
workflows. It is intentionally limited to transport and archive operations:

- downloading files,
- extracting ZIP archives,
- calculating file hashes.

Dataset-specific URLs, expected files, source validation, provenance metadata,
and geological interpretation belong in the individual acquisition modules.
"""

from __future__ import annotations

import hashlib
import shutil
import time
import zipfile
from collections.abc import Mapping
from pathlib import Path

import requests


# =============================================================================
# Default acquisition settings
# =============================================================================

DEFAULT_HEADERS = {
    "User-Agent": (
        "CANCO2-Storage/0.1.0 "
        "(University of Toronto Academic Research)"
    )
}

DEFAULT_TIMEOUT = 120
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 5
DEFAULT_CHUNK_SIZE = 1024 * 1024  # 1 MiB


# =============================================================================
# Download helpers
# =============================================================================


def download_file(
    url: str,
    destination: Path,
    *,
    overwrite: bool = False,
    headers: Mapping[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_delay: float = DEFAULT_RETRY_DELAY,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> Path:
    """Download a file using streaming, retry handling, and a temporary file.

    The destination parent directory is created when needed. Existing completed
    files are reused unless ``overwrite`` is true.

    Downloads are first written to a ``.part`` file. The temporary file is moved
    to the requested destination only after the HTTP response has been written
    successfully. This prevents interrupted downloads from appearing to be valid
    raw source files.

    Parameters
    ----------
    url : str
        HTTP or HTTPS URL of the source file.
    destination : Path
        Local path where the completed file will be stored.
    overwrite : bool, default=False
        Whether to replace an existing destination file.
    headers : Mapping[str, str] | None, default=None
        Optional HTTP headers. ``DEFAULT_HEADERS`` are used when omitted.
    timeout : int, default=DEFAULT_TIMEOUT
        Request timeout in seconds.
    max_retries : int, default=DEFAULT_MAX_RETRIES
        Maximum number of download attempts.
    retry_delay : float, default=DEFAULT_RETRY_DELAY
        Delay in seconds between failed attempts.
    chunk_size : int, default=DEFAULT_CHUNK_SIZE
        Streaming chunk size in bytes.

    Returns
    -------
    Path
        Path to the existing or successfully downloaded file.

    Raises
    ------
    ValueError
        If ``max_retries`` or ``chunk_size`` is less than one.
    RuntimeError
        If the file cannot be downloaded after all configured attempts.
    """

    if max_retries < 1:
        raise ValueError("max_retries must be at least 1.")

    if chunk_size < 1:
        raise ValueError("chunk_size must be at least 1 byte.")

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    if destination.exists() and not overwrite:
        print(f"[Skip download] {destination.name} already exists.")
        return destination

    if destination.exists():
        destination.unlink()

    temp_path = destination.with_suffix(destination.suffix + ".part")
    request_headers = dict(headers) if headers is not None else DEFAULT_HEADERS

    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        temp_path.unlink(missing_ok=True)

        try:
            print(
                f"[Download] {destination.name} "
                f"(attempt {attempt}/{max_retries})"
            )

            with requests.get(
                url,
                headers=request_headers,
                stream=True,
                timeout=timeout,
            ) as response:
                response.raise_for_status()

                with temp_path.open("wb") as file:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if chunk:
                            file.write(chunk)

            temp_path.replace(destination)

            print(f"[Complete download] {destination.name}")
            return destination

        except (requests.RequestException, OSError) as exc:
            last_error = exc
            temp_path.unlink(missing_ok=True)

            if attempt < max_retries:
                print(f"[Retry] {destination.name}: {exc}")
                time.sleep(retry_delay)

    raise RuntimeError(
        f"Failed to download {url} after {max_retries} attempt(s)."
    ) from last_error


# =============================================================================
# Archive helpers
# =============================================================================


def extract_zip(
    zip_path: Path,
    output_dir: Path,
    *,
    overwrite: bool = False,
) -> list[Path]:
    """Extract a ZIP archive while preserving its original directory structure.

    Unlike some Geospatial-CANOE acquisition workflows, this helper does not
    flatten nested archive directories. Geological source archives may contain
    meaningful directory organization, so Bronze extraction preserves the
    provider's original structure by default.

    Existing files are retained when ``overwrite`` is false. When ``overwrite``
    is true, matching extracted files are replaced.

    Archive members are validated before extraction to prevent paths from
    escaping ``output_dir``.

    Parameters
    ----------
    zip_path : Path
        ZIP archive to extract.
    output_dir : Path
        Directory into which archive contents will be extracted.
    overwrite : bool, default=False
        Whether existing extracted files should be replaced.

    Returns
    -------
    list[Path]
        Sorted paths to files represented by the archive after extraction.

    Raises
    ------
    FileNotFoundError
        If the ZIP archive does not exist.
    ValueError
        If the archive contains an unsafe path.
    zipfile.BadZipFile
        If ``zip_path`` is not a valid ZIP archive.
    """

    zip_path = Path(zip_path)
    output_dir = Path(output_dir)

    if not zip_path.is_file():
        raise FileNotFoundError(f"ZIP archive not found: {zip_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_root = output_dir.resolve()

    extracted_files: list[Path] = []

    print(f"[Extract] {zip_path.name} → {output_dir}")

    with zipfile.ZipFile(zip_path, "r") as archive:
        for member in archive.infolist():
            target = output_dir / member.filename
            resolved_target = target.resolve()

            if not resolved_target.is_relative_to(output_root):
                raise ValueError(
                    f"Unsafe archive member outside extraction directory: "
                    f"{member.filename}"
                )

            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue

            target.parent.mkdir(parents=True, exist_ok=True)

            if target.exists() and not overwrite:
                print(f"[Skip extract] {member.filename} already exists.")
                extracted_files.append(target)
                continue

            with archive.open(member, "r") as source:
                with target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)

            extracted_files.append(target)

    if not extracted_files:
        raise FileNotFoundError(
            f"No files found in ZIP archive: {zip_path}"
        )

    print(
        f"[Complete extract] {zip_path.name}: "
        f"{len(extracted_files)} file(s)"
    )

    return sorted(extracted_files)


# =============================================================================
# Provenance helpers
# =============================================================================


def sha256_file(
    path: Path,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> str:
    """Calculate the SHA-256 checksum of a file.

    The file is read incrementally so large geological datasets can be hashed
    without loading them entirely into memory.

    Parameters
    ----------
    path : Path
        File to hash.
    chunk_size : int, default=DEFAULT_CHUNK_SIZE
        Number of bytes read during each iteration.

    Returns
    -------
    str
        Lowercase hexadecimal SHA-256 digest.

    Raises
    ------
    FileNotFoundError
        If ``path`` does not identify an existing file.
    ValueError
        If ``chunk_size`` is less than one.
    """

    path = Path(path)

    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    if chunk_size < 1:
        raise ValueError("chunk_size must be at least 1 byte.")

    digest = hashlib.sha256()

    with path.open("rb") as file:
        while chunk := file.read(chunk_size):
            digest.update(chunk)

    return digest.hexdigest()
