# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping

import pytest
from meridian_storage.semantics import (
    CatalogName,
    ObjectProfile,
    ObjectReference,
    ResourceReference,
)

from meridian_storage import Expression, Operation, ResourceRef
from meridian_storage.object_common import (
    GUARANTEE_CONDITIONAL_CREATE,
    GUARANTEE_IMMUTABILITY_INTENT,
    GUARANTEE_RETENTION_ENFORCEMENT,
    GUARANTEE_RETENTION_INTENT,
    GUARANTEE_SIGNED_REFERENCE,
    LIMIT_MAX_LIST_PAGE_SIZE,
    LIMIT_MAX_OBJECT_BYTES,
    LIMIT_MAX_RANGE_BYTES,
    LIMIT_MAX_USER_METADATA_ENTRIES,
    OBJECT_CATALOG_CONTRACT_VERSION,
    ByteRange,
    HmacSha256Key,
    ObjectCatalogProvider,
    ObjectInvalidRequest,
    PayloadReference,
    sign_object_reference,
)

DIGEST = "sha256:" + "a" * 64
RESOURCE = ResourceReference(CatalogName.OBJECT, "fixtures", "objects")
REFERENCE = ObjectReference(RESOURCE, "folder/item.bin", DIGEST)
PAYLOAD = PayloadReference(
    "p_fixture",
    expected_length=4,
    expected_digest=DIGEST,
    replayable=True,
)


def _provider() -> tuple[ObjectCatalogProvider, object]:
    provider = ObjectCatalogProvider()
    return provider, provider.create_surface()


@pytest.mark.integration
def test_manifest_is_exact_and_deterministic() -> None:
    provider = ObjectCatalogProvider()
    manifest = provider.manifest()
    expected = {
        "create_resource",
        "delete",
        "get",
        "list",
        "publish_schema",
        "put",
        "read_range",
        "stat",
    }
    assert manifest.catalog_name == "object"
    assert manifest.package_name == "meridian-storage-object-common"
    assert manifest.catalog_contract_version == OBJECT_CATALOG_CONTRACT_VERSION == "1.0.0"
    assert {item.method for item in manifest.operations} == expected
    assert len(manifest.operations) == 8
    assert provider.manifest() is manifest
    assert manifest.fingerprint == (
        "sha256:e6696e6944768e9a42acffa331d91c75fe7222ae331bfbda3640a4a4fe024b1b"
    )


@pytest.mark.integration
def test_registry_operations_normalize_to_registry_resource() -> None:
    provider = ObjectCatalogProvider()
    surface = provider.create_surface()
    publish = provider.normalize(
        surface.publish_schema(
            namespace="fixtures",
            name="metadata",
            version="1.0.0",
            definition={"type": "object"},
            expected_registry_revision=0,
        )
    )
    create = provider.normalize(
        surface.create_resource(
            namespace="fixtures",
            name="objects",
            profile=ObjectProfile(profile="artifact"),
            options={"logicalLabel": "release objects"},
        )
    )
    for operation, contract in (
        (publish, "meridian.object.publish_schema"),
        (create, "meridian.object.create_resource"),
    ):
        assert operation.operation_contract == contract
        assert operation.resources == (ResourceRef("object", "meridian", "registry"),)
        assert operation.idempotent
        assert not operation.read_only
    profile = create.input["profile"]
    assert isinstance(profile, Mapping)
    assert profile["profile"] == "artifact"
    assert profile["mutability"] == "immutable"


@pytest.mark.integration
def test_put_normalization_carries_request_specific_requirements() -> None:
    provider = ObjectCatalogProvider()
    surface = provider.create_surface()
    expression = surface.put(
        resource="fixtures.objects",
        object_id="folder/item.bin",
        payload=PAYLOAD,
        media_type="application/octet-stream",
        user_metadata={"purpose": "fixture"},
        creation_context={"requestId": "r-1"},
        provenance={"producer": "tests"},
        immutability={"mutability": "immutable", "publishOnce": True},
        retention={
            "retainUntil": "2099-01-01T00:00:00.000000Z",
            "policy": None,
            "requireEnforcement": True,
        },
        create_only=True,
    )

    operation = provider.normalize(expression)

    assert isinstance(operation, Operation)
    assert operation.resources == (ResourceRef("object", "fixtures", "objects"),)
    assert operation.operation_contract == "meridian.object.put"
    assert operation.idempotent
    assert not operation.read_only
    assert len(operation.requirements) == 1
    requirement = operation.requirements[0]
    assert set(requirement.guarantees) == {
        GUARANTEE_CONDITIONAL_CREATE,
        GUARANTEE_IMMUTABILITY_INTENT,
        GUARANTEE_RETENTION_ENFORCEMENT,
        GUARANTEE_RETENTION_INTENT,
    }
    assert requirement.minimum_limits == {
        LIMIT_MAX_OBJECT_BYTES: 4,
        LIMIT_MAX_USER_METADATA_ENTRIES: 1,
    }
    assert operation.input["expectedDigest"] == DIGEST
    assert operation.input["expectedLength"] == 4


@pytest.mark.integration
def test_read_list_and_delete_normalize_exactly() -> None:
    provider = ObjectCatalogProvider()
    surface = provider.create_surface()
    get = provider.normalize(surface.get(resource="fixtures.objects", reference=REFERENCE))
    stat = provider.normalize(surface.stat(resource="fixtures.objects", reference=REFERENCE))
    selected_range = provider.normalize(
        surface.read_range(
            resource="fixtures.objects",
            reference=REFERENCE,
            byte_range=ByteRange(start=1, end=3),
        )
    )
    listed = provider.normalize(
        surface.list(resource="fixtures.objects", prefix="folder/", limit=25)
    )
    deleted = provider.normalize(
        surface.delete(resource="fixtures.objects", reference=REFERENCE, reason="cleanup")
    )

    assert get.read_only and stat.read_only and selected_range.read_only and listed.read_only
    assert not deleted.read_only
    assert selected_range.requirements[0].minimum_limits == {LIMIT_MAX_RANGE_BYTES: 3}
    assert listed.requirements[0].minimum_limits == {LIMIT_MAX_LIST_PAGE_SIZE: 25}
    assert deleted.input["reference"] == REFERENCE.to_dict()


@pytest.mark.integration
def test_signed_reference_adds_capability_requirement_and_permission_check() -> None:
    provider = ObjectCatalogProvider()
    surface = provider.create_surface()
    signed = sign_object_reference(
        REFERENCE,
        allowed_operations=("get",),
        expires_at="2099-01-01T00:00:00.000000Z",
        audience="reader",
        signer=HmacSha256Key("key-1", b"x" * 32),
        nonce="nonce-1",
    )
    operation = provider.normalize(surface.get(resource="fixtures.objects", reference=signed))
    assert operation.requirements[0].guarantees == (GUARANTEE_SIGNED_REFERENCE,)

    with pytest.raises(ObjectInvalidRequest, match="does not permit"):
        provider.normalize(surface.stat(resource="fixtures.objects", reference=signed))


@pytest.mark.integration
@pytest.mark.parametrize(
    ("expression", "match"),
    [
        (
            Expression(
                "object",
                "list",
                {
                    "resource": "fixtures.objects",
                    "prefix": "",
                    "limit": 1,
                    "cursor": None,
                    "purpose": "consumer-query",
                },
            ),
            "maintenance",
        ),
        (
            Expression(
                "object",
                "create_resource",
                {
                    "namespace": "fixtures",
                    "name": "objects",
                    "profile": ObjectProfile().to_dict(),
                    "options": {"bucket": "private-provider-value"},
                },
            ),
            "private Adapter or IaC",
        ),
        (
            Expression(
                "object",
                "delete",
                {
                    "resource": "fixtures.objects",
                    "reference": ObjectReference(RESOURCE, "folder/item.bin").to_dict(),
                    "reason": None,
                },
            ),
            "requires an exact",
        ),
        (
            Expression(
                "object",
                "put",
                {
                    "resource": "fixtures.objects",
                    "objectId": "folder/item.bin",
                    "payload": PAYLOAD.to_dict(),
                    "mediaType": "application/octet-stream",
                    "expectedDigest": "sha256:" + "b" * 64,
                    "expectedLength": 4,
                    "userMetadata": {},
                    "creationContext": {},
                    "provenance": {},
                    "immutability": None,
                    "retention": None,
                    "createOnly": False,
                },
            ),
            "digests do not match",
        ),
    ],
)
def test_normalization_rejects_boundary_violations(
    expression: Expression,
    match: str,
) -> None:
    with pytest.raises(ObjectInvalidRequest, match=match):
        ObjectCatalogProvider().normalize(expression)


@pytest.mark.integration
def test_provider_rejects_wrong_catalog_and_unknown_method() -> None:
    provider = ObjectCatalogProvider()
    with pytest.raises(ObjectInvalidRequest, match="does not match"):
        provider.normalize(Expression("cache", "get", {}))
    with pytest.raises(ObjectInvalidRequest, match="unsupported"):
        provider.normalize(Expression("object", "unknown", {}))
