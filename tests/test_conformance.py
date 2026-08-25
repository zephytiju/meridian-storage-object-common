# SPDX-License-Identifier: Apache-2.0

from dataclasses import replace

import pytest

from meridian_storage.object_common import (
    ObjectConformanceCheck,
    ObjectConformanceTarget,
    run_object_conformance,
)

from ._memory_target import MemoryObjectTarget


@pytest.mark.conformance
def test_memory_target_passes_complete_conformance() -> None:
    target = MemoryObjectTarget()
    assert isinstance(target, ObjectConformanceTarget)

    report = run_object_conformance(target)

    assert report.passed
    assert len(report.checks) == 9
    assert report.fingerprint.startswith("sha256:")
    assert report.to_dict()["fingerprint"] == report.fingerprint
    report.require_success()


@pytest.mark.conformance
def test_conformance_report_is_deterministic_and_reports_failures() -> None:
    report = run_object_conformance(MemoryObjectTarget())
    rerun = run_object_conformance(MemoryObjectTarget())
    assert report.to_dict() == rerun.to_dict()

    failed = replace(
        report,
        checks=(ObjectConformanceCheck("forced", False, "failure"),),
    )
    assert not failed.passed
    with pytest.raises(AssertionError, match="forced"):
        failed.require_success()


@pytest.mark.conformance
def test_conformance_rejects_non_target() -> None:
    with pytest.raises(TypeError, match="does not implement"):
        run_object_conformance(object())  # type: ignore[arg-type]
