<!-- SPDX-License-Identifier: Apache-2.0 -->

# Security policy

Report suspected vulnerabilities privately through GitHub's security advisory
interface for this repository. Do not include credentials, provider endpoints,
private object identifiers, payload bytes, or production configuration in a
public issue.

The supported line is the latest 1.x release. Security fixes preserve stable
public error data and redact provider failure details. Payload and signed
reference tokens are capabilities scoped to their composing process or signer;
callers must bound their lifetime, audience, and distribution.
