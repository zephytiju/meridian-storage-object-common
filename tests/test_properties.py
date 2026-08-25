# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
from io import BytesIO

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from meridian_storage.semantics import canonical_json_bytes

from meridian_storage.object_common import (
    ByteRange,
    FactoryPayloadSource,
    ObjectCatalogProvider,
    PayloadReference,
    PayloadRegistry,
    transfer_payload,
)


@pytest.mark.property
@settings(max_examples=100, deadline=None)
@given(
    total=st.integers(min_value=1, max_value=10_000),
    start_fraction=st.floats(min_value=0, max_value=1, allow_nan=False),
    end_fraction=st.floats(min_value=0, max_value=1, allow_nan=False),
)
def test_resolved_ranges_always_cover_exact_inclusive_length(
    total: int,
    start_fraction: float,
    end_fraction: float,
) -> None:
    start = min(total - 1, int(start_fraction * total))
    end = start + int(end_fraction * (total - start - 1))
    resolved = ByteRange(start=start, end=end).resolve(total)
    assert 0 <= resolved.start <= resolved.end < resolved.total_length == total
    assert resolved.length == resolved.end - resolved.start + 1


@pytest.mark.property
@settings(max_examples=100, deadline=None)
@given(
    total=st.integers(min_value=1, max_value=10_000),
    suffix=st.integers(min_value=1, max_value=20_000),
)
def test_suffix_ranges_are_clamped_to_object_length(total: int, suffix: int) -> None:
    resolved = ByteRange(suffix_length=suffix).resolve(total)
    assert resolved.end == total - 1
    assert resolved.length == min(total, suffix)


@pytest.mark.property
@settings(max_examples=75, deadline=None)
@given(
    payload=st.binary(max_size=16_384),
    chunk_size=st.integers(min_value=1, max_value=1024),
)
def test_streaming_identity_is_independent_of_chunk_boundaries(
    payload: bytes,
    chunk_size: int,
) -> None:
    digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    registry = PayloadRegistry()
    reference = registry.register(
        FactoryPayloadSource(lambda: BytesIO(payload)),
        expected_length=len(payload),
        expected_digest=digest,
    )
    sink = BytesIO()
    identity = transfer_payload(reference, registry, sink, chunk_size=chunk_size)
    assert sink.getvalue() == payload
    assert identity.digest == digest
    assert identity.byte_length == len(payload)


@pytest.mark.property
@settings(max_examples=75, deadline=None)
@given(
    entries=st.dictionaries(
        keys=st.from_regex(r"[A-Za-z][A-Za-z0-9_-]{0,8}", fullmatch=True),
        values=st.from_regex(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,12}", fullmatch=True),
        max_size=12,
    )
)
def test_operation_normalization_is_independent_of_mapping_insertion_order(
    entries: dict[str, str],
) -> None:
    digest = "sha256:" + "a" * 64
    payload = PayloadReference("p_property", expected_length=1, expected_digest=digest)
    surface = ObjectCatalogProvider().create_surface()
    forward = surface.put(
        resource="fixtures.objects",
        object_id="item.bin",
        payload=payload,
        media_type="application/octet-stream",
        user_metadata=entries,
    )
    reverse = surface.put(
        resource="fixtures.objects",
        object_id="item.bin",
        payload=payload,
        media_type="application/octet-stream",
        user_metadata=dict(reversed(tuple(entries.items()))),
    )
    provider = ObjectCatalogProvider()
    first = provider.normalize(forward)
    second = provider.normalize(reverse)
    assert canonical_json_bytes(first.to_dict()) == canonical_json_bytes(second.to_dict())
