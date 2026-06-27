# Security Policy

## Supported versions

Until the first stable release, only the latest tagged ProofAlpha version receives security fixes.

## Reporting a vulnerability

Do not disclose exploitable vulnerabilities in a public issue, discussion, pull request, log, or screenshot.

Use GitHub private vulnerability reporting when it is enabled for the repository. If that channel is unavailable, contact the maintainer through the public repository profile without including exploit details in a public message.

Include:

- affected version or commit;
- impact and attack preconditions;
- a minimal reproduction;
- whether credentials, order authority, private data, artifact integrity, or package supply chain are affected;
- a suggested remediation, if known.

Do not test against accounts, exchanges, systems, or data that you do not own or have explicit permission to assess.

## High-priority vulnerability classes

- execution-mode or risk-gate bypass;
- credential or account-data exposure;
- order duplication or incorrect reconciliation;
- malicious archive extraction or code execution;
- unsafe strategy or plugin loading;
- model output changing trusted policy;
- stale or manipulated data accepted as healthy;
- dashboard write access, XSS, SQL injection, or path traversal;
- release or dependency supply-chain compromise;
- evidence tampering or silent data leakage.

## Disclosure process

Maintainers should:

1. acknowledge the report privately;
2. reproduce and classify impact;
3. develop and test a fix;
4. prepare an advisory and affected-version statement;
5. release the fix before broad disclosure where practical;
6. credit the reporter unless anonymity is requested.

Response times are goals, not guarantees.
