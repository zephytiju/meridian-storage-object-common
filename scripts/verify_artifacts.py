#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify wheel/sdist ownership, metadata, contracts, and license evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
import zipfile
from email.parser import Parser
from pathlib import Path, PurePosixPath

PACKAGE = "meridian_storage/object_common"
DISTRIBUTION = "meridian-storage-object-common"
VERSION = "1.0.0"


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def reject_generated(names: list[str]) -> None:
    assert not any("__pycache__" in name for name in names)
    assert not any(name.endswith((".pyc", ".pyo")) for name in names)
    assert not any("/.coverage" in name for name in names)
    assert not any("/.git/" in name for name in names)
    assert not any("/.venv/" in name for name in names)


def verify_wheel(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        names = sorted(archive.namelist())
        reject_generated(names)
        required = {
            f"{PACKAGE}/__init__.py",
            f"{PACKAGE}/py.typed",
            f"{PACKAGE}/compatibility.json",
            f"{PACKAGE}/contracts/data/object/meridian-object-expression.v1.schema.json",
            f"{PACKAGE}/contracts/data/object/meridian-object-result.v1.schema.json",
            f"{PACKAGE}/contracts/data/public-api/meridian-object-common.v1.json",
            f"{PACKAGE}/contracts/data/fixtures/valid/object-expressions.json",
        }
        assert required <= set(names), sorted(required - set(names))
        assert "meridian_storage/__init__.py" not in names
        assert not any(name.startswith("tests/") for name in names)
        source_entries = [
            name for name in names if ".dist-info/" not in name and not name.endswith("/")
        ]
        assert all(name.startswith(f"{PACKAGE}/") for name in source_entries), source_entries
        assert not any(
            forbidden in name.casefold()
            for name in source_entries
            for forbidden in ("s3", "oci", "boto", "credential", "provision")
        )

        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = Parser().parsestr(archive.read(metadata_name).decode("utf-8"))
        assert metadata["Name"] == DISTRIBUTION
        assert metadata["Version"] == VERSION
        assert metadata["Requires-Python"] == ">=3.12"
        assert metadata["License-Expression"] == "Apache-2.0"
        dependencies = metadata.get_all("Requires-Dist", [])
        assert "meridian-storage-core==1.0.0" in dependencies
        assert "meridian-storage-semantics==1.0.0" in dependencies
        license_files = [name for name in names if ".dist-info/licenses/" in name]
        assert any(name.endswith("/LICENSE") for name in license_files)
        assert any(name.endswith("/NOTICE") for name in license_files)
        entry_points_name = next(
            name for name in names if name.endswith(".dist-info/entry_points.txt")
        )
        entry_points = archive.read(entry_points_name).decode("utf-8")
        assert entry_points == (
            "[meridian_storage.catalogs]\n"
            "object = meridian_storage.object_common.catalog:ObjectCatalogProvider\n"
        )
    return {"kind": "wheel", "entries": len(names)}


def verify_sdist(path: Path) -> dict[str, object]:
    with tarfile.open(path, "r:gz") as archive:
        names = sorted(member.name for member in archive.getmembers())
        reject_generated(names)
        roots = {PurePosixPath(name).parts[0] for name in names}
        assert len(roots) == 1
        root = next(iter(roots))
        required = {
            f"{root}/CHANGELOG.md",
            f"{root}/LICENSE",
            f"{root}/NOTICE",
            f"{root}/README.md",
            f"{root}/pyproject.toml",
            f"{root}/compatibility.json",
            f"{root}/contracts/public-api/meridian-object-common.v1.json",
            f"{root}/src/{PACKAGE}/__init__.py",
            f"{root}/tests/test_conformance.py",
            f"{root}/scripts/verify_artifacts.py",
            f"{root}/.github/workflows/ci.yml",
        }
        assert required <= set(names), sorted(required - set(names))
        assert f"{root}/src/meridian_storage/__init__.py" not in names
        assert not any(
            name.startswith(f"{root}/src/") and "object_common" not in name for name in names
        )
    return {"kind": "sdist", "entries": len(names)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifacts", nargs="+", type=Path)
    arguments = parser.parse_args()
    evidence: list[dict[str, object]] = []
    for path in sorted(arguments.artifacts):
        assert path.is_file(), path
        if path.suffix == ".whl":
            detail = verify_wheel(path)
        elif path.name.endswith(".tar.gz"):
            detail = verify_sdist(path)
        else:
            raise AssertionError(f"unsupported artifact: {path}")
        evidence.append(
            {
                "file": path.name,
                "sha256": digest(path),
                "size": path.stat().st_size,
                **detail,
            }
        )
    kinds = {item["kind"] for item in evidence}
    assert kinds == {"wheel", "sdist"}, kinds
    print(json.dumps({"artifacts": evidence}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
