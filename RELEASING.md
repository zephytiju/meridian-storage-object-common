<!-- SPDX-License-Identifier: Apache-2.0 -->

# Releasing

1. Update version, changelog, contracts, fixtures, and compatibility/public API ledgers together.
2. Merge a reviewed green pull request to protected `main`.
3. Create and push an annotated `vX.Y.Z` tag on that merge commit.
4. The release workflow verifies tag/version, reruns all gates, performs a fixed-epoch double build and byte comparison, inspects artifacts, emits an SPDX SBOM, attests provenance, and creates a GitHub release.
5. PyPI publication uses GitHub OIDC only when repository variable `PYPI_TRUSTED_PUBLISHING_ENABLED=true` and the owner has configured the `pypi` environment and trusted publisher. Never bypass namespace ownership, MFA, or trusted publishing. If the first GitHub release precedes that owner-only setup, dispatch `Release` again at the existing version tag after enabling the variable; the workflow re-verifies and reuses the release before trusted publication.

Subsequent releases follow the same CI path. Do not manually replace attested
release assets.
