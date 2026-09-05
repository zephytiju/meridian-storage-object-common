# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from meridian_storage.semantics import CatalogName, ObjectReference, ResourceReference

from meridian_storage.object_common import (
    HmacSha256Key,
    ObjectAuthorizationFailed,
    ObjectInvalidRequest,
    ReferenceSigner,
    SignedObjectReference,
    parse_logical_reference,
    sign_object_reference,
)

DIGEST = "sha256:" + "a" * 64
REFERENCE = ObjectReference(
    ResourceReference(CatalogName.OBJECT, "fixtures", "objects"),
    "item.bin",
    DIGEST,
)
EXPIRY = "2099-01-01T00:00:00.000000Z"


def _signed() -> tuple[HmacSha256Key, SignedObjectReference]:
    key = HmacSha256Key("key-1", b"x" * 32)
    signed = sign_object_reference(
        REFERENCE,
        allowed_operations=("stat", "get"),
        expires_at=EXPIRY,
        audience="fixture-reader",
        signer=key,
        nonce="nonce-1",
    )
    return key, signed


def test_signed_logical_reference_round_trip_and_verification() -> None:
    key, signed = _signed()
    assert isinstance(key, ReferenceSigner)
    assert signed.allowed_operations == ("get", "stat")
    assert signed.object_ref == REFERENCE
    assert "signature" not in signed.claims()
    assert SignedObjectReference.from_mapping(signed.to_dict()) == signed
    assert parse_logical_reference(signed.to_dict()) == signed
    assert parse_logical_reference(REFERENCE.to_dict()) == REFERENCE
    assert (
        signed.verify(
            key,
            operation="get",
            audience="fixture-reader",
            now=datetime(2026, 8, 25, tzinfo=UTC),
        )
        == REFERENCE
    )


def test_hmac_key_validation_and_redaction() -> None:
    key = HmacSha256Key("key-1", bytearray(b"x" * 32))
    assert key.algorithm == "hmac-sha256"
    assert key.key_id == "key-1"
    assert key.verify(b"message", key.sign(b"message"))
    assert not key.verify(b"message", b"bad")
    assert "<redacted>" in repr(key)
    assert "xxxxxxxx" not in repr(key)
    with pytest.raises(ValueError, match="at least 32"):
        HmacSha256Key("key", b"too short")
    with pytest.raises(ValueError, match="not a URL"):
        HmacSha256Key("https://key", b"x" * 32)


@pytest.mark.parametrize(
    ("mutation", "operation", "audience", "now", "match"),
    [
        ("wrong-key", "get", "fixture-reader", datetime(2026, 1, 1, tzinfo=UTC), "key identity"),
        ("same-key", "read_range", "fixture-reader", datetime(2026, 1, 1, tzinfo=UTC), "permit"),
        ("same-key", "get", "wrong", datetime(2026, 1, 1, tzinfo=UTC), "audience"),
        ("same-key", "get", "fixture-reader", datetime(2100, 1, 1, tzinfo=UTC), "expired"),
    ],
)
def test_signed_reference_rejects_authorization_mismatch(
    mutation: str,
    operation: str,
    audience: str,
    now: datetime,
    match: str,
) -> None:
    key, signed = _signed()
    selected_key = HmacSha256Key("key-2", b"y" * 32) if mutation == "wrong-key" else key
    with pytest.raises(ObjectAuthorizationFailed, match=match):
        signed.verify(selected_key, operation=operation, audience=audience, now=now)


def test_signed_reference_rejects_tampering_and_naive_time() -> None:
    key, signed = _signed()
    tampered = replace(signed, audience="another-reader")
    with pytest.raises(ObjectAuthorizationFailed, match="signature"):
        tampered.verify(
            key,
            operation="get",
            audience="another-reader",
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        signed.verify(
            key,
            operation="get",
            audience="fixture-reader",
            now=datetime(2026, 1, 1),
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"allowed_operations": ()},
        {"allowed_operations": ("delete",)},
        {"object_ref": ObjectReference(REFERENCE.resource_ref, REFERENCE.object_id)},
        {"signature": "not+base64"},
        {"format_version": "future"},
    ],
)
def test_signed_reference_shape_validation(kwargs: dict[str, object]) -> None:
    _, signed = _signed()
    values = {
        "object_ref": signed.object_ref,
        "allowed_operations": signed.allowed_operations,
        "expires_at": signed.expires_at,
        "audience": signed.audience,
        "nonce": signed.nonce,
        "key_id": signed.key_id,
        "algorithm": signed.algorithm,
        "signature": signed.signature,
        "format_version": signed.format_version,
    }
    values.update(kwargs)
    with pytest.raises(ValueError):
        SignedObjectReference(**values)  # type: ignore[arg-type]


class _EmptySigner:
    key_id = "key-1"
    algorithm = "test"

    def sign(self, value: bytes) -> bytes:
        del value
        return b""

    def verify(self, value: bytes, signature: bytes) -> bool:
        del value, signature
        return False


def test_signing_boundary_rejects_invalid_signers_and_references() -> None:
    with pytest.raises(TypeError, match="does not implement"):
        sign_object_reference(
            REFERENCE,
            allowed_operations=("get",),
            expires_at=EXPIRY,
            audience="reader",
            signer=object(),  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="empty signature"):
        sign_object_reference(
            REFERENCE,
            allowed_operations=("get",),
            expires_at=EXPIRY,
            audience="reader",
            signer=_EmptySigner(),
        )
    with pytest.raises(ObjectInvalidRequest, match="invalid logical"):
        parse_logical_reference({"resourceRef": "invalid", "objectId": "x"})


def test_generated_nonce_always_satisfies_the_opaque_token_contract() -> None:
    key = HmacSha256Key("key-1", b"x" * 32)
    for _ in range(200):
        signed = sign_object_reference(
            REFERENCE,
            allowed_operations=("get",),
            expires_at=EXPIRY,
            audience="reader",
            signer=key,
        )
        assert SignedObjectReference.from_mapping(signed.to_dict()) == signed
