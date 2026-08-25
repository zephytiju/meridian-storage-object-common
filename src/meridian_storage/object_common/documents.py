# SPDX-License-Identifier: Apache-2.0
"""Load the exact packaged language-neutral Object contracts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from importlib import resources
from pathlib import Path
from typing import cast


def object_expression_contract() -> Mapping[str, object]:
    return _document("object/meridian-object-expression.v1.schema.json")


def object_result_contract() -> Mapping[str, object]:
    return _document("object/meridian-object-result.v1.schema.json")


def payload_reference_contract() -> Mapping[str, object]:
    return _document("object/meridian-object-payload-reference.v1.schema.json")


def signed_reference_contract() -> Mapping[str, object]:
    return _document("object/meridian-object-signed-reference.v1.schema.json")


def public_api_contract() -> Mapping[str, object]:
    return _document("public-api/meridian-object-common.v1.json")


def compatibility_document() -> Mapping[str, object]:
    packaged = resources.files("meridian_storage.object_common").joinpath("compatibility.json")
    if packaged.is_file():
        return cast(Mapping[str, object], json.loads(packaged.read_text(encoding="utf-8")))
    source = Path(__file__).resolve().parents[3] / "compatibility.json"
    return cast(Mapping[str, object], json.loads(source.read_text(encoding="utf-8")))


def _document(relative: str) -> Mapping[str, object]:
    packaged = resources.files("meridian_storage.object_common").joinpath(
        "contracts", "data", *relative.split("/")
    )
    if packaged.is_file():
        return cast(Mapping[str, object], json.loads(packaged.read_text(encoding="utf-8")))
    source = Path(__file__).resolve().parents[3] / "contracts" / relative
    return cast(Mapping[str, object], json.loads(source.read_text(encoding="utf-8")))


__all__ = [
    "compatibility_document",
    "object_expression_contract",
    "object_result_contract",
    "payload_reference_contract",
    "public_api_contract",
    "signed_reference_contract",
]
