# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest
from meridian_storage.errors import MeridianError
from meridian_storage.spi import (
    AdapterDescriptor,
    CapabilityManifest,
    OperationCapability,
)

from meridian_storage.object_common import (
    GUARANTEE_CONDITIONAL_CREATE,
    GUARANTEE_STREAMING,
    LIMIT_MAX_OBJECT_BYTES,
    ConditionalConflict,
    DigestMismatch,
    IncompleteUpload,
    ObjectAuthenticationFailed,
    ObjectAuthorizationFailed,
    ObjectCapabilityMismatch,
    ObjectErrorCode,
    ObjectNotFound,
    ObjectQuotaExceeded,
    ObjectRateLimited,
    ObjectUnavailable,
    RetentionDenied,
    classify_object_failure,
    negotiate_object_capabilities,
    object_requirement,
    require_object_capabilities,
)


def _manifest(*, available: bool = True, max_bytes: int = 1024) -> CapabilityManifest:
    capability = OperationCapability(
        operation_contract="meridian.object.put",
        operation_versions=("1.0.0",),
        guarantees=(GUARANTEE_CONDITIONAL_CREATE, GUARANTEE_STREAMING),
        limits={LIMIT_MAX_OBJECT_BYTES: max_bytes},
    )
    stat_capability = OperationCapability(
        operation_contract="meridian.object.stat",
        operation_versions=("1.0.0",),
    )
    descriptor = AdapterDescriptor(
        adapter_id="memory-object-adapter",
        adapter_contract_version="1.0.0",
        driver="memory",
        supported_engine_versions={"memory": ("1.0.0",)},
        capabilities=(capability, stat_capability),
    )
    return CapabilityManifest(
        descriptor,
        "memory",
        "1.0.0",
        available_operation_contracts=(
            ("meridian.object.put", "meridian.object.stat")
            if available
            else ("meridian.object.stat",)
        ),
    )


def test_object_capability_negotiation_accepts_supported_requirement() -> None:
    manifest = _manifest()
    requirement = object_requirement(
        "put",
        guarantees=(GUARANTEE_STREAMING, GUARANTEE_CONDITIONAL_CREATE),
        minimum_limits={LIMIT_MAX_OBJECT_BYTES: 512},
    )
    report = negotiate_object_capabilities(manifest, (requirement,))
    assert report.supported
    assert report.violations == ()
    assert report.capability_fingerprint == manifest.fingerprint
    assert require_object_capabilities(manifest, (requirement,)) == manifest.fingerprint


@pytest.mark.parametrize(
    "requirement",
    [
        object_requirement("put", guarantees=("object.missing",)),
        object_requirement("put", minimum_limits={LIMIT_MAX_OBJECT_BYTES: 2048}),
        object_requirement("put", guarantees=(GUARANTEE_STREAMING,)),
    ],
)
def test_object_capability_negotiation_reports_stable_mismatch(requirement: object) -> None:
    manifest = _manifest(available=True, max_bytes=1024)
    if getattr(requirement, "guarantees", ()) == (GUARANTEE_STREAMING,):
        manifest = _manifest(available=False, max_bytes=1024)
    report = negotiate_object_capabilities(manifest, (requirement,))  # type: ignore[arg-type]
    assert not report.supported
    assert len(report.violations) == 1
    with pytest.raises(ObjectCapabilityMismatch) as captured:
        require_object_capabilities(manifest, (requirement,))  # type: ignore[arg-type]
    data = captured.value.to_dict()
    assert data["code"] == ObjectErrorCode.CAPABILITY_MISMATCH
    assert data["adapterProvenance"]["adapterId"] == "memory-object-adapter"


def test_object_capability_negotiation_rejects_other_catalog_contracts() -> None:
    requirement = object_requirement("put")
    foreign = type(requirement)("meridian.cache.put", "1.0.0")
    with pytest.raises(ValueError, match="only Object"):
        negotiate_object_capabilities(_manifest(), (foreign,))


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("authentication", ObjectAuthenticationFailed),
        ("authorization", ObjectAuthorizationFailed),
        ("conditional-conflict", ConditionalConflict),
        ("corruption", DigestMismatch),
        ("incomplete-upload", IncompleteUpload),
        ("missing-object", ObjectNotFound),
        ("quota", ObjectQuotaExceeded),
        ("rate-limit", ObjectRateLimited),
        ("retention-denied", RetentionDenied),
        ("unavailable", ObjectUnavailable),
        ("unknown-provider-failure", ObjectUnavailable),
    ],
)
def test_failure_classifier_maps_only_safe_public_taxonomy(
    kind: str,
    expected: type[MeridianError],
) -> None:
    failure = classify_object_failure(kind, request_id="safe-request-id")
    assert isinstance(failure, expected)
    assert failure.to_dict()["requestId"] == "safe-request-id"
    custom = classify_object_failure(kind, message="safe message")
    expected_message = (
        "Object Adapter returned an unclassified failure"
        if kind == "unknown-provider-failure"
        else "safe message"
    )
    assert custom.to_dict()["message"] == expected_message


def test_object_error_codes_are_unique_and_retryability_is_explicit() -> None:
    values = [item.value for item in ObjectErrorCode]
    assert len(values) == len(set(values)) == 17
    assert all(value.startswith("MERIDIAN_OBJECT_") for value in values)
    assert ObjectRateLimited().retryable
    assert ObjectUnavailable().retryable
    assert not ObjectNotFound().retryable
