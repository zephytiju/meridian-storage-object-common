# SPDX-License-Identifier: Apache-2.0
"""Reusable Object Adapter conformance runner and result contract."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from io import BytesIO
from typing import Protocol, cast, runtime_checkable

from meridian_storage.semantics import JsonValue, sha256_fingerprint

from meridian_storage import Expression, Operation

from ..catalog import ObjectCatalogProvider
from ..contracts import (
    ByteRange,
    FactoryPayloadSource,
    PayloadReference,
    PayloadRegistry,
    transfer_payload,
)
from ..errors import ConditionalConflict, DigestMismatch, ObjectNotFound
from ..metadata import ObjectMetadata, parse_object_metadata


@runtime_checkable
class ObjectConformanceTarget(Protocol):
    """Minimal provider-neutral execution hook implemented by downstream Adapter tests."""

    @property
    def target_id(self) -> str: ...

    def reset(self) -> None: ...

    def execute(
        self,
        operation: Operation,
        payloads: PayloadRegistry,
    ) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class ObjectConformanceCheck:
    name: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, JsonValue]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class ObjectConformanceReport:
    target_id: str
    checks: tuple[ObjectConformanceCheck, ...]

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(check.passed for check in self.checks)

    @property
    def fingerprint(self) -> str:
        return sha256_fingerprint(cast(JsonValue, self.to_dict(include_fingerprint=False)))

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, JsonValue]:
        result: dict[str, JsonValue] = {
            "formatVersion": "meridian.object-conformance-report.v1",
            "targetId": self.target_id,
            "passed": self.passed,
            "checks": [check.to_dict() for check in self.checks],
        }
        if include_fingerprint:
            result["fingerprint"] = self.fingerprint
        return result

    def require_success(self) -> None:
        failures = [check.name for check in self.checks if not check.passed]
        if failures:
            raise AssertionError(f"Object conformance failed: {failures!r}")


class _Runner:
    def __init__(self, target: ObjectConformanceTarget) -> None:
        self.target = target
        self.payloads = PayloadRegistry()
        self.provider = ObjectCatalogProvider()
        self.surface = self.provider.create_surface()
        self.checks: list[ObjectConformanceCheck] = []
        self.resource = "object:conformance.objects"
        self.payload = b"Meridian object conformance payload\x00\xff\n"
        self.digest = f"sha256:{hashlib.sha256(self.payload).hexdigest()}"
        self.object_id = "fixture/object-001"
        self.metadata: ObjectMetadata | None = None

    def run(self) -> ObjectConformanceReport:
        self.target.reset()
        self._check("unknown-length-streaming-put", self._put)
        self._check("stat-content-identity", self._stat)
        self._check("streaming-get", self._get)
        self._check("inclusive-range-read", self._range)
        self._check("bounded-prefix-list", self._list)
        self._expected("conditional-create-conflict", ConditionalConflict, self._duplicate)
        self._expected("digest-mismatch", DigestMismatch, self._digest_mismatch)
        self._check("exact-version-delete", self._delete)
        self._expected("missing-object", ObjectNotFound, self._stat)
        return ObjectConformanceReport(self.target.target_id, tuple(self.checks))

    def _check(self, name: str, action: Callable[[], None]) -> None:
        try:
            action()
        except Exception as exc:
            self.checks.append(ObjectConformanceCheck(name, False, type(exc).__name__))
        else:
            self.checks.append(ObjectConformanceCheck(name, True, "ok"))

    def _expected(
        self,
        name: str,
        expected: type[Exception],
        action: Callable[[], None],
    ) -> None:
        try:
            action()
        except expected:
            self.checks.append(ObjectConformanceCheck(name, True, expected.__name__))
        except Exception as exc:
            self.checks.append(ObjectConformanceCheck(name, False, type(exc).__name__))
        else:
            self.checks.append(ObjectConformanceCheck(name, False, "no-error"))

    def _execute(self, expression: Expression) -> Mapping[str, object]:
        operation = self.provider.normalize(expression)
        return self.target.execute(operation, self.payloads)

    def _payload_reference(self, *, digest_value: str | None = None) -> PayloadReference:
        return self.payloads.register(
            FactoryPayloadSource(lambda: BytesIO(self.payload), replayable=True),
            expected_digest=self.digest if digest_value is None else digest_value,
        )

    def _put(self) -> None:
        result = self._execute(
            self.surface.put(
                resource=self.resource,
                object_id=self.object_id,
                payload=self._payload_reference(),
                media_type="application/octet-stream",
                expected_digest=self.digest,
                create_only=True,
                user_metadata={"fixture": "v1"},
                immutability={"mutability": "immutable", "publishOnce": True},
            )
        )
        metadata = _metadata_result(result)
        assert metadata.digest == self.digest
        assert metadata.byte_length == len(self.payload)
        assert metadata.object_ref.digest == self.digest
        self.metadata = metadata

    def _stat(self) -> None:
        reference = self._reference()
        result = self._execute(self.surface.stat(resource=self.resource, reference=reference))
        metadata = _metadata_result(result)
        assert metadata.to_dict() == self._required_metadata().to_dict()

    def _get(self) -> None:
        result = self._execute(
            self.surface.get(resource=self.resource, reference=self._reference())
        )
        metadata = _metadata_result(result)
        assert metadata.digest == self.digest
        raw_payload = result.get("payload")
        if not isinstance(raw_payload, Mapping):
            raise AssertionError("get result requires payload")
        sink = BytesIO()
        identity = transfer_payload(PayloadReference.from_mapping(raw_payload), self.payloads, sink)
        assert identity.digest == self.digest
        assert sink.getvalue() == self.payload

    def _range(self) -> None:
        selected = ByteRange(start=2, end=9)
        result = self._execute(
            self.surface.read_range(
                resource=self.resource,
                reference=self._reference(),
                byte_range=selected,
            )
        )
        raw_payload = result.get("payload")
        if not isinstance(raw_payload, Mapping):
            raise AssertionError("range result requires payload")
        sink = BytesIO()
        transfer_payload(PayloadReference.from_mapping(raw_payload), self.payloads, sink)
        assert sink.getvalue() == self.payload[2:10]
        assert result.get("range") == selected.resolve(len(self.payload)).to_dict()

    def _list(self) -> None:
        result = self._execute(
            self.surface.list(resource=self.resource, prefix="fixture/", limit=1)
        )
        items = result.get("items")
        if not isinstance(items, list) or len(items) != 1:
            raise AssertionError("bounded list must return one fixture")
        assert parse_object_metadata(cast(Mapping[str, object], items[0])).digest == self.digest
        cursor = result.get("cursor")
        assert cursor is None or isinstance(cursor, str)

    def _duplicate(self) -> None:
        self._execute(
            self.surface.put(
                resource=self.resource,
                object_id=self.object_id,
                payload=self._payload_reference(),
                media_type="application/octet-stream",
                expected_digest=self.digest,
                create_only=True,
            )
        )

    def _digest_mismatch(self) -> None:
        self._execute(
            self.surface.put(
                resource=self.resource,
                object_id="fixture/digest-mismatch",
                payload=self._payload_reference(digest_value="sha256:" + "0" * 64),
                media_type="application/octet-stream",
                expected_digest="sha256:" + "0" * 64,
                create_only=True,
            )
        )

    def _delete(self) -> None:
        result = self._execute(
            self.surface.delete(
                resource=self.resource,
                reference=self._reference(),
                reason="conformance-cleanup",
            )
        )
        assert result == {"deleted": True}

    def _required_metadata(self) -> ObjectMetadata:
        if self.metadata is None:
            raise AssertionError("put did not produce metadata")
        return self.metadata

    def _reference(self) -> Mapping[str, JsonValue]:
        return self._required_metadata().object_ref.to_dict()


def _metadata_result(result: Mapping[str, object]) -> ObjectMetadata:
    value = result.get("metadata")
    if not isinstance(value, Mapping):
        raise AssertionError("Object result requires metadata")
    return parse_object_metadata(value)


def run_object_conformance(target: ObjectConformanceTarget) -> ObjectConformanceReport:
    if not isinstance(target, ObjectConformanceTarget):
        raise TypeError("target does not implement ObjectConformanceTarget")
    return _Runner(target).run()


__all__ = [
    "ObjectConformanceCheck",
    "ObjectConformanceReport",
    "ObjectConformanceTarget",
    "run_object_conformance",
]
