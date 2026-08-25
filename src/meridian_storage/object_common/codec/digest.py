# SPDX-License-Identifier: Apache-2.0
"""Incremental SHA-256 content identity helpers."""

from __future__ import annotations

import hashlib

from ..errors import DigestMismatch
from ..metadata import ContentIdentity


class Sha256Accumulator:
    """Compute a portable content identity without retaining payload bytes."""

    def __init__(self) -> None:
        self._hasher = hashlib.sha256()
        self._length = 0
        self._finished = False

    @property
    def byte_length(self) -> int:
        return self._length

    def update(self, chunk: bytes | bytearray | memoryview) -> None:
        if self._finished:
            raise RuntimeError("content identity accumulator is already finalized")
        raw = bytes(chunk)
        self._hasher.update(raw)
        self._length += len(raw)

    def finish(self, *, expected_digest: str | None = None) -> ContentIdentity:
        if self._finished:
            raise RuntimeError("content identity accumulator is already finalized")
        self._finished = True
        identity = ContentIdentity(f"sha256:{self._hasher.hexdigest()}", self._length)
        if expected_digest is not None and identity.digest != expected_digest:
            raise DigestMismatch()
        return identity


__all__ = ["Sha256Accumulator"]
