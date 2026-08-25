# SPDX-License-Identifier: Apache-2.0
"""Provider-neutral multipart Adapter SPI; never a consumer Catalog surface."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast, runtime_checkable

from meridian_storage.semantics import JsonValue, ObjectMetadata, ObjectReference

from meridian_storage import Operation

from .._validation import exact_fields, positive_int, token, utc_timestamp
from ..errors import MultipartInvalid
from ..metadata import ContentIdentity, parse_object_reference
from .payloads import PayloadReference, PayloadRegistry

MULTIPART_SESSION_FORMAT_VERSION = "meridian.object.multipart-session.v1"


@dataclass(frozen=True, slots=True)
class MultipartLimits:
    min_part_bytes: int
    max_part_bytes: int
    max_parts: int

    def __post_init__(self) -> None:
        minimum = positive_int(self.min_part_bytes, "minimum part bytes")
        maximum = positive_int(self.max_part_bytes, "maximum part bytes")
        positive_int(self.max_parts, "maximum parts")
        if minimum > maximum:
            raise MultipartInvalid("minimum part bytes exceeds maximum part bytes")

    def validate(self, *, part_size: int, total_length: int | None = None) -> int | None:
        size = positive_int(part_size, "part size")
        if not self.min_part_bytes <= size <= self.max_part_bytes:
            raise MultipartInvalid("part size is outside the advertised multipart limits")
        if total_length is None:
            return None
        if total_length < 0:
            raise MultipartInvalid("total length must be non-negative")
        count = max(1, (total_length + size - 1) // size)
        if count > self.max_parts:
            raise MultipartInvalid("multipart plan exceeds the advertised part-count limit")
        return count

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "minPartBytes": self.min_part_bytes,
            "maxPartBytes": self.max_part_bytes,
            "maxParts": self.max_parts,
        }


@dataclass(frozen=True, slots=True)
class MultipartSession:
    session_id: str
    object_ref: ObjectReference
    part_size: int
    expires_at: str | None = None
    format_version: str = MULTIPART_SESSION_FORMAT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", token(self.session_id, "multipart session id"))
        object.__setattr__(self, "object_ref", parse_object_reference(self.object_ref))
        object.__setattr__(self, "part_size", positive_int(self.part_size, "part size"))
        if self.expires_at is not None:
            object.__setattr__(self, "expires_at", utc_timestamp(self.expires_at, "session expiry"))
        if self.format_version != MULTIPART_SESSION_FORMAT_VERSION:
            raise ValueError(f"format_version must be {MULTIPART_SESSION_FORMAT_VERSION!r}")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "formatVersion": self.format_version,
            "sessionId": self.session_id,
            "objectRef": self.object_ref.to_dict(),
            "partSize": self.part_size,
            "expiresAt": self.expires_at,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> MultipartSession:
        exact_fields(value, {"formatVersion", "sessionId", "objectRef", "partSize", "expiresAt"})
        raw_ref = value["objectRef"]
        if not isinstance(raw_ref, Mapping):
            raise TypeError("multipart objectRef must be an object")
        return cls(
            session_id=cast(str, value["sessionId"]),
            object_ref=parse_object_reference(raw_ref),
            part_size=cast(int, value["partSize"]),
            expires_at=cast(str | None, value["expiresAt"]),
            format_version=cast(str, value["formatVersion"]),
        )


@dataclass(frozen=True, slots=True)
class MultipartPart:
    number: int
    identity: ContentIdentity
    verification_token: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "number", positive_int(self.number, "part number"))
        object.__setattr__(
            self,
            "verification_token",
            token(self.verification_token, "part verification token"),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "number": self.number,
            "identity": self.identity.to_dict(),
            "verificationToken": self.verification_token,
        }


@dataclass(frozen=True, slots=True)
class MultipartCompletion:
    parts: tuple[MultipartPart, ...]
    identity: ContentIdentity

    def __post_init__(self) -> None:
        parts = tuple(sorted(self.parts, key=lambda item: item.number))
        if not parts:
            raise MultipartInvalid("multipart completion requires at least one part")
        if tuple(item.number for item in parts) != tuple(range(1, len(parts) + 1)):
            raise MultipartInvalid("multipart part numbers must be contiguous from one")
        if sum(item.identity.byte_length for item in parts) != self.identity.byte_length:
            raise MultipartInvalid("multipart part lengths do not match the completed Object")
        object.__setattr__(self, "parts", parts)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "parts": [part.to_dict() for part in self.parts],
            "identity": self.identity.to_dict(),
        }


@runtime_checkable
class MultipartAdapter(Protocol):
    """Optional Adapter-internal transfer extension negotiated from put capability."""

    def begin_multipart(self, operation: Operation) -> MultipartSession: ...

    def upload_part(
        self,
        session: MultipartSession,
        part_number: int,
        payload: PayloadReference,
        payloads: PayloadRegistry,
    ) -> MultipartPart: ...

    def complete_multipart(
        self,
        session: MultipartSession,
        parts: Sequence[MultipartPart],
    ) -> ObjectMetadata: ...

    def abort_multipart(self, session: MultipartSession) -> None: ...


__all__ = [
    "MULTIPART_SESSION_FORMAT_VERSION",
    "MultipartAdapter",
    "MultipartCompletion",
    "MultipartLimits",
    "MultipartPart",
    "MultipartSession",
]
