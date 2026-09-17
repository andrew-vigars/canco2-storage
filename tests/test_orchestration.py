"""Tests for dataset workflow registration and resolution."""

import pytest

from canco2_storage.orchestration import build_all, unified
from canco2_storage.orchestration.geopackages import (
    BRONZE_DATASETS,
    PIPELINE_DATASETS,
    resolve_build_datasets,
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


def test_build_includes_bronze_only_datasets() -> None:
    """Include Bronze-only support datasets in the acquisition queue."""

    assert resolve_build_datasets() == list(BRONZE_DATASETS)
    assert resolve_build_datasets(["statcan_digital_boundaries"]) == [
        "statcan_digital_boundaries",
    ]


def test_unregistered_dataset_is_rejected() -> None:
    """Reject dataset IDs absent from both orchestration registries."""

    with pytest.raises(ValueError, match="not registered"):
        resolve_pipeline_datasets(["missing_dataset"])


def test_silver_rejects_unknown_dataset() -> None:
    """Reject dataset IDs absent from the Silver registry."""

    with pytest.raises(ValueError, match="Unknown Silver dataset ID"):
        resolve_datasets(["missing_dataset"])


def test_unified_runs_harmonization_before_metadata(monkeypatch) -> None:
    """Build the unified GeoPackage before rendering its README."""

    calls: list[tuple[str, list[str] | None]] = []
    monkeypatch.setattr(
        unified,
        "run_module",
        lambda module_name, arguments=None: calls.append((module_name, arguments)),
    )

    unified.build_unified()

    assert [module_name for module_name, _ in calls] == [
        unified.HARMONIZE_MODULE,
        unified.METADATA_MODULE,
    ]


def test_build_all_runs_geopackages_before_unified(monkeypatch) -> None:
    """Run the precursor GeoPackages before the unified atlas."""

    calls: list[str] = []
    monkeypatch.setattr(
        build_all,
        "build_geopackages",
        lambda **_: calls.append("geopackages"),
    )
    monkeypatch.setattr(
        build_all,
        "build_unified",
        lambda **_: calls.append("unified"),
    )

    monkeypatch.setattr(
        build_all,
        "parse_args",
        lambda: type(
            "Args",
            (),
            {
                "datasets": None,
                "skip_bronze": False,
                "skip_silver": False,
                "project_root": None,
                "output": None,
            },
        )(),
    )

    build_all.main()

    assert calls == ["geopackages", "unified"]
