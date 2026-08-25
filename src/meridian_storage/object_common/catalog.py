# SPDX-License-Identifier: Apache-2.0
"""Mapping-first Object Catalog Expressions and deterministic normalization."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, cast

from meridian_storage.semantics import CatalogName, JsonValue, ObjectProfile, ResourceReference
from meridian_storage.spi import CapabilityRequirement

from meridian_storage import (
    CatalogManifest,
    Expression,
    Operation,
    OperationContract,
    ResourceRef,
    SchemaRef,
)

from ._validation import (
    bounded_string,
    digest,
    exact_fields,
    json_mapping,
    media_type,
    non_negative_int,
    positive_int,
    reject_private_configuration,
    string_mapping,
)
from ._version import __version__
from .capabilities import (
    GUARANTEE_BOUNDED_PREFIX_LIST,
    GUARANTEE_CONDITIONAL_CREATE,
    GUARANTEE_DIGEST_SHA256,
    GUARANTEE_DIGEST_VERIFICATION,
    GUARANTEE_EXACT_VERSION_DELETE,
    GUARANTEE_IMMUTABILITY_INTENT,
    GUARANTEE_METADATA_AFTER_COMMIT,
    GUARANTEE_RANGE_READ,
    GUARANTEE_RETENTION_ENFORCEMENT,
    GUARANTEE_RETENTION_INTENT,
    GUARANTEE_SIGNED_REFERENCE,
    GUARANTEE_STREAMING,
    LIMIT_MAX_LIST_PAGE_SIZE,
    LIMIT_MAX_OBJECT_BYTES,
    LIMIT_MAX_RANGE_BYTES,
    LIMIT_MAX_USER_METADATA_ENTRIES,
    OBJECT_OPERATION_VERSION,
    object_requirement,
)
from .codec import SignedObjectReference, parse_logical_reference
from .contracts import ByteRange, PayloadReference
from .errors import ObjectInvalidRequest
from .immutability import ImmutabilityRequest, RetentionRequest, parse_object_profile
from .metadata import ObjectReference

OBJECT_CATALOG_CONTRACT_VERSION = "1.0.0"
OBJECT_REGISTRY_REF = ResourceRef("object", "meridian", "registry")

_OBJECT_OPERATIONS: Mapping[str, tuple[bool, str, tuple[str, ...]]] = MappingProxyType(
    {
        "create_resource": (False, "always", ()),
        "delete": (False, "always", (GUARANTEE_EXACT_VERSION_DELETE,)),
        "get": (
            True,
            "always",
            (GUARANTEE_DIGEST_VERIFICATION, GUARANTEE_STREAMING),
        ),
        "list": (True, "always", (GUARANTEE_BOUNDED_PREFIX_LIST,)),
        "publish_schema": (False, "always", ()),
        "put": (
            False,
            "conditional",
            (
                GUARANTEE_DIGEST_SHA256,
                GUARANTEE_METADATA_AFTER_COMMIT,
                GUARANTEE_STREAMING,
            ),
        ),
        "read_range": (
            True,
            "always",
            (GUARANTEE_DIGEST_VERIFICATION, GUARANTEE_RANGE_READ),
        ),
        "stat": (True, "always", ()),
    }
)


def object_manifest() -> CatalogManifest:
    return CatalogManifest(
        catalog_name="object",
        package_name="meridian-storage-object-common",
        package_version=__version__,
        catalog_contract_version=OBJECT_CATALOG_CONTRACT_VERSION,
        operations=tuple(
            OperationContract(
                method=method,
                operation_contract=f"meridian.object.{method}",
                operation_version=OBJECT_OPERATION_VERSION,
                read_only=read_only,
                idempotency=idempotency,
                guarantees=guarantees,
            )
            for method, (read_only, idempotency, guarantees) in _OBJECT_OPERATIONS.items()
        ),
        extensions={
            "design.hldRevision": 56,
            "design.catalogRevision": 70,
            "design.objectLldRevision": 12,
            "objectMetadataFormat": "meridian.object.v1",
            "payloadReferenceFormat": "meridian.object.payload-reference.v1",
        },
    )


class ObjectCatalogSurface:
    """The exact eight-method V1 Object Catalog consumer surface."""

    catalog_name = "object"

    def publish_schema(
        self,
        *,
        namespace: str,
        name: str,
        version: str,
        definition: Mapping[str, object],
        expected_registry_revision: int | None = None,
        allow_breaking: bool = False,
    ) -> Expression:
        arguments: dict[str, Any] = {
            "namespace": namespace,
            "name": name,
            "version": version,
            "definition": dict(definition),
            "allowBreaking": allow_breaking,
            "expectedRegistryRevision": expected_registry_revision,
        }
        return self._expression("publish_schema", arguments)

    def create_resource(
        self,
        *,
        namespace: str,
        name: str,
        profile: ObjectProfile | Mapping[str, object] | None = None,
        options: Mapping[str, object] | None = None,
    ) -> Expression:
        selected_profile = ObjectProfile().to_dict() if profile is None else _wire(profile)
        return self._expression(
            "create_resource",
            {
                "namespace": namespace,
                "name": name,
                "profile": selected_profile,
                "options": dict(options or {}),
            },
        )

    def put(
        self,
        *,
        resource: ResourceRef | str | Mapping[str, object],
        object_id: str,
        payload: PayloadReference | Mapping[str, object],
        media_type: str,
        expected_digest: str | None = None,
        expected_length: int | None = None,
        user_metadata: Mapping[str, str] | None = None,
        creation_context: Mapping[str, object] | None = None,
        provenance: Mapping[str, object] | None = None,
        immutability: ImmutabilityRequest | Mapping[str, object] | None = None,
        retention: RetentionRequest | Mapping[str, object] | None = None,
        create_only: bool = False,
    ) -> Expression:
        payload_value = (
            payload
            if isinstance(payload, PayloadReference)
            else PayloadReference.from_mapping(payload)
        )
        selected_digest = (
            payload_value.expected_digest if expected_digest is None else expected_digest
        )
        selected_length = (
            payload_value.expected_length if expected_length is None else expected_length
        )
        return self._expression(
            "put",
            {
                "resource": _wire(resource),
                "objectId": object_id,
                "payload": payload_value.to_dict(),
                "mediaType": media_type,
                "expectedDigest": selected_digest,
                "expectedLength": selected_length,
                "userMetadata": dict(user_metadata or {}),
                "creationContext": dict(creation_context or {}),
                "provenance": dict(provenance or {}),
                "immutability": None if immutability is None else _wire(immutability),
                "retention": None if retention is None else _wire(retention),
                "createOnly": create_only,
            },
        )

    def get(
        self,
        *,
        resource: ResourceRef | str | Mapping[str, object],
        reference: ObjectReference | SignedObjectReference | Mapping[str, object],
    ) -> Expression:
        return self._reference_expression("get", resource, reference)

    def stat(
        self,
        *,
        resource: ResourceRef | str | Mapping[str, object],
        reference: ObjectReference | SignedObjectReference | Mapping[str, object],
    ) -> Expression:
        return self._reference_expression("stat", resource, reference)

    def read_range(
        self,
        *,
        resource: ResourceRef | str | Mapping[str, object],
        reference: ObjectReference | SignedObjectReference | Mapping[str, object],
        byte_range: ByteRange | Mapping[str, object],
    ) -> Expression:
        selected_range = (
            byte_range if isinstance(byte_range, ByteRange) else ByteRange.from_mapping(byte_range)
        )
        return self._expression(
            "read_range",
            {
                "resource": _wire(resource),
                "reference": _wire(reference),
                "range": selected_range.to_dict(),
            },
        )

    def list(
        self,
        *,
        resource: ResourceRef | str | Mapping[str, object],
        prefix: str = "",
        limit: int = 100,
        cursor: str | None = None,
        purpose: str = "maintenance",
    ) -> Expression:
        return self._expression(
            "list",
            {
                "resource": _wire(resource),
                "prefix": prefix,
                "limit": limit,
                "cursor": cursor,
                "purpose": purpose,
            },
        )

    def delete(
        self,
        *,
        resource: ResourceRef | str | Mapping[str, object],
        reference: ObjectReference | Mapping[str, object],
        reason: str | None = None,
    ) -> Expression:
        return self._expression(
            "delete",
            {"resource": _wire(resource), "reference": _wire(reference), "reason": reason},
        )

    def _reference_expression(
        self,
        method: str,
        resource: ResourceRef | str | Mapping[str, object],
        reference: ObjectReference | SignedObjectReference | Mapping[str, object],
    ) -> Expression:
        return self._expression(
            method,
            {"resource": _wire(resource), "reference": _wire(reference)},
        )

    def _expression(self, method: str, arguments: Mapping[str, Any]) -> Expression:
        return Expression(self.catalog_name, method, cast(Mapping[str, JsonValue], arguments))


class ObjectCatalogProvider:
    catalog_name = "object"

    def __init__(self) -> None:
        self._manifest = object_manifest()

    def manifest(self) -> CatalogManifest:
        return self._manifest

    def create_surface(self) -> ObjectCatalogSurface:
        return ObjectCatalogSurface()

    def normalize(self, expression: Expression) -> Operation:
        if expression.catalog != self.catalog_name:
            raise ObjectInvalidRequest("Expression Catalog does not match the Object provider")
        try:
            contract = self._manifest.operation_for(expression.method)
        except KeyError as exc:
            raise ObjectInvalidRequest(
                f"unsupported object Expression method {expression.method!r}"
            ) from exc
        input_value: dict[str, Any] = dict(expression.arguments)
        try:
            reject_private_configuration(input_value)
            if expression.method in {"publish_schema", "create_resource"}:
                _validate_registry_arguments(expression.method, input_value)
                resources = (OBJECT_REGISTRY_REF,)
                guarantees: set[str] = set()
                limits: dict[str, int] = {}
                idempotent = True
            else:
                resource = _parse_resource(input_value.get("resource"))
                resources = (resource,)
                guarantees, limits, idempotent = _validate_data_arguments(
                    expression.method, input_value, resource
                )
        except ObjectInvalidRequest:
            raise
        except (TypeError, ValueError) as exc:
            raise ObjectInvalidRequest(
                f"invalid object.{expression.method} arguments: {exc}",
                operation_contract=contract.operation_contract,
            ) from exc
        requirements: tuple[CapabilityRequirement, ...] = ()
        if guarantees or limits:
            requirements = (
                object_requirement(
                    expression.method,
                    guarantees=guarantees,
                    minimum_limits=limits,
                ),
            )
        return Operation(
            catalog=self.catalog_name,
            operation_contract=contract.operation_contract,
            operation_version=contract.operation_version,
            resources=resources,
            input=cast(Mapping[str, JsonValue], input_value),
            requirements=requirements,
            read_only=contract.read_only,
            idempotent=idempotent,
        )


def _validate_registry_arguments(method: str, value: dict[str, Any]) -> None:
    if method == "publish_schema":
        exact_fields(
            value,
            {
                "namespace",
                "name",
                "version",
                "definition",
                "allowBreaking",
                "expectedRegistryRevision",
            },
        )
        namespace = cast(str, value["namespace"])
        name = cast(str, value["name"])
        ResourceRef("object", namespace, name)
        SchemaRef("object", namespace, name, cast(str, value["version"]))
        json_mapping(value["definition"], "definition")
        if not isinstance(value["allowBreaking"], bool):
            raise TypeError("allowBreaking must be boolean")
        revision = value["expectedRegistryRevision"]
        if revision is not None:
            non_negative_int(revision, "expected registry revision")
        return
    exact_fields(value, {"namespace", "name", "profile", "options"})
    ResourceRef("object", cast(str, value["namespace"]), cast(str, value["name"]))
    profile_value = value["profile"]
    if not isinstance(profile_value, Mapping):
        raise TypeError("profile must be an object")
    value["profile"] = parse_object_profile(profile_value).to_dict()
    value["options"] = json_mapping(value["options"], "options")


def _validate_data_arguments(
    method: str,
    value: dict[str, Any],
    resource: ResourceRef,
) -> tuple[set[str], dict[str, int], bool]:
    if method == "put":
        return _validate_put(value, resource)
    if method in {"get", "stat"}:
        exact_fields(value, {"resource", "reference"})
        signed = _normalize_reference(value, resource, method=method)
        return ({GUARANTEE_SIGNED_REFERENCE} if signed else set(), {}, True)
    if method == "read_range":
        exact_fields(value, {"resource", "reference", "range"})
        signed = _normalize_reference(value, resource, method=method)
        raw_range = value["range"]
        if not isinstance(raw_range, Mapping):
            raise TypeError("range must be an object")
        selected_range = ByteRange.from_mapping(raw_range)
        value["range"] = selected_range.to_dict()
        limits = (
            {}
            if selected_range.requested_length is None
            else {LIMIT_MAX_RANGE_BYTES: selected_range.requested_length}
        )
        guarantees = {GUARANTEE_SIGNED_REFERENCE} if signed else set()
        return guarantees, limits, True
    if method == "list":
        exact_fields(value, {"resource", "prefix", "limit", "cursor", "purpose"})
        prefix = value["prefix"]
        if not isinstance(prefix, str) or len(prefix.encode("utf-8")) > 1024:
            raise ValueError("list prefix must be a UTF-8 string no larger than 1024 bytes")
        if any(ord(character) < 32 or ord(character) == 127 for character in prefix):
            raise ValueError("list prefix contains a control character")
        limit = positive_int(value["limit"], "list limit")
        if limit > 1000:
            raise ValueError("list limit must not exceed 1000")
        cursor = value["cursor"]
        if cursor is not None:
            bounded_string(cursor, "list cursor", 2048)
        if value["purpose"] != "maintenance":
            raise ValueError("bounded-prefix listing is restricted to maintenance use")
        return set(), {LIMIT_MAX_LIST_PAGE_SIZE: limit}, True
    if method == "delete":
        exact_fields(value, {"resource", "reference", "reason"})
        _normalize_reference(value, resource, method=method, require_digest=True)
        reason = value["reason"]
        if reason is not None:
            bounded_string(reason, "delete reason", 1024)
        return set(), {}, True
    raise ValueError(f"unsupported Object operation {method!r}")


def _validate_put(
    value: dict[str, Any],
    resource: ResourceRef,
) -> tuple[set[str], dict[str, int], bool]:
    exact_fields(
        value,
        {
            "resource",
            "objectId",
            "payload",
            "mediaType",
            "expectedDigest",
            "expectedLength",
            "userMetadata",
            "creationContext",
            "provenance",
            "immutability",
            "retention",
            "createOnly",
        },
    )
    raw_payload = value["payload"]
    if not isinstance(raw_payload, Mapping):
        raise TypeError("payload must be a serialized PayloadReference")
    payload = PayloadReference.from_mapping(raw_payload)
    expected_digest = value["expectedDigest"]
    if expected_digest is not None:
        expected_digest = digest(expected_digest, "expected digest")
    expected_length = value["expectedLength"]
    if expected_length is not None:
        expected_length = non_negative_int(expected_length, "expected length")
    if payload.expected_digest is not None and payload.expected_digest != expected_digest:
        raise ValueError("payload and put expected digests do not match")
    if payload.expected_length is not None and payload.expected_length != expected_length:
        raise ValueError("payload and put expected lengths do not match")
    payload = PayloadReference(
        payload.token,
        expected_length=expected_length,
        expected_digest=expected_digest,
        replayable=payload.replayable,
    )
    value["payload"] = payload.to_dict()
    value["expectedDigest"] = expected_digest
    value["expectedLength"] = expected_length
    media_type(value["mediaType"])
    object_id = bounded_string(value["objectId"], "Object id", 1024)
    semantic_resource = ResourceReference(
        CatalogName.OBJECT,
        resource.namespace,
        resource.name,
    )
    ObjectReference(semantic_resource, object_id, expected_digest)
    value["userMetadata"] = string_mapping(
        value["userMetadata"],
        "user metadata",
        maximum_entries=128,
        maximum_key_bytes=128,
        maximum_value_bytes=2048,
    )
    value["creationContext"] = json_mapping(value["creationContext"], "creationContext")
    value["provenance"] = json_mapping(value["provenance"], "provenance")
    guarantees: set[str] = set()
    raw_immutability = value["immutability"]
    if raw_immutability is not None:
        if not isinstance(raw_immutability, Mapping):
            raise TypeError("immutability must be an object or null")
        selected_immutability = ImmutabilityRequest.from_mapping(raw_immutability)
        value["immutability"] = selected_immutability.to_dict()
        if selected_immutability.mutability == "immutable":
            guarantees.add(GUARANTEE_IMMUTABILITY_INTENT)
    raw_retention = value["retention"]
    if raw_retention is not None:
        if not isinstance(raw_retention, Mapping):
            raise TypeError("retention must be an object or null")
        selected_retention = RetentionRequest.from_mapping(raw_retention)
        value["retention"] = selected_retention.to_dict()
        guarantees.add(GUARANTEE_RETENTION_INTENT)
        if selected_retention.require_enforcement:
            guarantees.add(GUARANTEE_RETENTION_ENFORCEMENT)
    if not isinstance(value["createOnly"], bool):
        raise TypeError("createOnly must be boolean")
    if value["createOnly"]:
        guarantees.add(GUARANTEE_CONDITIONAL_CREATE)
    limits = {LIMIT_MAX_USER_METADATA_ENTRIES: len(value["userMetadata"])}
    if expected_length is not None:
        limits[LIMIT_MAX_OBJECT_BYTES] = expected_length
    return guarantees, limits, bool(value["createOnly"] or expected_digest is not None)


def _normalize_reference(
    value: dict[str, Any],
    resource: ResourceRef,
    *,
    method: str,
    require_digest: bool = False,
) -> bool:
    raw = value["reference"]
    if not isinstance(raw, Mapping):
        raise TypeError("reference must be an object")
    parsed = parse_logical_reference(raw)
    signed = isinstance(parsed, SignedObjectReference)
    if signed:
        signed_reference = cast(SignedObjectReference, parsed)
        if method not in signed_reference.allowed_operations:
            raise ValueError("signed Object reference does not permit this method")
        reference = signed_reference.object_ref
        value["reference"] = signed_reference.to_dict()
    else:
        reference = cast(ObjectReference, parsed)
        if require_digest and reference.digest is None:
            raise ValueError("delete requires an exact Object reference with digest")
        value["reference"] = reference.to_dict()
    _require_same_resource(reference, resource)
    return signed


def _require_same_resource(reference: ObjectReference, resource: ResourceRef) -> None:
    selected = reference.resource_ref
    if (
        selected.catalog.value,
        selected.namespace,
        selected.name,
    ) != (resource.catalog, resource.namespace, resource.name):
        raise ValueError("Object reference does not belong to the target Resource")


def _parse_resource(value: object) -> ResourceRef:
    try:
        return ResourceRef.parse(cast(Any, value), catalog="object")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid logical Object Resource reference: {exc}") from exc


def _wire(value: object) -> object:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    return value


__all__ = [
    "OBJECT_CATALOG_CONTRACT_VERSION",
    "OBJECT_REGISTRY_REF",
    "ObjectCatalogProvider",
    "ObjectCatalogSurface",
    "object_manifest",
]
