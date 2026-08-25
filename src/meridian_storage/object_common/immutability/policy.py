# SPDX-License-Identifier: Apache-2.0
"""Consumer-selectable immutability and provider-neutral retention intent."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from meridian_storage.semantics import JsonValue, ObjectProfile, profile_from_mapping

from .._validation import bounded_string, exact_fields, utc_timestamp
from ..errors import ImmutableObjectConflict, RetentionDenied


@dataclass(frozen=True, slots=True)
class ImmutabilityRequest:
    mutability: str
    publish_once: bool = False

    def __post_init__(self) -> None:
        if self.mutability not in {"immutable", "mutable"}:
            raise ValueError("mutability must be immutable or mutable")
        if not isinstance(self.publish_once, bool):
            raise TypeError("publish_once must be boolean")
        if self.publish_once and self.mutability != "immutable":
            raise ValueError("publish-once requires immutable Object bytes")

    def to_dict(self) -> dict[str, JsonValue]:
        return {"mutability": self.mutability, "publishOnce": self.publish_once}

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ImmutabilityRequest:
        exact_fields(value, {"mutability", "publishOnce"})
        return cls(
            mutability=cast(str, value["mutability"]),
            publish_once=cast(bool, value["publishOnce"]),
        )


@dataclass(frozen=True, slots=True)
class RetentionRequest:
    """Portable retention intent; it makes no WORM or certification claim."""

    retain_until: str | datetime | None = None
    policy: str | None = None
    require_enforcement: bool = False

    def __post_init__(self) -> None:
        if self.retain_until is None and self.policy is None:
            raise ValueError("retention intent requires retain_until or a logical policy")
        if self.retain_until is not None:
            object.__setattr__(
                self,
                "retain_until",
                utc_timestamp(self.retain_until, "retention deadline"),
            )
        if self.policy is not None:
            object.__setattr__(self, "policy", bounded_string(self.policy, "retention policy", 256))
        if not isinstance(self.require_enforcement, bool):
            raise TypeError("require_enforcement must be boolean")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "retainUntil": cast(str | None, self.retain_until),
            "policy": self.policy,
            "requireEnforcement": self.require_enforcement,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> RetentionRequest:
        exact_fields(value, {"retainUntil", "policy", "requireEnforcement"})
        return cls(
            retain_until=cast(str | None, value["retainUntil"]),
            policy=cast(str | None, value["policy"]),
            require_enforcement=cast(bool, value["requireEnforcement"]),
        )

    def permits_delete(self, *, now: datetime | None = None) -> bool:
        if self.retain_until is None:
            return False
        selected = datetime.now(UTC) if now is None else now
        if selected.tzinfo is None or selected.utcoffset() is None:
            raise ValueError("deletion check time must be timezone-aware")
        deadline = datetime.strptime(cast(str, self.retain_until), "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=UTC
        )
        return selected.astimezone(UTC) >= deadline

    def require_delete_allowed(self, *, now: datetime | None = None) -> None:
        if not self.permits_delete(now=now):
            raise RetentionDenied()


def parse_object_profile(value: ObjectProfile | Mapping[str, object]) -> ObjectProfile:
    if isinstance(value, ObjectProfile):
        return ObjectProfile(
            profile=value.profile,
            mutability=value.mutability,
            range_reads=value.range_reads,
            conditional_create=value.conditional_create,
            bounded_prefix_list=value.bounded_prefix_list,
            metadata=value.metadata,
        )
    result = profile_from_mapping(value)
    if not isinstance(result, ObjectProfile):
        raise ValueError("Object Resource profile must be object, artifact, or media")
    return result


def effective_immutability(
    profile: ObjectProfile | Mapping[str, object],
    request: ImmutabilityRequest | Mapping[str, object] | None = None,
) -> ImmutabilityRequest:
    """Resolve per-put intent without weakening the Resource profile."""

    selected_profile = parse_object_profile(profile)
    selected = (
        ImmutabilityRequest(selected_profile.mutability, selected_profile.profile == "artifact")
        if request is None
        else request
        if isinstance(request, ImmutabilityRequest)
        else ImmutabilityRequest.from_mapping(request)
    )
    if selected_profile.profile == "artifact" and (
        selected.mutability != "immutable" or not selected.publish_once
    ):
        raise ImmutableObjectConflict("artifact Objects require immutable publish-once intent")
    if selected_profile.mutability == "immutable" and selected.mutability != "immutable":
        raise ImmutableObjectConflict("a put request cannot weaken Resource immutability")
    return selected


__all__ = [
    "ImmutabilityRequest",
    "RetentionRequest",
    "effective_immutability",
    "parse_object_profile",
]
