# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator
from meridian_storage.semantics import ObjectMetadata
from referencing import Registry, Resource

import meridian_storage.object_common as public_api
from meridian_storage import Expression
from meridian_storage.object_common import (
    HmacSha256Key,
    ObjectCatalogProvider,
    ObjectErrorCode,
    PayloadReference,
    SignedObjectReference,
)
from meridian_storage.object_common.documents import (
    compatibility_document,
    object_expression_contract,
    object_result_contract,
    payload_reference_contract,
    public_api_contract,
    signed_reference_contract,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _schemas() -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for path in sorted((CONTRACTS / "object").glob("*.schema.json")):
        document = cast(Mapping[str, Any], _json(path))
        result[cast(str, document["$id"])] = document
    return result


def _registry(schemas: Mapping[str, Mapping[str, Any]]) -> Registry:
    return Registry().with_resources(
        (identifier, Resource.from_contents(document)) for identifier, document in schemas.items()
    )


def _fixture_documents(kind: str, name: str) -> Iterator[Mapping[str, Any]]:
    fixture = cast(Mapping[str, Any], _json(CONTRACTS / "fixtures" / kind / name))
    for item in cast(list[Mapping[str, Any]], fixture["documents"]):
        if kind == "invalid":
            yield cast(Mapping[str, Any], item["document"])
        else:
            yield item


@pytest.mark.contract
def test_all_json_schemas_are_draft_2020_12_and_self_valid() -> None:
    schemas = _schemas()
    assert len(schemas) == 4
    for schema in schemas.values():
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$comment"] == "SPDX-License-Identifier: Apache-2.0"
        Draft202012Validator.check_schema(schema)


@pytest.mark.contract
@pytest.mark.parametrize(
    ("schema_name", "fixture_name"),
    [
        ("meridian-object-expression.v1.schema.json", "object-expressions.json"),
        ("meridian-object-result.v1.schema.json", "object-results.json"),
        ("meridian-object-payload-reference.v1.schema.json", "payload-references.json"),
        ("meridian-object-signed-reference.v1.schema.json", "signed-references.json"),
    ],
)
def test_valid_and_invalid_fixtures_match_language_neutral_contracts(
    schema_name: str,
    fixture_name: str,
) -> None:
    schemas = _schemas()
    schema = next(value for key, value in schemas.items() if key.endswith(schema_name))
    validator = Draft202012Validator(schema, registry=_registry(schemas))
    valid = tuple(_fixture_documents("valid", fixture_name))
    invalid = tuple(_fixture_documents("invalid", fixture_name))
    assert valid and invalid
    for document in valid:
        validator.validate(document)
    for document in invalid:
        assert list(validator.iter_errors(document)), document


@pytest.mark.contract
def test_expression_fixtures_also_normalize_through_released_core() -> None:
    provider = ObjectCatalogProvider()
    methods: set[str] = set()
    for document in _fixture_documents("valid", "object-expressions.json"):
        expression = Expression(
            cast(str, document["catalog"]),
            cast(str, document["method"]),
            cast(Mapping[str, Any], document["arguments"]),
            format_version=cast(str, document["formatVersion"]),
        )
        operation = provider.normalize(expression)
        methods.add(expression.method)
        assert operation.operation_contract == f"meridian.object.{expression.method}"
        assert operation.operation_version == "1.0.0"
    assert methods == {item.method for item in provider.manifest().operations}


@pytest.mark.contract
def test_payload_signed_and_metadata_fixtures_round_trip_runtime_values() -> None:
    payloads = tuple(_fixture_documents("valid", "payload-references.json"))
    for document in payloads:
        assert PayloadReference.from_mapping(document).to_dict() == document

    signed = next(_fixture_documents("valid", "signed-references.json"))
    reference = SignedObjectReference.from_mapping(signed)
    assert reference.to_dict() == signed
    reference.verify(
        HmacSha256Key("fixture-key", b"x" * 32),
        operation="get",
        audience="fixture-reader",
    )

    metadata_result = next(_fixture_documents("valid", "object-results.json"))
    metadata = cast(Mapping[str, object], metadata_result["metadata"])
    assert ObjectMetadata(**_metadata_arguments(metadata)).to_dict() == metadata


def _metadata_arguments(value: Mapping[str, object]) -> dict[str, Any]:
    from meridian_storage.object_common import parse_object_metadata

    parsed = parse_object_metadata(value)
    return {
        "object_ref": parsed.object_ref,
        "digest": parsed.digest,
        "byte_length": parsed.byte_length,
        "media_type": parsed.media_type,
        "created_at": parsed.created_at,
        "creation_context": parsed.creation_context,
        "user_metadata": parsed.user_metadata,
        "mutability": parsed.mutability,
        "provenance": parsed.provenance,
        "format_version": parsed.format_version,
    }


@pytest.mark.contract
def test_public_api_compatibility_and_document_loaders_match_source() -> None:
    ledger = public_api_contract()
    assert ledger == _json(CONTRACTS / "public-api" / "meridian-object-common.v1.json")
    assert ledger["exports"] == sorted(public_api.__all__)
    assert ledger["errorCodes"] == sorted(item.value for item in ObjectErrorCode)
    assert ledger["operations"] == sorted(
        item.method for item in ObjectCatalogProvider().manifest().operations
    )
    assert compatibility_document() == _json(ROOT / "compatibility.json")
    assert object_expression_contract() == _json(
        CONTRACTS / "object" / "meridian-object-expression.v1.schema.json"
    )
    assert object_result_contract() == _json(
        CONTRACTS / "object" / "meridian-object-result.v1.schema.json"
    )
    assert payload_reference_contract() == _json(
        CONTRACTS / "object" / "meridian-object-payload-reference.v1.schema.json"
    )
    assert signed_reference_contract() == _json(
        CONTRACTS / "object" / "meridian-object-signed-reference.v1.schema.json"
    )


@pytest.mark.contract
def test_contract_tree_contains_no_provider_or_sixth_catalog_values() -> None:
    forbidden = (
        '"catalog": "ontology"',
        '"catalog": "query"',
        '"catalog": "projection"',
        '"catalog": "telemetry"',
        '"catalog": "audit"',
        '"catalog": "lineage"',
        "amazonaws.com",
        "oci://",
        '"accessKey"',
        '"secretKey"',
    )
    for path in sorted(CONTRACTS.rglob("*.json")):
        if "fixtures/invalid" in path.as_posix():
            continue
        text = path.read_text(encoding="utf-8")
        assert not any(value in text for value in forbidden), path
