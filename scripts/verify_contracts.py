#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify checked-in V1 contracts against the Python implementation."""

from __future__ import annotations

import ast
import json
import tomllib
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

import meridian_storage.object_common as object_common
from meridian_storage import Expression
from meridian_storage.object_common import (
    ObjectCatalogProvider,
    ObjectErrorCode,
    PayloadReference,
    SignedObjectReference,
)

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def fixtures(kind: str, name: str) -> Iterator[Mapping[str, Any]]:
    document = load(ROOT / "contracts" / "fixtures" / kind / name)
    for item in cast(list[Mapping[str, Any]], document["documents"]):
        yield cast(Mapping[str, Any], item["document"] if kind == "invalid" else item)


def main() -> None:
    public = load(ROOT / "contracts/public-api/meridian-object-common.v1.json")
    assert public["version"] == object_common.__version__ == "1.0.1"
    assert public["core"] == "1.0.0"
    assert public["semantics"] == "1.0.0"
    assert public["exports"] == sorted(object_common.__all__)
    assert public["errorCodes"] == sorted(item.value for item in ObjectErrorCode)

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["name"] == "meridian-storage-object-common"
    assert project["version"] == object_common.__version__
    assert project["license"] == "Apache-2.0"
    assert project["dependencies"] == [
        "meridian-storage-core==1.0.0",
        "meridian-storage-semantics==1.0.0",
    ]

    compatibility = load(ROOT / "compatibility.json")
    assert compatibility["version"] == object_common.__version__
    assert compatibility["core"]["version"] == "1.0.0"
    assert compatibility["semantics"]["version"] == "1.0.0"
    assert compatibility["design"] == {
        "catalogsRevision": 121,
        "hldRevision": 114,
        "objectLldRevision": 35,
    }

    provider = ObjectCatalogProvider()
    manifest = provider.manifest()
    methods = sorted(item.method for item in manifest.operations)
    assert methods == public["operations"]
    assert len(methods) == 8
    assert manifest.catalog_name == "object"
    assert manifest.package_name == project["name"]
    assert manifest.package_version == project["version"]
    assert manifest.catalog_contract_version == public["catalogContractVersion"]

    schemas: dict[str, Mapping[str, Any]] = {}
    for path in sorted((ROOT / "contracts/object").glob("*.schema.json")):
        schema = load(path)
        Draft202012Validator.check_schema(schema)
        schemas[cast(str, schema["$id"])] = schema
    registry = Registry().with_resources(
        (identifier, Resource.from_contents(schema)) for identifier, schema in schemas.items()
    )
    fixtures_by_schema = {
        "meridian-object-expression.v1.schema.json": "object-expressions.json",
        "meridian-object-result.v1.schema.json": "object-results.json",
        "meridian-object-payload-reference.v1.schema.json": "payload-references.json",
        "meridian-object-signed-reference.v1.schema.json": "signed-references.json",
    }
    fixture_count = 0
    for identifier, schema in schemas.items():
        fixture_name = next(
            fixture for suffix, fixture in fixtures_by_schema.items() if identifier.endswith(suffix)
        )
        validator = Draft202012Validator(schema, registry=registry)
        for document in fixtures("valid", fixture_name):
            validator.validate(document)
            fixture_count += 1
        for document in fixtures("invalid", fixture_name):
            assert list(validator.iter_errors(document)), document
            fixture_count += 1

    normalized: set[str] = set()
    for document in fixtures("valid", "object-expressions.json"):
        expression = Expression(
            cast(str, document["catalog"]),
            cast(str, document["method"]),
            cast(Mapping[str, Any], document["arguments"]),
            format_version=cast(str, document["formatVersion"]),
        )
        operation = provider.normalize(expression)
        normalized.add(expression.method)
        assert operation.operation_contract == f"meridian.object.{expression.method}"
    assert normalized == set(methods)

    for document in fixtures("valid", "payload-references.json"):
        assert PayloadReference.from_mapping(document).to_dict() == document
    for document in fixtures("valid", "signed-references.json"):
        assert SignedObjectReference.from_mapping(document).to_dict() == document

    forbidden_imports = {"boto", "boto3", "botocore", "oci", "s3fs"}
    for path in sorted((ROOT / "src").rglob("*.py")):
        source = path.read_text(encoding="utf-8").casefold()
        assert "nativequery" not in source, path
        tree = ast.parse(source)
        imports = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert not imports & forbidden_imports, path

    print(
        json.dumps(
            {
                "errors": len(ObjectErrorCode),
                "fixtures": fixture_count,
                "manifestFingerprint": manifest.fingerprint,
                "methods": methods,
                "schemas": len(schemas),
                "version": object_common.__version__,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
