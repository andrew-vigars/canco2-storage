"""Project path discovery for CANCO2-Storage."""

from __future__ import annotations

from pathlib import Path


def find_project_root(start: Path | None = None) -> Path:
    """Find the CANCO2-Storage repository root.

    The project root is identified as the nearest parent directory containing
    both ``pyproject.toml`` and ``src/canco2_storage``.

    Parameters
    ----------
    start : Path | None, default=None
        Starting path for the search. When omitted, this module's location is
        used.

    Returns
    -------
    Path
        Repository root directory.

    Raises
    ------
    FileNotFoundError
        If a valid project root cannot be found.
    """

    current = Path(start or __file__).resolve()

    if current.is_file():
        current = current.parent

    for candidate in (current, *current.parents):
        package_dir = candidate / "src" / "canco2_storage"

        if (
            (candidate / "pyproject.toml").is_file()
            and package_dir.is_dir()
        ):
            return candidate

    raise FileNotFoundError(
        "Could not locate the CANCO2-Storage project root."
    )
