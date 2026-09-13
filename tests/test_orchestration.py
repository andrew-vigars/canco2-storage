"""Tests for dataset workflow registration and resolution."""

import pytest

from canco2_storage.orchestration.geopackages import (
    PIPELINE_DATASETS,
    resolve_pipeline_datasets,
)
from canco2_storage.orchestration.silver import resolve_datasets


def test_all_registered_datasets_are_in_pipeline_order() -> None:
    """Resolve all registered datasets in their declared order."""

    assert resolve_pipeline_datasets() == list(PIPELINE_DATASETS)
    assert resolve_datasets() == list(PIPELINE_DATASETS)


def test_requested_datasets_follow_registry_order() -> None:
    """Preserve registry order when callers request datasets out of order."""

    requested = ["natcarb_doe", "aer_agreements"]

    assert resolve_pipeline_datasets(requested) == [
        "aer_agreements",
        "natcarb_doe",
    ]


def test_unregistered_dataset_is_rejected() -> None:
    """Reject dataset IDs absent from both orchestration registries."""

    with pytest.raises(ValueError, match="not registered"):
        resolve_pipeline_datasets(["missing_dataset"])


def test_silver_rejects_unknown_dataset() -> None:
    """Reject dataset IDs absent from the Silver registry."""

    with pytest.raises(ValueError, match="Unknown Silver dataset ID"):
        resolve_datasets(["missing_dataset"])
