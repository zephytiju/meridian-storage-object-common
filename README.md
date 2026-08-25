<!-- SPDX-License-Identifier: Apache-2.0 -->

# Meridian Storage Object Common

`meridian-storage-object-common` is the provider-neutral Meridian V1 Object
Catalog contract package. It supplies mapping-first Object Expressions,
deterministic Core Operation normalization, bounded streaming payload handles,
portable metadata and content identity, byte ranges, multipart Adapter
contracts, consumer-selectable immutability and retention intent, signed
logical references, capability negotiation, stable errors, JSON contracts, and
a reusable downstream Adapter conformance runner.

The distribution contains exactly one Python package,
`meridian_storage.object_common`. It consumes the released
`meridian-storage-core==1.0.0` and `meridian-storage-semantics==1.0.0`
distributions. It contains no provider implementation, cloud credential,
physical locator, provisioning, state, ACL, migration, recovery, or lifecycle
policy.

## Install

```console
python -m pip install meridian-storage-object-common==1.0.0
```

Python 3.12 or newer is required.

## Stream an Object put

```python
from io import BytesIO

from meridian_storage.object_common import ObjectCatalogProvider, PayloadRegistry

payloads = PayloadRegistry()
payload = payloads.register_stream(
    BytesIO(b"immutable bytes"),
    expected_length=15,
    expected_digest="sha256:59d8792018a51a408d2738f31eedebd6fe9926cc4260fa168a38710bc51d7e30",
)

provider = ObjectCatalogProvider()
expression = provider.create_surface().put(
    resource="assets.release_artifacts",
    object_id="v1/example.bin",
    payload=payload,
    media_type="application/octet-stream",
    create_only=True,
    immutability={"mutability": "immutable", "publishOnce": True},
)
operation = provider.normalize(expression)
```

The Core `Expression` and `Operation` remain deterministic JSON. Bytes stay
outside that envelope in the explicit process-local `PayloadRegistry`; the
serialized payload token is opaque and cannot be a URL or provider locator.

## Exact V1 surface

The Object Catalog exposes exactly these methods:

- `publish_schema` and `create_resource`
- `put`, `get`, `stat`, and `read_range`
- bounded maintenance `list`
- exact-version, policy-aware `delete`

Artifact and media are Object profiles, not additional Catalogs. Immutability
is selected by the Resource profile and per-put intent. Retention values express
portable intent and never imply a WORM or regulatory certification.

## Downstream Adapter conformance

An Adapter test target implements `ObjectConformanceTarget` and passes it to
`run_object_conformance`. The runner verifies unknown-length streaming put,
content identity, metadata visibility, streaming get, inclusive range reads,
bounded prefix listing, conditional create conflict, digest mismatch,
exact-version delete, and missing-object behavior.

## Contracts and verification

Language-neutral Draft 2020-12 JSON Schemas, the public API ledger, and
valid/invalid fixtures are in [`contracts`](contracts). Exact predecessor
artifacts and locked design revisions are recorded in
[`compatibility.json`](compatibility.json).

```console
python -m pip install '.[test]'
ruff format --check src tests scripts
ruff check src tests scripts
mypy src
python scripts/verify_contracts.py
pytest --cov=meridian_storage.object_common --cov-report=term-missing
```

Release builds are produced twice with a fixed epoch, compared byte-for-byte,
inspected for package and license boundaries, clean-installed against released
predecessors, and accompanied by an SPDX 2.3 SBOM and GitHub provenance.

See [`docs/architecture.md`](docs/architecture.md),
[`docs/contracts.md`](docs/contracts.md), and
[`docs/compatibility.md`](docs/compatibility.md).

## License

Copyright 2026 Meridian contributors. Licensed under Apache License 2.0; see
[`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
