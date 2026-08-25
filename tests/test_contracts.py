# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from meridian_storage.semantics import (
    CatalogName,
    ObjectMetadata,
    ObjectProfile,
    ObjectReference,
    RelationalProfile,
    ResourceReference,
)

from meridian_storage.object_common import (
    ByteRange,
    ContentIdentity,
    ImmutabilityRequest,
    ImmutableObjectConflict,
    MultipartCompletion,
    MultipartInvalid,
    MultipartLimits,
    MultipartPart,
    MultipartSession,
    ObjectInvalidRequest,
    PutState,
    PutStateMachine,
    RangeNotSatisfiable,
    RetentionDenied,
    RetentionRequest,
    effective_immutability,
    parse_object_metadata,
    parse_object_profile,
    parse_object_reference,
)

DIGEST = "sha256:" + "a" * 64
RESOURCE = ResourceReference(CatalogName.OBJECT, "fixtures", "objects")
REFERENCE = ObjectReference(RESOURCE, "item.bin", DIGEST)


def test_byte_ranges_are_inclusive_and_deterministic() -> None:
    bounded = ByteRange(start=2, end=4)
    assert bounded.requested_length == 3
    assert bounded.to_dict() == {"start": 2, "end": 4}
    assert ByteRange.from_mapping(bounded.to_dict()) == bounded
    assert bounded.resolve(10).to_dict() == {
        "start": 2,
        "end": 4,
        "length": 3,
        "totalLength": 10,
    }

    open_ended = ByteRange(start=8)
    assert open_ended.requested_length is None
    assert open_ended.resolve(10).to_dict()["end"] == 9

    suffix = ByteRange(suffix_length=20)
    assert suffix.requested_length == 20
    assert suffix.to_dict() == {"suffixLength": 20}
    assert ByteRange.from_mapping(suffix.to_dict()).resolve(5).length == 5


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ByteRange(),
        lambda: ByteRange(start=1, end=0),
        lambda: ByteRange(start=1, suffix_length=1),
        lambda: ByteRange(suffix_length=0),
        lambda: ByteRange(start=-1),
    ],
)
def test_invalid_range_shapes_are_rejected(factory: object) -> None:
    with pytest.raises((ValueError, RangeNotSatisfiable)):
        factory()  # type: ignore[operator]


def test_unsatisfiable_ranges_are_stable_public_failures() -> None:
    with pytest.raises(RangeNotSatisfiable):
        ByteRange(start=0).resolve(0)
    with pytest.raises(RangeNotSatisfiable):
        ByteRange(start=5).resolve(5)
    with pytest.raises(ValueError, match="unknown fields"):
        ByteRange.from_mapping({"start": 0, "extra": 1})


def test_put_state_machine_models_commit_and_orphan_paths() -> None:
    committed = PutStateMachine()
    assert committed.state is PutState.NEW
    assert committed.transition("UPLOADING") is PutState.UPLOADING
    assert committed.transition(PutState.VERIFYING) is PutState.VERIFYING
    assert committed.transition(PutState.COMMITTED) is PutState.COMMITTED
    assert committed.history == (
        PutState.NEW,
        PutState.UPLOADING,
        PutState.VERIFYING,
        PutState.COMMITTED,
    )
    with pytest.raises(ObjectInvalidRequest, match="COMMITTED->ABORTED"):
        committed.fail(physical_commit_possible=False)

    aborted = PutStateMachine()
    assert aborted.fail(physical_commit_possible=False) is PutState.ABORTED
    orphan = PutStateMachine()
    orphan.transition(PutState.UPLOADING)
    assert orphan.fail(physical_commit_possible=True) is PutState.ORPHAN_CANDIDATE


def test_content_identity_and_object_metadata_round_trip() -> None:
    identity = ContentIdentity(DIGEST, 4)
    assert ContentIdentity.from_mapping(identity.to_dict()) == identity
    with pytest.raises(ValueError, match="sha256"):
        ContentIdentity("bad", 0)
    with pytest.raises(ValueError, match="non-negative"):
        ContentIdentity(DIGEST, -1)

    metadata = ObjectMetadata(
        object_ref=REFERENCE,
        digest=DIGEST,
        byte_length=4,
        media_type="application/octet-stream",
        created_at="2026-08-25T00:00:00.000000Z",
        creation_context={"request": "r-1"},
        user_metadata={"name": "fixture"},
        mutability="immutable",
        provenance={"producer": "test"},
    )
    assert parse_object_metadata(metadata.to_dict()).to_dict() == metadata.to_dict()
    assert parse_object_metadata(metadata).to_dict() == metadata.to_dict()
    assert parse_object_reference(REFERENCE.to_dict(), require_digest=True) == REFERENCE
    with pytest.raises(ValueError, match="requires a digest"):
        parse_object_reference(ObjectReference(RESOURCE, "unversioned"), require_digest=True)
    with pytest.raises(TypeError, match="resourceRef"):
        parse_object_reference({"resourceRef": "not-an-object", "objectId": "x"})


def test_multipart_limits_session_parts_and_completion() -> None:
    limits = MultipartLimits(min_part_bytes=2, max_part_bytes=8, max_parts=3)
    assert limits.to_dict() == {"minPartBytes": 2, "maxPartBytes": 8, "maxParts": 3}
    assert limits.validate(part_size=4, total_length=9) == 3
    assert limits.validate(part_size=4) is None
    with pytest.raises(MultipartInvalid, match="part size"):
        limits.validate(part_size=1)
    with pytest.raises(MultipartInvalid, match="part-count"):
        limits.validate(part_size=2, total_length=7)
    with pytest.raises(MultipartInvalid, match="non-negative"):
        limits.validate(part_size=2, total_length=-1)
    with pytest.raises(MultipartInvalid, match="minimum"):
        MultipartLimits(9, 8, 1)

    session = MultipartSession(
        "session-1",
        REFERENCE,
        4,
        expires_at="2099-01-01T00:00:00.000000Z",
    )
    assert MultipartSession.from_mapping(session.to_dict()) == session

    part_one = MultipartPart(1, ContentIdentity("sha256:" + "1" * 64, 2), "part-1")
    part_two = MultipartPart(2, ContentIdentity("sha256:" + "2" * 64, 2), "part-2")
    completion = MultipartCompletion((part_two, part_one), ContentIdentity(DIGEST, 4))
    assert [item["number"] for item in completion.to_dict()["parts"]] == [1, 2]

    with pytest.raises(MultipartInvalid, match="at least one"):
        MultipartCompletion((), ContentIdentity(DIGEST, 0))
    with pytest.raises(MultipartInvalid, match="contiguous"):
        MultipartCompletion((part_two,), ContentIdentity(DIGEST, 2))
    with pytest.raises(MultipartInvalid, match="lengths"):
        MultipartCompletion((part_one,), ContentIdentity(DIGEST, 3))
    with pytest.raises(ValueError, match="positive"):
        MultipartPart(0, ContentIdentity(DIGEST, 1), "part")


def test_immutability_respects_resource_and_profile_intent() -> None:
    mutable = ObjectProfile(mutability="mutable")
    assert effective_immutability(mutable) == ImmutabilityRequest("mutable")
    explicit = ImmutabilityRequest.from_mapping({"mutability": "immutable", "publishOnce": True})
    assert effective_immutability(mutable, explicit) is explicit

    artifact = ObjectProfile(profile="artifact")
    assert effective_immutability(artifact) == ImmutabilityRequest("immutable", True)
    with pytest.raises(ImmutableObjectConflict, match="artifact"):
        effective_immutability(artifact, {"mutability": "immutable", "publishOnce": False})
    with pytest.raises(ImmutableObjectConflict, match="cannot weaken"):
        effective_immutability(ObjectProfile(), {"mutability": "mutable", "publishOnce": False})
    with pytest.raises(ValueError, match="publish-once"):
        ImmutabilityRequest("mutable", True)
    with pytest.raises(ValueError, match="object, artifact, or media"):
        parse_object_profile(RelationalProfile().to_dict())


def test_retention_intent_handles_deadline_and_external_policy() -> None:
    future = RetentionRequest(
        retain_until="2099-01-01T00:00:00.000000Z",
        policy="legal-hold",
        require_enforcement=True,
    )
    assert RetentionRequest.from_mapping(future.to_dict()) == future
    assert not future.permits_delete(now=datetime(2026, 1, 1, tzinfo=UTC))
    with pytest.raises(RetentionDenied):
        future.require_delete_allowed(now=datetime(2026, 1, 1, tzinfo=UTC))
    assert future.permits_delete(now=datetime(2100, 1, 1, tzinfo=UTC))
    future.require_delete_allowed(now=datetime(2100, 1, 1, tzinfo=UTC))

    policy_only = RetentionRequest(policy="external-policy")
    assert not policy_only.permits_delete()
    with pytest.raises(ValueError, match="requires"):
        RetentionRequest()
    with pytest.raises(ValueError, match="timezone-aware"):
        future.permits_delete(now=datetime(2026, 1, 1))
