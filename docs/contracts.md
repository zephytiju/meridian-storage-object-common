<!-- SPDX-License-Identifier: Apache-2.0 -->

# Public contracts

## Object Catalog methods

| Method | Contract | Read only | Idempotency | Required baseline behavior |
| --- | --- | --- | --- | --- |
| `publish_schema` | `meridian.object.publish_schema` | no | always | logical metadata publication |
| `create_resource` | `meridian.object.create_resource` | no | always | logical Object Resource |
| `put` | `meridian.object.put` | no | conditional | streaming, SHA-256, metadata after commit |
| `get` | `meridian.object.get` | yes | always | verified streaming payload |
| `stat` | `meridian.object.stat` | yes | always | canonical `meridian.object.v1` metadata |
| `read_range` | `meridian.object.read_range` | yes | always | inclusive verified range |
| `list` | `meridian.object.list` | yes | always | bounded maintenance prefix list |
| `delete` | `meridian.object.delete` | no | always | digest-pinned exact-version delete |

Every contract and Operation version is `1.0.0`. Request-specific requirements
cover conditional create, signed references, object/range/page limits,
immutability intent, retention intent, and explicit retention enforcement.

## Wire documents

- `meridian-object-expression.v1.schema.json` defines exact serialized
  Expressions for all eight methods.
- `meridian-object-result.v1.schema.json` defines normalized metadata, payload,
  range, list, and deletion data returned by downstream execution targets.
- `meridian-object-payload-reference.v1.schema.json` defines the process-local
  streaming handle outside the Core JSON payload boundary.
- `meridian-object-signed-reference.v1.schema.json` defines digest-pinned signed
  logical references for `get`, `read_range`, and `stat`.
- `meridian-object-common.v1.json` is the checked-in Python public API and stable
  error-code ledger.

All schemas use JSON Schema Draft 2020-12, reject unknown contract fields, and
are exercised by valid and invalid conformance fixtures. Object metadata is not
redefined here: `ObjectMetadata`, `ObjectReference`, and `ObjectProfile` are
imported from and wire-compatible with `meridian-storage-semantics==1.0.0`.

## Ranges, immutability, retention, and multipart

Byte ranges are zero-based and inclusive. A request is either start/end, an
open-ended start, or a positive suffix length. A resolved range records start,
end, length, and total Object length.

Immutability intent is `mutable` or `immutable`, with optional publish-once.
Artifact profiles always resolve to immutable publish-once behavior and a put
cannot weaken an immutable Resource profile. Retention can provide a UTC
deadline, a logical policy name, or both. `requireEnforcement` converts that
intent into a required Adapter guarantee; the value itself makes no physical or
regulatory claim.

Multipart sessions and parts use opaque tokens and portable SHA-256 content
identity. Part numbers are positive and completion requires a contiguous
one-based sequence whose byte lengths equal the final Object length.
