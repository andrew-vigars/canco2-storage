"""Shared helpers for CanCO₂Re dataset documentation and submission naming."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class SubmissionMetadata:
    """Store shared CanCO₂Re submission identity metadata.

    Parameters
    ----------
    activity_code : str
        CanCO₂Re activity code associated with the submitted dataset.
    creator_name : str
        Full name of the dataset creator or submitting researcher.
    creator_initials : str
        Initials used in CanCO₂Re submission filenames.
    """

    activity_code: str
    creator_name: str
    creator_initials: str


CANCO2RE_SUBMISSION = SubmissionMetadata(
    activity_code="13",
    creator_name="Andrew Vigars",
    creator_initials="AV",
)


def build_submission_stem(
    *,
    data_type: str,
    created_date: date,
) -> str:
    """Build a CanCO₂Re-compliant submission filename stem.

    Parameters
    ----------
    data_type : str
        Concise dataset descriptor used in the CanCO₂Re filename convention.
    created_date : datetime.date
        Date on which the submission artifact is generated.

    Returns
    -------
    str
        Filename stem using the pattern
        ``YYYYMMDD_ActivityCode_DataType_CreatorInitials``.

    Examples
    --------
    >>> build_submission_stem(
    ...     data_type="AtlanticStorageCOS",
    ...     created_date=date(2026, 9, 12),
    ... )
    '20260912_13_AtlanticStorageCOS_AV'
    """

    return (
        f"{created_date:%Y%m%d}_"
        f"{CANCO2RE_SUBMISSION.activity_code}_"
        f"{data_type}_"
        f"{CANCO2RE_SUBMISSION.creator_initials}"
    )


def write_readme(path: Path, text: str) -> Path:
    """Write normalized Markdown documentation to disk.

    Parameters
    ----------
    path : pathlib.Path
        Destination path for the README file.
    text : str
        Markdown content to write.

    Returns
    -------
    pathlib.Path
        Path to the written README file.

    Notes
    -----
    Parent directories are created when required. The written file is
    normalized to contain exactly one trailing newline.
    """

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return path


def format_int(value: int) -> str:
    """Format an integer with thousands separators.

    Parameters
    ----------
    value : int
        Integer-like value to format.

    Returns
    -------
    str
        Formatted integer string containing comma thousands separators.

    Examples
    --------
    >>> format_int(4711)
    '4,711'
    """

    return f"{int(value):,}"


def markdown_list(items: list[str] | tuple[str, ...]) -> str:
    """Render strings as a Markdown bullet list.

    Parameters
    ----------
    items : list of str or tuple of str
        Ordered collection of list items.

    Returns
    -------
    str
        Markdown-formatted bullet list with one item per line.
    """

    return "\n".join(f"- {item}" for item in items)


def numbered_steps(items: list[str] | tuple[str, ...]) -> str:
    """Render strings as a Markdown numbered list.

    Parameters
    ----------
    items : list of str or tuple of str
        Ordered collection of processing or workflow steps.

    Returns
    -------
    str
        Markdown-formatted numbered list beginning at one.
    """

    return "\n".join(
        f"{index}. {item}"
        for index, item in enumerate(items, start=1)
    )
