# SPDX-License-Identifier: Apache-2.0
"""A provider-neutral in-memory execution target used only for conformance tests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from io import BytesIO
from typing import Any, cast

from meridian_storage.semantics import (
    CatalogName,
    JsonValue,
    ObjectMetadata,
    ObjectReference,
    ResourceReference,
)

from meridian_storage import Operation, ResourceRef
from meridian_storage.object_common import (
    ByteRange,
    ConditionalConflict,
    FactoryPayloadSource,
    ObjectNotFound,
    PayloadReference,
    PayloadRegistry,
    SignedObjectReference,
    parse_logical_reference,
    transfer_payload,
)


@dataclass(frozen=True, slots=True)
class _StoredObject:
    data: bytes
    metadata: ObjectMetadata


class MemoryObjectTarget:
    """Executes normalized Operations without modeling any physical provider."""

    target_id = "memory-object-target/1.0"

    def __init__(self) -> None:
        self._objects: dict[tuple[str, str, str], _StoredObject] = {}

    def reset(self) -> None:
        self._objects.clear()

    def execute(
        self,
        operation: Operation,
        payloads: PayloadRegistry,
    ) -> Mapping[str, object]:
        method = operation.operation_contract.removeprefix("meridian.object.")
        handlers = {
            "put": self._put,
            "get": self._get,
            "stat": self._stat,
            "read_range": self._read_range,
            "list": self._list,
            "delete": self._delete,
        }
        handler = handlers.get(method)
        if handler is None:
            raise AssertionError(f"test target cannot execute {method!r}")
        return handler(operation, payloads)

    def _put(self, operation: Operation, payloads: PayloadRegistry) -> Mapping[str, object]:
        value = operation.input
        resource = operation.resources[0]
        object_id = cast(str, value["objectId"])
        key = self._key(resource, object_id)
        if value["createOnly"] and key in self._objects:
            raise ConditionalConflict()
        raw_payload = value["payload"]
        assert isinstance(raw_payload, Mapping)
        sink = BytesIO()
        identity = transfer_payload(
            PayloadReference.from_mapping(cast(Mapping[str, object], raw_payload)),
            payloads,
            sink,
            chunk_size=7,
        )
        reference = ObjectReference(
            ResourceReference(CatalogName.OBJECT, resource.namespace, resource.name),
            object_id,
            identity.digest,
        )
        raw_immutability = value["immutability"]
        mutability = "mutable"
        if isinstance(raw_immutability, Mapping):
            mutability = cast(str, raw_immutability["mutability"])
        metadata = ObjectMetadata(
            object_ref=reference,
            digest=identity.digest,
            byte_length=identity.byte_length,
            media_type=cast(str, value["mediaType"]),
            created_at="2026-08-25T00:00:00.000000Z",
            creation_context=cast(Mapping[str, Any], value["creationContext"]),
            user_metadata=cast(Mapping[str, str], value["userMetadata"]),
            mutability=mutability,
            provenance=cast(Mapping[str, Any], value["provenance"]),
        )
        self._objects[key] = _StoredObject(sink.getvalue(), metadata)
        return {"metadata": metadata.to_dict()}

    def _get(self, operation: Operation, payloads: PayloadRegistry) -> Mapping[str, object]:
        stored = self._lookup(operation)
        reference = payloads.register(
            FactoryPayloadSource(lambda: BytesIO(stored.data)),
            expected_length=len(stored.data),
            expected_digest=stored.metadata.digest,
        )
        return {"metadata": stored.metadata.to_dict(), "payload": reference.to_dict()}

    def _stat(self, operation: Operation, payloads: PayloadRegistry) -> Mapping[str, object]:
        del payloads
        stored = self._lookup(operation)
        return {"metadata": stored.metadata.to_dict()}

    def _read_range(
        self,
        operation: Operation,
        payloads: PayloadRegistry,
    ) -> Mapping[str, object]:
        stored = self._lookup(operation)
        raw_range = operation.input["range"]
        assert isinstance(raw_range, Mapping)
        selected = ByteRange.from_mapping(cast(Mapping[str, object], raw_range))
        resolved = selected.resolve(len(stored.data))
        data = stored.data[resolved.start : resolved.end + 1]
        reference = payloads.register(
            FactoryPayloadSource(lambda: BytesIO(data)),
            expected_length=len(data),
        )
        return {
            "metadata": stored.metadata.to_dict(),
            "payload": reference.to_dict(),
            "range": resolved.to_dict(),
        }

    def _list(self, operation: Operation, payloads: PayloadRegistry) -> Mapping[str, object]:
        del payloads
        resource = operation.resources[0]
        prefix = cast(str, operation.input["prefix"])
        limit = cast(int, operation.input["limit"])
        matches = [
            stored.metadata.to_dict()
            for (namespace, name, object_id), stored in sorted(self._objects.items())
            if (namespace, name) == (resource.namespace, resource.name)
            and object_id.startswith(prefix)
        ]
        return {"items": matches[:limit], "cursor": None}

    def _delete(self, operation: Operation, payloads: PayloadRegistry) -> Mapping[str, object]:
        del payloads
        stored = self._lookup(operation)
        key = self._key(operation.resources[0], stored.metadata.object_ref.object_id)
        del self._objects[key]
        return {"deleted": True}

    def _lookup(self, operation: Operation) -> _StoredObject:
        raw = operation.input["reference"]
        assert isinstance(raw, Mapping)
        parsed = parse_logical_reference(cast(Mapping[str, object], raw))
        reference = parsed.object_ref if isinstance(parsed, SignedObjectReference) else parsed
        key = self._key(operation.resources[0], reference.object_id)
        stored = self._objects.get(key)
        if stored is None or (
            reference.digest is not None and reference.digest != stored.metadata.digest
        ):
            raise ObjectNotFound()
        return stored

    @staticmethod
    def _key(resource: ResourceRef, object_id: str) -> tuple[str, str, str]:
        return resource.namespace, resource.name, object_id


def json_mapping(value: Mapping[str, JsonValue]) -> Mapping[str, object]:
    """Retain a typed convenience boundary for test assertions."""

    return cast(Mapping[str, object], value)
