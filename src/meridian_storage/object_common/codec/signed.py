# SPDX-License-Identifier: Apache-2.0
"""Signed logical Object references with no provider URL or credential material."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol, cast, runtime_checkable

from meridian_storage.semantics import JsonValue, ObjectReference, canonical_json_bytes

from .._validation import bounded_string, exact_fields, string_sequence, token, utc_timestamp
from ..errors import ObjectAuthorizationFailed, ObjectInvalidRequest
from ..metadata import parse_object_reference

SIGNED_REFERENCE_FORMAT_VERSION = "meridian.object.signed-reference.v1"
SIGNED_REFERENCE_OPERATIONS = frozenset({"get", "read_range", "stat"})


@runtime_checkable
class ReferenceSigner(Protocol):
    @property
    def key_id(self) -> str: ...

    @property
    def algorithm(self) -> str: ...

    def sign(self, value: bytes) -> bytes: ...

    def verify(self, value: bytes, signature: bytes) -> bool: ...


class HmacSha256Key:
    """In-memory signer for local composition; key provisioning remains external."""

    __slots__ = ("_key", "_key_id")

    def __init__(self, key_id: str, key: bytes | bytearray | memoryview) -> None:
        raw = bytes(key)
        if len(raw) < 32:
            raise ValueError("HMAC-SHA256 signing keys must contain at least 32 bytes")
        self._key_id = token(key_id, "signing key id")
        self._key = raw

    @property
    def key_id(self) -> str:
        return self._key_id

    @property
    def algorithm(self) -> str:
        return "hmac-sha256"

    def sign(self, value: bytes) -> bytes:
        return hmac.new(self._key, value, hashlib.sha256).digest()

    def verify(self, value: bytes, signature: bytes) -> bool:
        return hmac.compare_digest(self.sign(value), signature)

    def __repr__(self) -> str:
        return f"HmacSha256Key(key_id={self.key_id!r}, key=<redacted>)"


@dataclass(frozen=True, slots=True)
class SignedObjectReference:
    object_ref: ObjectReference
    allowed_operations: tuple[str, ...]
    expires_at: str | datetime
    audience: str
    nonce: str
    key_id: str
    algorithm: str
    signature: str
    format_version: str = SIGNED_REFERENCE_FORMAT_VERSION

    def __post_init__(self) -> None:
        reference = parse_object_reference(self.object_ref, require_digest=True)
        operations = string_sequence(self.allowed_operations, "signed reference operations")
        if not operations or not set(operations) <= SIGNED_REFERENCE_OPERATIONS:
            raise ValueError("signed Object references permit only get, read_range, and stat")
        object.__setattr__(self, "object_ref", reference)
        object.__setattr__(self, "allowed_operations", operations)
        object.__setattr__(self, "expires_at", utc_timestamp(self.expires_at, "reference expiry"))
        object.__setattr__(
            self, "audience", bounded_string(self.audience, "reference audience", 256)
        )
        object.__setattr__(self, "nonce", token(self.nonce, "reference nonce"))
        object.__setattr__(self, "key_id", token(self.key_id, "signing key id"))
        object.__setattr__(self, "algorithm", token(self.algorithm, "signing algorithm"))
        object.__setattr__(self, "signature", _signature_string(self.signature))
        if self.format_version != SIGNED_REFERENCE_FORMAT_VERSION:
            raise ValueError(f"format_version must be {SIGNED_REFERENCE_FORMAT_VERSION!r}")

    def claims(self) -> dict[str, JsonValue]:
        return {
            "formatVersion": self.format_version,
            "objectRef": self.object_ref.to_dict(),
            "allowedOperations": list(self.allowed_operations),
            "expiresAt": cast(str, self.expires_at),
            "audience": self.audience,
            "nonce": self.nonce,
            "keyId": self.key_id,
            "algorithm": self.algorithm,
        }

    def to_dict(self) -> dict[str, JsonValue]:
        return {**self.claims(), "signature": self.signature}

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> SignedObjectReference:
        exact_fields(
            value,
            {
                "formatVersion",
                "objectRef",
                "allowedOperations",
                "expiresAt",
                "audience",
                "nonce",
                "keyId",
                "algorithm",
                "signature",
            },
        )
        raw_ref = value["objectRef"]
        raw_operations = value["allowedOperations"]
        if not isinstance(raw_ref, Mapping):
            raise TypeError("signed Object objectRef must be an object")
        if not isinstance(raw_operations, Sequence) or isinstance(raw_operations, (str, bytes)):
            raise TypeError("signed Object allowedOperations must be an array")
        return cls(
            object_ref=parse_object_reference(raw_ref, require_digest=True),
            allowed_operations=tuple(cast(Sequence[str], raw_operations)),
            expires_at=cast(str, value["expiresAt"]),
            audience=cast(str, value["audience"]),
            nonce=cast(str, value["nonce"]),
            key_id=cast(str, value["keyId"]),
            algorithm=cast(str, value["algorithm"]),
            signature=cast(str, value["signature"]),
            format_version=cast(str, value["formatVersion"]),
        )

    def verify(
        self,
        signer: ReferenceSigner,
        *,
        operation: str,
        audience: str,
        now: datetime | None = None,
    ) -> ObjectReference:
        if signer.key_id != self.key_id or signer.algorithm != self.algorithm:
            raise ObjectAuthorizationFailed("signed Object reference key identity does not match")
        if operation not in self.allowed_operations:
            raise ObjectAuthorizationFailed("signed Object reference does not permit the operation")
        if audience != self.audience:
            raise ObjectAuthorizationFailed("signed Object reference audience does not match")
        selected = datetime.now(UTC) if now is None else now
        if selected.tzinfo is None or selected.utcoffset() is None:
            raise ValueError("reference verification time must be timezone-aware")
        expiry = datetime.strptime(cast(str, self.expires_at), "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=UTC
        )
        if selected.astimezone(UTC) >= expiry:
            raise ObjectAuthorizationFailed("signed Object reference has expired")
        signature = _decode_signature(self.signature)
        if not signer.verify(canonical_json_bytes(self.claims()), signature):
            raise ObjectAuthorizationFailed("signed Object reference signature is invalid")
        return self.object_ref


def sign_object_reference(
    object_ref: ObjectReference | Mapping[str, object],
    *,
    allowed_operations: Sequence[str],
    expires_at: str | datetime,
    audience: str,
    signer: ReferenceSigner,
    nonce: str | None = None,
) -> SignedObjectReference:
    if not isinstance(signer, ReferenceSigner):
        raise TypeError("signer does not implement the ReferenceSigner contract")
    reference = parse_object_reference(object_ref, require_digest=True)
    selected_nonce = nonce or f"n_{secrets.token_hex(24)}"
    unsigned = SignedObjectReference(
        object_ref=reference,
        allowed_operations=tuple(allowed_operations),
        expires_at=expires_at,
        audience=audience,
        nonce=selected_nonce,
        key_id=signer.key_id,
        algorithm=signer.algorithm,
        signature="AA",
    )
    signature = _encode_signature(signer.sign(canonical_json_bytes(unsigned.claims())))
    return replace(unsigned, signature=signature)


def parse_logical_reference(
    value: ObjectReference | SignedObjectReference | Mapping[str, object],
) -> ObjectReference | SignedObjectReference:
    if isinstance(value, (ObjectReference, SignedObjectReference)):
        return value
    if value.get("formatVersion") == SIGNED_REFERENCE_FORMAT_VERSION:
        return SignedObjectReference.from_mapping(value)
    try:
        return parse_object_reference(value)
    except (TypeError, ValueError) as exc:
        raise ObjectInvalidRequest(f"invalid logical Object reference: {exc}") from exc


def _encode_signature(value: bytes) -> str:
    if not value:
        raise ValueError("reference signer returned an empty signature")
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _signature_string(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ValueError("signature must be bounded base64url")
    _decode_signature(value)
    return value


def _decode_signature(value: str) -> bytes:
    if re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise ValueError("signature must be base64url")
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise ValueError("signature must be base64url") from exc
    if not raw:
        raise ValueError("signature must not be empty")
    return raw


__all__ = [
    "SIGNED_REFERENCE_FORMAT_VERSION",
    "SIGNED_REFERENCE_OPERATIONS",
    "HmacSha256Key",
    "ReferenceSigner",
    "SignedObjectReference",
    "parse_logical_reference",
    "sign_object_reference",
]
