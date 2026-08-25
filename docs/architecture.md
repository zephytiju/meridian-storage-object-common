<!-- SPDX-License-Identifier: Apache-2.0 -->

# Architecture and authority boundary

This package owns the provider-neutral public contract and conformance layer for
the single Meridian `object` Catalog. Its design baseline is Meridian HLD
revision 56, Catalogs and Public Interfaces revision 70, and the Object Common
LLD revision 12.

Consumers build mapping-first Core `Expression` values through
`ObjectCatalogSurface`. `ObjectCatalogProvider.normalize` validates the wire
arguments, rejects private deployment configuration, produces the corresponding
serialized Core `Operation`, and attaches capability requirements derived from
the individual request. The manifest is deterministic and contains exactly the
eight V1 Object methods.

Payload streams deliberately do not enter Core's JSON envelope. A consumer
registers a `PayloadSource` in an explicit process-local `PayloadRegistry` and
places only its opaque `PayloadReference` in an Expression. An Adapter resolves
that reference using the registry supplied by the execution composition. Tokens
are bounded, non-URL values; they carry optional length and SHA-256 expectations
but no physical location or credential. Streaming is bounded by chunk size and
verifies length and digest before metadata can be committed.

The put state machine is `NEW -> UPLOADING -> VERIFYING -> COMMITTED`. Failures
before a possible physical commit become `ABORTED`; failures after an uncertain
physical commit become `ORPHAN_CANDIDATE`. Orphan enumeration and cleanup are
Adapter maintenance responsibilities and are intentionally absent from the
consumer Catalog surface.

The optional `MultipartAdapter` protocol is an Adapter-internal transfer
extension negotiated through Object put capabilities. It does not add a Catalog
method. Signed references authorize a bounded set of logical read operations;
they contain a digest-pinned `ObjectReference`, audience, expiry, nonce, and
signature, never a provider URL.

Provider Adapter repositories own S3, OCI, or other physical behavior.
Platform/Vangu IaC owns Engine selection, provisioning and references, state,
identity, ACLs, migrations, recovery, and lifecycle. This package does not
import or encode any of those concerns. Artifact and media remain Object
profiles supplied by the released Semantics package.
