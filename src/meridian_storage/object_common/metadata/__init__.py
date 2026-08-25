# SPDX-License-Identifier: Apache-2.0
"""Content identity and released Object metadata interoperability."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from meridian_storage.semantics import (
    CatalogName,
    FrozenJson,
    JsonValue,
    ObjectMetadata,
    ObjectProfile,
    ObjectReference,
    ResourceReference,
)

from .._validation import digest, exact_fields, non_negative_int


@dataclass(frozen=True, slots=True)
class ContentIdentity:
    """Portable SHA-256 identity and observed byte length."""

    digest: str
    byte_length: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "digest", digest(self.digest))
        object.__setattr__(
            self,
            "byte_length",
            non_negative_int(self.byte_length, "byte length"),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {"digest": self.digest, "byteLength": self.byte_length}

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ContentIdentity:
        exact_fields(value, {"digest", "byteLength"})
        return cls(cast(str, value["digest"]), cast(int, value["byteLength"]))


def parse_object_reference(
    value: ObjectReference | Mapping[str, object],
    *,
    require_digest: bool = False,
) -> ObjectReference:
    if isinstance(value, ObjectReference):
        result = ObjectReference(value.resource_ref, value.object_id, value.digest)
    else:
        exact_fields(value, {"resourceRef", "objectId"}, {"digest"})
        raw_resource = value["resourceRef"]
        if not isinstance(raw_resource, Mapping):
            raise TypeError("Object resourceRef must be an object")
        resource = ResourceReference.parse(raw_resource, catalog=CatalogName.OBJECT)
        result = ObjectReference(
            resource,
            cast(str, value["objectId"]),
            cast(str | None, value.get("digest")),
        )
    if require_digest and result.digest is None:
        raise ValueError("an exact Object reference requires a digest")
    return result


def parse_object_metadata(value: ObjectMetadata | Mapping[str, object]) -> ObjectMetadata:
    if isinstance(value, ObjectMetadata):
        return ObjectMetadata(
            object_ref=value.object_ref,
            digest=value.digest,
            byte_length=value.byte_length,
            media_type=value.media_type,
            created_at=value.created_at,
            creation_context=value.creation_context,
            user_metadata=value.user_metadata,
            mutability=value.mutability,
            provenance=value.provenance,
            format_version=value.format_version,
        )
    required = {
        "formatVersion",
        "objectRef",
        "digest",
        "byteLength",
        "mediaType",
        "createdAt",
        "creationContext",
        "userMetadata",
        "mutability",
        "provenance",
    }
    exact_fields(value, required)
    raw_ref = value["objectRef"]
    if not isinstance(raw_ref, Mapping):
        raise TypeError("Object objectRef must be an object")
    for field in ("creationContext", "userMetadata", "provenance"):
        if not isinstance(value[field], Mapping):
            raise TypeError(f"Object {field} must be an object")
    return ObjectMetadata(
        object_ref=parse_object_reference(raw_ref),
        digest=cast(str, value["digest"]),
        byte_length=cast(int, value["byteLength"]),
        media_type=cast(str, value["mediaType"]),
        created_at=cast(str, value["createdAt"]),
        creation_context=cast(Mapping[str, FrozenJson], value["creationContext"]),
        user_metadata=cast(Mapping[str, str], value["userMetadata"]),
        mutability=cast(str, value["mutability"]),
        provenance=cast(Mapping[str, FrozenJson], value["provenance"]),
        format_version=cast(str, value["formatVersion"]),
    )


__all__ = [
    "ContentIdentity",
    "ObjectMetadata",
    "ObjectProfile",
    "ObjectReference",
    "parse_object_metadata",
    "parse_object_reference",
]
