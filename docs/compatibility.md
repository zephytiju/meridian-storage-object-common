<!-- SPDX-License-Identifier: Apache-2.0 -->

# Compatibility

Version 1.0.0 requires Python 3.12 or newer and depends exactly on
`meridian-storage-core==1.0.0` and `meridian-storage-semantics==1.0.0`.
`compatibility.json` records the independently downloaded wheel and source
distribution SHA-256 values, the Core public-contract commit, the Semantics
release commit, and the locked design revisions.

The Object Catalog contract and all eight Operation contracts are version
`1.0.0`. Downstream runtimes should use Core discovery deployment pins and the
manifest fingerprint to prevent package or contract substitution. Adapters
negotiate each normalized Operation's Core `CapabilityRequirement`; this
package never selects an Engine or Adapter.

Compatibility changes to serialized fields, exact method membership, stable
error codes, public exports, operation guarantees, or capability names require
a versioned contract update and approved design write-back. Additive
implementation changes that preserve these checked-in ledgers can remain within
the existing contract version.
