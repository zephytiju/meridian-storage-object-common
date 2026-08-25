# SPDX-License-Identifier: Apache-2.0
"""Stable provider-neutral Object Catalog failures."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from meridian_storage.errors import (
    AuthenticationError,
    AuthorizationError,
    CompatibilityError,
    ConflictError,
    ConstraintError,
    CorruptionError,
    MeridianError,
    NotFoundError,
    RateLimitError,
    TransientError,
    UnavailableError,
    ValidationError,
)


class ObjectErrorCode(StrEnum):
    INVALID_REQUEST = "MERIDIAN_OBJECT_INVALID_REQUEST"
    NOT_FOUND = "MERIDIAN_OBJECT_NOT_FOUND"
    CONDITIONAL_CONFLICT = "MERIDIAN_OBJECT_CONDITIONAL_CONFLICT"
    IMMUTABLE = "MERIDIAN_OBJECT_IMMUTABLE"
    RETENTION_DENIED = "MERIDIAN_OBJECT_RETENTION_DENIED"
    DIGEST_MISMATCH = "MERIDIAN_OBJECT_DIGEST_MISMATCH"
    INCOMPLETE_UPLOAD = "MERIDIAN_OBJECT_INCOMPLETE_UPLOAD"
    PAYLOAD_UNAVAILABLE = "MERIDIAN_OBJECT_PAYLOAD_UNAVAILABLE"
    RANGE_NOT_SATISFIABLE = "MERIDIAN_OBJECT_RANGE_NOT_SATISFIABLE"
    MULTIPART_INVALID = "MERIDIAN_OBJECT_MULTIPART_INVALID"
    CAPABILITY_MISMATCH = "MERIDIAN_OBJECT_CAPABILITY_MISMATCH"
    AUTHENTICATION = "MERIDIAN_OBJECT_AUTHENTICATION"
    AUTHORIZATION = "MERIDIAN_OBJECT_AUTHORIZATION"
    QUOTA = "MERIDIAN_OBJECT_QUOTA"
    RATE_LIMIT = "MERIDIAN_OBJECT_RATE_LIMIT"
    TRANSFER_CANCELLED = "MERIDIAN_OBJECT_TRANSFER_CANCELLED"
    UNAVAILABLE = "MERIDIAN_OBJECT_UNAVAILABLE"


class ObjectInvalidRequest(ValidationError):
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(ObjectErrorCode.INVALID_REQUEST, message, **details)


class ObjectNotFound(NotFoundError):
    def __init__(self, message: str = "the logical Object was not found", **details: Any) -> None:
        super().__init__(ObjectErrorCode.NOT_FOUND, message, **details)


class ConditionalConflict(ConflictError):
    def __init__(
        self, message: str = "the Object precondition did not match", **details: Any
    ) -> None:
        super().__init__(ObjectErrorCode.CONDITIONAL_CONFLICT, message, **details)


class ImmutableObjectConflict(ConflictError):
    def __init__(
        self, message: str = "the immutable Object cannot be replaced", **details: Any
    ) -> None:
        super().__init__(ObjectErrorCode.IMMUTABLE, message, **details)


class RetentionDenied(ConstraintError):
    def __init__(
        self, message: str = "retention policy does not permit this operation", **details: Any
    ) -> None:
        super().__init__(ObjectErrorCode.RETENTION_DENIED, message, **details)


class DigestMismatch(CorruptionError):
    def __init__(
        self, message: str = "the Object SHA-256 digest did not match", **details: Any
    ) -> None:
        super().__init__(ObjectErrorCode.DIGEST_MISMATCH, message, **details)


class IncompleteUpload(ValidationError):
    def __init__(
        self, message: str = "the upload ended before its declared length", **details: Any
    ) -> None:
        super().__init__(ObjectErrorCode.INCOMPLETE_UPLOAD, message, **details)


class PayloadUnavailable(UnavailableError):
    def __init__(
        self, message: str = "the in-process payload reference is unavailable", **details: Any
    ) -> None:
        super().__init__(ObjectErrorCode.PAYLOAD_UNAVAILABLE, message, **details)


class RangeNotSatisfiable(ValidationError):
    def __init__(
        self, message: str = "the requested byte range is not satisfiable", **details: Any
    ) -> None:
        super().__init__(ObjectErrorCode.RANGE_NOT_SATISFIABLE, message, **details)


class MultipartInvalid(ValidationError):
    def __init__(
        self, message: str = "the multipart upload contract is invalid", **details: Any
    ) -> None:
        super().__init__(ObjectErrorCode.MULTIPART_INVALID, message, **details)


class ObjectCapabilityMismatch(CompatibilityError):
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(ObjectErrorCode.CAPABILITY_MISMATCH, message, **details)


class ObjectAuthenticationFailed(AuthenticationError):
    def __init__(
        self, message: str = "Object Adapter authentication failed", **details: Any
    ) -> None:
        super().__init__(ObjectErrorCode.AUTHENTICATION, message, **details)


class ObjectAuthorizationFailed(AuthorizationError):
    def __init__(self, message: str = "Object operation is not authorized", **details: Any) -> None:
        super().__init__(ObjectErrorCode.AUTHORIZATION, message, **details)


class ObjectQuotaExceeded(ConstraintError):
    def __init__(self, message: str = "Object storage quota was exceeded", **details: Any) -> None:
        super().__init__(ObjectErrorCode.QUOTA, message, **details)


class ObjectRateLimited(RateLimitError):
    def __init__(self, message: str = "Object operation was rate limited", **details: Any) -> None:
        super().__init__(ObjectErrorCode.RATE_LIMIT, message, retryable=True, **details)


class TransferCancelled(TransientError):
    def __init__(self, message: str = "Object transfer was cancelled", **details: Any) -> None:
        super().__init__(ObjectErrorCode.TRANSFER_CANCELLED, message, **details)


class ObjectUnavailable(UnavailableError):
    def __init__(self, message: str = "Object endpoint is unavailable", **details: Any) -> None:
        super().__init__(ObjectErrorCode.UNAVAILABLE, message, retryable=True, **details)


_FAILURE_CLASSES: dict[str, type[MeridianError]] = {
    "authentication": ObjectAuthenticationFailed,
    "authorization": ObjectAuthorizationFailed,
    "conditional-conflict": ConditionalConflict,
    "corruption": DigestMismatch,
    "incomplete-upload": IncompleteUpload,
    "missing-object": ObjectNotFound,
    "quota": ObjectQuotaExceeded,
    "rate-limit": ObjectRateLimited,
    "retention-denied": RetentionDenied,
    "unavailable": ObjectUnavailable,
}


def classify_object_failure(
    kind: str, *, message: str | None = None, **details: Any
) -> MeridianError:
    """Map a safe provider failure kind to the stable public taxonomy."""

    failure_type = _FAILURE_CLASSES.get(kind)
    if failure_type is None:
        return ObjectUnavailable("Object Adapter returned an unclassified failure", **details)
    if message is None:
        return failure_type(**details)
    return failure_type(message, **details)


__all__ = [
    "ConditionalConflict",
    "DigestMismatch",
    "ImmutableObjectConflict",
    "IncompleteUpload",
    "MultipartInvalid",
    "ObjectAuthenticationFailed",
    "ObjectAuthorizationFailed",
    "ObjectCapabilityMismatch",
    "ObjectErrorCode",
    "ObjectInvalidRequest",
    "ObjectNotFound",
    "ObjectQuotaExceeded",
    "ObjectRateLimited",
    "ObjectUnavailable",
    "PayloadUnavailable",
    "RangeNotSatisfiable",
    "RetentionDenied",
    "TransferCancelled",
    "classify_object_failure",
]
