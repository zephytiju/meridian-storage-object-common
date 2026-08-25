# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
from contextlib import nullcontext
from io import BytesIO
from typing import BinaryIO, cast

import pytest

from meridian_storage.object_common import (
    DigestMismatch,
    FactoryPayloadSource,
    IncompleteUpload,
    ObjectInvalidRequest,
    PayloadReference,
    PayloadRegistry,
    PayloadSource,
    PayloadUnavailable,
    Sha256Accumulator,
    StreamPayloadSource,
    TransferCancelled,
    iter_payload_chunks,
    transfer_payload,
)


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def test_payload_reference_round_trip_and_validation() -> None:
    reference = PayloadReference(
        "p_example",
        expected_length=3,
        expected_digest=_digest(b"abc"),
        replayable=True,
    )
    assert PayloadReference.from_mapping(reference.to_dict()) == reference

    with pytest.raises(ValueError, match="not a URL"):
        PayloadReference("https://provider.example/object")
    with pytest.raises(ValueError, match="non-negative"):
        PayloadReference("token", expected_length=-1)
    with pytest.raises(ValueError, match="sha256"):
        PayloadReference("token", expected_digest="SHA256:bad")
    with pytest.raises(TypeError, match="boolean"):
        PayloadReference("token", replayable=cast(bool, 1))
    with pytest.raises(ValueError, match="format_version"):
        PayloadReference("token", format_version="future")
    with pytest.raises(ValueError, match="missing fields"):
        PayloadReference.from_mapping({"formatVersion": "meridian.object.payload-reference.v1"})


def test_stream_source_and_registry_are_explicitly_one_shot() -> None:
    source = StreamPayloadSource(BytesIO(b"abc"))
    assert isinstance(source, PayloadSource)
    registry = PayloadRegistry()
    reference = registry.register(source)
    assert len(registry) == 1
    with registry.open(reference) as stream:
        assert stream.read() == b"abc"
    assert len(registry) == 0
    with pytest.raises(PayloadUnavailable):
        registry.open(reference).__enter__()
    with pytest.raises(PayloadUnavailable, match="already opened"):
        source.open().__enter__()


def test_factory_source_replayability_closure_and_release() -> None:
    streams: list[BytesIO] = []

    def factory() -> BytesIO:
        stream = BytesIO(b"value")
        streams.append(stream)
        return stream

    registry = PayloadRegistry()
    reference = registry.register(FactoryPayloadSource(factory))
    for _ in range(2):
        with registry.open(reference) as stream:
            assert stream.read() == b"value"
        assert streams[-1].closed
    assert registry.release(reference)
    assert not registry.release(reference.token)
    assert len(registry) == 0

    one_shot = FactoryPayloadSource(factory, replayable=False)
    with one_shot.open() as stream:
        assert stream.read() == b"value"
    with pytest.raises(PayloadUnavailable, match="already opened"):
        one_shot.open().__enter__()


def test_registry_rejects_bad_sources_and_tampered_handles() -> None:
    registry = PayloadRegistry()
    with pytest.raises(TypeError, match="does not implement"):
        registry.register(object())  # type: ignore[arg-type]
    reference = registry.register(FactoryPayloadSource(lambda: BytesIO(b"ok")))
    tampered = PayloadReference(reference.token, replayable=False)
    with pytest.raises(PayloadUnavailable, match="replayability"):
        registry.open(tampered).__enter__()

    with pytest.raises(ValueError, match="not a URL"):
        registry.release("https://invalid")


class _NonBinaryStream:
    def read(self, size: int) -> str:
        del size
        return "text"


class _OverproducingStream:
    def read(self, size: int) -> bytes:
        return b"x" * (size + 1)


class _BadSource:
    replayable = True

    def open(self) -> nullcontext[object]:
        return nullcontext(object())


def test_chunk_iterator_enforces_bounds_and_binary_streams() -> None:
    assert list(iter_payload_chunks(BytesIO(b"abcdef"), chunk_size=2)) == [b"ab", b"cd", b"ef"]
    with pytest.raises(ValueError, match="positive"):
        list(iter_payload_chunks(BytesIO(b"x"), chunk_size=0))
    with pytest.raises(ObjectInvalidRequest, match="safety bound"):
        list(iter_payload_chunks(BytesIO(b"x"), chunk_size=17 * 1024 * 1024))
    with pytest.raises(TypeError, match="bytes-like"):
        list(iter_payload_chunks(cast(BinaryIO, _NonBinaryStream()), chunk_size=2))
    with pytest.raises(ObjectInvalidRequest, match="more bytes"):
        list(iter_payload_chunks(cast(BinaryIO, _OverproducingStream()), chunk_size=2))

    with (
        pytest.raises(TypeError, match="binary stream"),
        FactoryPayloadSource(lambda: cast(BinaryIO, object())).open(),
    ):
        pass


def test_transfer_payload_success_and_integrity_failures() -> None:
    data = b"streamed payload"
    registry = PayloadRegistry()
    reference = registry.register(
        FactoryPayloadSource(lambda: BytesIO(data)),
        expected_length=len(data),
        expected_digest=_digest(data),
    )
    sink = BytesIO()
    identity = transfer_payload(reference.to_dict(), registry, sink, chunk_size=3)
    assert sink.getvalue() == data
    assert identity.digest == _digest(data)
    assert identity.byte_length == len(data)

    too_short = registry.register(
        FactoryPayloadSource(lambda: BytesIO(data)),
        expected_length=len(data) + 1,
    )
    with pytest.raises(IncompleteUpload, match="ended before"):
        transfer_payload(too_short, registry, BytesIO())

    too_long = registry.register(
        FactoryPayloadSource(lambda: BytesIO(data)),
        expected_length=1,
    )
    with pytest.raises(IncompleteUpload, match="exceeded"):
        transfer_payload(too_long, registry, BytesIO(), chunk_size=2)

    bad_digest = registry.register(
        FactoryPayloadSource(lambda: BytesIO(data)),
        expected_digest="sha256:" + "0" * 64,
    )
    with pytest.raises(DigestMismatch):
        transfer_payload(bad_digest, registry, BytesIO())


class _PartialSink:
    def write(self, data: bytes) -> int:
        return len(data) - 1


def test_transfer_payload_handles_partial_sink_and_cancellation() -> None:
    registry = PayloadRegistry()
    partial = registry.register(FactoryPayloadSource(lambda: BytesIO(b"abc")))
    with pytest.raises(IncompleteUpload, match="part of a chunk"):
        transfer_payload(partial, registry, _PartialSink())

    cancelled = registry.register(FactoryPayloadSource(lambda: BytesIO(b"abc")))
    with pytest.raises(TransferCancelled):
        transfer_payload(cancelled, registry, BytesIO(), cancelled=lambda: True)


def test_sha256_accumulator_is_incremental_and_single_use() -> None:
    accumulator = Sha256Accumulator()
    accumulator.update(b"ab")
    accumulator.update(memoryview(b"c"))
    assert accumulator.byte_length == 3
    identity = accumulator.finish(expected_digest=_digest(b"abc"))
    assert identity.to_dict() == {"digest": _digest(b"abc"), "byteLength": 3}
    with pytest.raises(RuntimeError, match="finalized"):
        accumulator.update(b"again")
    with pytest.raises(RuntimeError, match="finalized"):
        accumulator.finish()

    mismatch = Sha256Accumulator()
    mismatch.update(b"abc")
    with pytest.raises(DigestMismatch):
        mismatch.finish(expected_digest="sha256:" + "0" * 64)
