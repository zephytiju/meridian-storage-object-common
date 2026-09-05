# SPDX-License-Identifier: Apache-2.0
"""Bounded streaming payload registry kept outside Core's JSON envelope."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from threading import RLock
from typing import BinaryIO, Protocol, cast, runtime_checkable

from meridian_storage.semantics import JsonValue

from .._validation import digest, exact_fields, non_negative_int, positive_int, token
from ..errors import (
    DigestMismatch,
    IncompleteUpload,
    ObjectInvalidRequest,
    PayloadUnavailable,
    TransferCancelled,
)
from ..metadata import ContentIdentity

PAYLOAD_REFERENCE_FORMAT_VERSION = "meridian.object.payload-reference.v1"
DEFAULT_CHUNK_SIZE = 1024 * 1024
MAX_CHUNK_SIZE = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class PayloadReference:
    """Serialized handle for in-process bytes; it is never an endpoint or physical locator."""

    token: str
    expected_length: int | None = None
    expected_digest: str | None = None
    replayable: bool = False
    format_version: str = PAYLOAD_REFERENCE_FORMAT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "token", token(self.token, "payload token"))
        if self.expected_length is not None:
            object.__setattr__(
                self,
                "expected_length",
                non_negative_int(self.expected_length, "expected payload length"),
            )
        if self.expected_digest is not None:
            object.__setattr__(
                self,
                "expected_digest",
                digest(self.expected_digest, "expected payload digest"),
            )
        if not isinstance(self.replayable, bool):
            raise TypeError("payload replayable must be boolean")
        if self.format_version != PAYLOAD_REFERENCE_FORMAT_VERSION:
            raise ValueError(f"format_version must be {PAYLOAD_REFERENCE_FORMAT_VERSION!r}")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "formatVersion": self.format_version,
            "token": self.token,
            "expectedLength": self.expected_length,
            "expectedDigest": self.expected_digest,
            "replayable": self.replayable,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> PayloadReference:
        exact_fields(
            value,
            {"formatVersion", "token", "expectedLength", "expectedDigest", "replayable"},
        )
        return cls(
            token=cast(str, value["token"]),
            expected_length=cast(int | None, value["expectedLength"]),
            expected_digest=cast(str | None, value["expectedDigest"]),
            replayable=cast(bool, value["replayable"]),
            format_version=cast(str, value["formatVersion"]),
        )


@runtime_checkable
class PayloadSource(Protocol):
    @property
    def replayable(self) -> bool: ...

    def open(self) -> AbstractContextManager[BinaryIO]: ...


@runtime_checkable
class BinarySink(Protocol):
    def write(self, data: bytes) -> int | None: ...


class StreamPayloadSource:
    """Wrap one caller-owned stream without buffering or silently reopening it."""

    def __init__(self, stream: BinaryIO) -> None:
        if not hasattr(stream, "read"):
            raise TypeError("stream payload source requires a binary read method")
        self._stream = stream
        self._consumed = False
        self._lock = RLock()

    @property
    def replayable(self) -> bool:
        return False

    @contextmanager
    def open(self) -> Iterator[BinaryIO]:
        with self._lock:
            if self._consumed:
                raise PayloadUnavailable("the non-replayable payload was already opened")
            self._consumed = True
        yield self._stream


class FactoryPayloadSource:
    """Open a fresh binary stream for each read and close it afterward."""

    def __init__(self, factory: Callable[[], BinaryIO], *, replayable: bool = True) -> None:
        if not callable(factory):
            raise TypeError("payload factory must be callable")
        self._factory = factory
        self._replayable = replayable
        self._opened = False
        self._lock = RLock()

    @property
    def replayable(self) -> bool:
        return self._replayable

    @contextmanager
    def open(self) -> Iterator[BinaryIO]:
        with self._lock:
            if not self._replayable and self._opened:
                raise PayloadUnavailable("the non-replayable payload factory was already opened")
            self._opened = True
        stream = self._factory()
        if not hasattr(stream, "read"):
            raise TypeError("payload factory must return a binary stream")
        try:
            yield stream
        finally:
            stream.close()


class PayloadRegistry:
    """Explicit process-local resolver shared by a consumer and an Object Adapter."""

    def __init__(self) -> None:
        self._sources: dict[str, PayloadSource] = {}
        self._lock = RLock()

    def register(
        self,
        source: PayloadSource,
        *,
        expected_length: int | None = None,
        expected_digest: str | None = None,
    ) -> PayloadReference:
        if not isinstance(source, PayloadSource):
            raise TypeError("payload source does not implement the PayloadSource contract")
        opaque_token = f"p_{secrets.token_urlsafe(32)}"
        reference = PayloadReference(
            opaque_token,
            expected_length=expected_length,
            expected_digest=expected_digest,
            replayable=source.replayable,
        )
        with self._lock:
            self._sources[reference.token] = source
        return reference

    def register_stream(
        self,
        stream: BinaryIO,
        *,
        expected_length: int | None = None,
        expected_digest: str | None = None,
    ) -> PayloadReference:
        return self.register(
            StreamPayloadSource(stream),
            expected_length=expected_length,
            expected_digest=expected_digest,
        )

    @contextmanager
    def open(self, reference: PayloadReference | Mapping[str, object]) -> Iterator[BinaryIO]:
        parsed = (
            reference
            if isinstance(reference, PayloadReference)
            else PayloadReference.from_mapping(reference)
        )
        with self._lock:
            source = self._sources.get(parsed.token)
            if source is None:
                raise PayloadUnavailable()
            if source.replayable != parsed.replayable:
                raise PayloadUnavailable(
                    "payload reference replayability does not match its source"
                )
            if not source.replayable:
                self._sources.pop(parsed.token, None)
        with source.open() as stream:
            yield stream

    def release(self, reference: PayloadReference | str) -> bool:
        selected = reference.token if isinstance(reference, PayloadReference) else reference
        selected = token(selected, "payload token")
        with self._lock:
            return self._sources.pop(selected, None) is not None

    def __len__(self) -> int:
        with self._lock:
            return len(self._sources)


class _DefaultPayloadRegistry(PayloadRegistry):
    def __bool__(self) -> bool:
        # Preserve injection through released constructors using ``x or default``.
        return True


_DEFAULT_PAYLOADS = _DefaultPayloadRegistry()


def default_payload_registry() -> PayloadRegistry:
    """Resolve process-local handles for default Object consumers and Adapters.

    Explicitly constructed registries remain independent. Callers own registered
    payloads and must release replayable handles after their final use.
    """
    return _DEFAULT_PAYLOADS


def iter_payload_chunks(
    stream: BinaryIO, *, chunk_size: int = DEFAULT_CHUNK_SIZE
) -> Iterator[bytes]:
    size = positive_int(chunk_size, "chunk size")
    if size > MAX_CHUNK_SIZE:
        raise ObjectInvalidRequest(f"chunk size exceeds the {MAX_CHUNK_SIZE}-byte safety bound")
    while True:
        chunk = stream.read(size)
        if chunk == b"":
            return
        if not isinstance(chunk, (bytes, bytearray, memoryview)):
            raise TypeError("binary payload streams must return bytes-like chunks")
        raw = bytes(chunk)
        if not raw:
            return
        if len(raw) > size:
            raise ObjectInvalidRequest("payload stream returned more bytes than requested")
        yield raw


def transfer_payload(
    reference: PayloadReference | Mapping[str, object],
    registry: PayloadRegistry,
    sink: BinarySink,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    cancelled: Callable[[], bool] | None = None,
) -> ContentIdentity:
    """Stream once, compute SHA-256, and verify all declared integrity inputs."""

    parsed = (
        reference
        if isinstance(reference, PayloadReference)
        else PayloadReference.from_mapping(reference)
    )
    hasher = hashlib.sha256()
    length = 0
    with registry.open(parsed) as stream:
        for chunk in iter_payload_chunks(stream, chunk_size=chunk_size):
            if cancelled is not None and cancelled():
                raise TransferCancelled()
            written = sink.write(chunk)
            if written is not None and written != len(chunk):
                raise IncompleteUpload("the payload sink accepted only part of a chunk")
            hasher.update(chunk)
            length += len(chunk)
            if parsed.expected_length is not None and length > parsed.expected_length:
                raise IncompleteUpload("the upload exceeded its declared length")
    if parsed.expected_length is not None and length != parsed.expected_length:
        raise IncompleteUpload()
    observed = f"sha256:{hasher.hexdigest()}"
    if parsed.expected_digest is not None and observed != parsed.expected_digest:
        raise DigestMismatch()
    return ContentIdentity(observed, length)


__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "MAX_CHUNK_SIZE",
    "PAYLOAD_REFERENCE_FORMAT_VERSION",
    "BinarySink",
    "FactoryPayloadSource",
    "PayloadReference",
    "PayloadRegistry",
    "PayloadSource",
    "StreamPayloadSource",
    "default_payload_registry",
    "iter_payload_chunks",
    "transfer_payload",
]
