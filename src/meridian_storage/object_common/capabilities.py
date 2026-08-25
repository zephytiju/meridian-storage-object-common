# SPDX-License-Identifier: Apache-2.0
"""Object-specific names layered on Core capability negotiation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from meridian_storage.spi import (
    CapabilityManifest,
    CapabilityRequirement,
    CapabilityViolation,
    capability_violations,
)

from .errors import ObjectCapabilityMismatch

OBJECT_OPERATION_VERSION = "1.0.0"

GUARANTEE_STREAMING = "object.streaming"
GUARANTEE_DIGEST_SHA256 = "object.digest-sha256"
GUARANTEE_DIGEST_VERIFICATION = "object.digest-verification"
GUARANTEE_METADATA_AFTER_COMMIT = "object.metadata-after-commit"
GUARANTEE_RANGE_READ = "object.range-read"
GUARANTEE_CONDITIONAL_CREATE = "object.conditional-create"
GUARANTEE_BOUNDED_PREFIX_LIST = "object.bounded-prefix-list"
GUARANTEE_EXACT_VERSION_DELETE = "object.exact-version-delete"
GUARANTEE_MULTIPART = "object.multipart"
GUARANTEE_IMMUTABILITY_INTENT = "object.immutability-intent"
GUARANTEE_RETENTION_INTENT = "object.retention-intent"
GUARANTEE_RETENTION_ENFORCEMENT = "object.retention-enforcement"
GUARANTEE_SIGNED_REFERENCE = "object.signed-reference"

LIMIT_MAX_OBJECT_BYTES = "object.max-object-bytes"
LIMIT_MAX_RANGE_BYTES = "object.max-range-bytes"
LIMIT_MAX_LIST_PAGE_SIZE = "object.max-list-page-size"
LIMIT_MAX_USER_METADATA_ENTRIES = "object.max-user-metadata-entries"
LIMIT_MAX_MULTIPART_PARTS = "object.max-multipart-parts"
LIMIT_MAX_MULTIPART_PART_BYTES = "object.max-multipart-part-bytes"


def object_requirement(
    method: str,
    *,
    guarantees: Iterable[str] = (),
    minimum_limits: Mapping[str, int] | None = None,
) -> CapabilityRequirement:
    return CapabilityRequirement(
        operation_contract=f"meridian.object.{method}",
        operation_version=OBJECT_OPERATION_VERSION,
        guarantees=tuple(guarantees),
        minimum_limits=minimum_limits or {},
    )


@dataclass(frozen=True, slots=True)
class ObjectCapabilityReport:
    supported: bool
    violations: tuple[CapabilityViolation, ...]
    capability_fingerprint: str


def negotiate_object_capabilities(
    manifest: CapabilityManifest,
    requirements: Iterable[CapabilityRequirement],
) -> ObjectCapabilityReport:
    selected = tuple(requirements)
    if any(not item.operation_contract.startswith("meridian.object.") for item in selected):
        raise ValueError("Object capability negotiation accepts only Object operation contracts")
    violations = capability_violations(manifest, selected)
    return ObjectCapabilityReport(not violations, violations, manifest.fingerprint)


def require_object_capabilities(
    manifest: CapabilityManifest,
    requirements: Iterable[CapabilityRequirement],
) -> str:
    report = negotiate_object_capabilities(manifest, requirements)
    if not report.supported:
        first = report.violations[0]
        raise ObjectCapabilityMismatch(
            f"Object capability requirement is unsatisfied: {first.reason}",
            operation_contract=first.requirement.operation_contract,
            adapter_provenance={
                "adapterId": manifest.adapter_id,
                "capabilityFingerprint": report.capability_fingerprint,
            },
        )
    return report.capability_fingerprint


__all__ = [
    "GUARANTEE_BOUNDED_PREFIX_LIST",
    "GUARANTEE_CONDITIONAL_CREATE",
    "GUARANTEE_DIGEST_SHA256",
    "GUARANTEE_DIGEST_VERIFICATION",
    "GUARANTEE_EXACT_VERSION_DELETE",
    "GUARANTEE_IMMUTABILITY_INTENT",
    "GUARANTEE_METADATA_AFTER_COMMIT",
    "GUARANTEE_MULTIPART",
    "GUARANTEE_RANGE_READ",
    "GUARANTEE_RETENTION_ENFORCEMENT",
    "GUARANTEE_RETENTION_INTENT",
    "GUARANTEE_SIGNED_REFERENCE",
    "GUARANTEE_STREAMING",
    "LIMIT_MAX_LIST_PAGE_SIZE",
    "LIMIT_MAX_MULTIPART_PARTS",
    "LIMIT_MAX_MULTIPART_PART_BYTES",
    "LIMIT_MAX_OBJECT_BYTES",
    "LIMIT_MAX_RANGE_BYTES",
    "LIMIT_MAX_USER_METADATA_ENTRIES",
    "OBJECT_OPERATION_VERSION",
    "ObjectCapabilityReport",
    "negotiate_object_capabilities",
    "object_requirement",
    "require_object_capabilities",
]
