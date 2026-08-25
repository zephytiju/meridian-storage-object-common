# SPDX-License-Identifier: Apache-2.0
"""Small validation helpers shared by the public Object contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence, Set
from datetime import UTC, datetime
from typing import Any, cast

from meridian_storage.semantics import JsonValue

DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._~-]{0,510}[A-Za-z0-9])?$")
MEDIA_TYPE_RE = re.compile(r"^[^/\s]+/[^/\s]+$")
TIMESTAMP_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$")

_PRIVATE_KEYS = {
    "accesskey",
    "acl",
    "adapter",
    "adapterid",
    "bucket",
    "cloudcredential",
    "credential",
    "credentials",
    "endpoint",
    "engine",
    "engineid",
    "kmskey",
    "lifecycle",
    "password",
    "physicalkey",
    "physicallocator",
    "region",
    "repository",
    "secret",
    "secretkey",
    "storagebinding",
}


def bounded_string(value: object, field: str, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    if len(value.encode("utf-8")) > maximum:
        raise ValueError(f"{field} exceeds {maximum} UTF-8 bytes")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{field} contains a control character")
    return value


def token(value: object, field: str, maximum: int = 512) -> str:
    result = bounded_string(value, field, maximum)
    if TOKEN_RE.fullmatch(result) is None:
        raise ValueError(f"{field} must be an opaque token, not a URL or physical locator")
    return result


def digest(value: object, field: str = "digest") -> str:
    if not isinstance(value, str) or DIGEST_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be sha256:<lowercase hex>")
    return value


def media_type(value: object) -> str:
    result = bounded_string(value, "media type", 255)
    if MEDIA_TYPE_RE.fullmatch(result) is None:
        raise ValueError("media type must contain one type/subtype separator")
    return result


def non_negative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def positive_int(value: object, field: str) -> int:
    result = non_negative_int(value, field)
    if result == 0:
        raise ValueError(f"{field} must be positive")
    return result


def utc_timestamp(value: str | datetime, field: str = "timestamp") -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} must be timezone-aware")
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if not isinstance(value, str) or TIMESTAMP_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be UTC RFC 3339 with six fractional digits")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ValueError(f"{field} is not a valid UTC instant") from exc
    return value


def string_mapping(
    value: object,
    field: str,
    *,
    maximum_entries: int,
    maximum_key_bytes: int,
    maximum_value_bytes: int,
) -> dict[str, str]:
    if not isinstance(value, Mapping) or len(value) > maximum_entries:
        raise ValueError(f"{field} exceeds its entry bound")
    result: dict[str, str] = {}
    for key, item in value.items():
        result[bounded_string(key, f"{field} key", maximum_key_bytes)] = bounded_string(
            item, f"{field} value", maximum_value_bytes
        )
    return dict(sorted(result.items()))


def json_mapping(value: object, field: str) -> dict[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be an object")
    return cast(dict[str, JsonValue], dict(value))


def string_sequence(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{field} must be an array")
    result = tuple(sorted(bounded_string(item, field, 128) for item in value))
    if len(set(result)) != len(result):
        raise ValueError(f"{field} entries must be unique")
    return result


def reject_private_configuration(value: object, path: str = "arguments") -> None:
    """Reject deployment, provider, credential, ACL, and lifecycle data from public values."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} keys must be strings")
            normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
            if normalized in _PRIVATE_KEYS:
                raise ValueError(f"{path}.{key} belongs to private Adapter or IaC configuration")
            reject_private_configuration(item, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            reject_private_configuration(item, f"{path}[{index}]")


def exact_fields(
    value: Mapping[str, Any],
    required: Set[str],
    optional: Set[str] = frozenset(),
) -> None:
    missing = required - set(value)
    unknown = set(value) - required - optional
    if missing or unknown:
        raise ValueError(f"missing fields {sorted(missing)!r}; unknown fields {sorted(unknown)!r}")
