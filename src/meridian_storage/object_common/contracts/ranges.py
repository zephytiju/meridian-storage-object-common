# SPDX-License-Identifier: Apache-2.0
"""Portable inclusive byte-range contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from meridian_storage.semantics import JsonValue

from .._validation import exact_fields, non_negative_int, positive_int
from ..errors import RangeNotSatisfiable


@dataclass(frozen=True, slots=True)
class ResolvedByteRange:
    start: int
    end: int
    total_length: int

    def __post_init__(self) -> None:
        start = non_negative_int(self.start, "range start")
        end = non_negative_int(self.end, "range end")
        total = non_negative_int(self.total_length, "total length")
        if total == 0 or start > end or end >= total:
            raise RangeNotSatisfiable()

    @property
    def length(self) -> int:
        return self.end - self.start + 1

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "start": self.start,
            "end": self.end,
            "length": self.length,
            "totalLength": self.total_length,
        }


@dataclass(frozen=True, slots=True)
class ByteRange:
    """A zero-based inclusive range or a positive suffix length."""

    start: int | None = None
    end: int | None = None
    suffix_length: int | None = None

    def __post_init__(self) -> None:
        if self.suffix_length is not None:
            if self.start is not None or self.end is not None:
                raise ValueError("suffix ranges cannot include start or end")
            object.__setattr__(
                self,
                "suffix_length",
                positive_int(self.suffix_length, "suffix length"),
            )
            return
        if self.start is None:
            raise ValueError("a non-suffix range requires start")
        start = non_negative_int(self.start, "range start")
        if self.end is not None:
            end = non_negative_int(self.end, "range end")
            if end < start:
                raise ValueError("range end must not precede start")

    @property
    def requested_length(self) -> int | None:
        if self.suffix_length is not None:
            return self.suffix_length
        if self.end is None:
            return None
        assert self.start is not None
        return self.end - self.start + 1

    def resolve(self, total_length: int) -> ResolvedByteRange:
        total = non_negative_int(total_length, "total length")
        if total == 0:
            raise RangeNotSatisfiable()
        if self.suffix_length is not None:
            length = min(self.suffix_length, total)
            return ResolvedByteRange(total - length, total - 1, total)
        assert self.start is not None
        if self.start >= total:
            raise RangeNotSatisfiable()
        end = total - 1 if self.end is None else min(self.end, total - 1)
        return ResolvedByteRange(self.start, end, total)

    def to_dict(self) -> dict[str, JsonValue]:
        if self.suffix_length is not None:
            return {"suffixLength": self.suffix_length}
        result: dict[str, JsonValue] = {"start": self.start}
        if self.end is not None:
            result["end"] = self.end
        return result

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ByteRange:
        if "suffixLength" in value:
            exact_fields(value, {"suffixLength"})
            return cls(suffix_length=cast(int, value["suffixLength"]))
        exact_fields(value, {"start"}, {"end"})
        return cls(
            start=cast(int, value["start"]),
            end=cast(int | None, value.get("end")),
        )


__all__ = ["ByteRange", "ResolvedByteRange"]
