<!-- SPDX-License-Identifier: Apache-2.0 -->

# Contributing

Changes must preserve the one-repository/one-package boundary, Apache-2.0
licensing, provider neutrality, and the exact V1 Object Catalog surface. Do not
add provider SDKs, credentials, physical locators, provisioning, state, ACL,
migration, recovery, or lifecycle choices.

Install `.[test]`, run every verification command in the README, and include
tests for new behavior. Update code, JSON Schemas, fixtures, public API and
compatibility ledgers, documentation, and changelog together whenever their
contract changes. Architecture or public-interface changes require approved
design write-back before implementation.

Contributions are submitted under Apache License 2.0. Source and contract files
must carry an SPDX `Apache-2.0` marker where the format permits it.
