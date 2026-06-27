# Open-Source Boundary

ProofAlpha is distributed as an independent open-source repository.

## Provenance

The initial `src/engine` code is published with authorization from its copyright owner. The release process copies the approved implementation byte-for-byte, verifies every file with SHA-256, and records a combined tree hash in `PUBLIC_EXPORT_MANIFEST.json`.

No local source path, credential, account record, generated trading output, captured database, private dataset, model artifact, virtual environment, vendor tree, or unrelated repository is included.

## Repository isolation

After publication, contributors and coding agents must work only from files in this repository and explicitly documented public dependencies. They must not inspect unrelated local projects or import code with unclear provenance.

## Acceptable contributions

Contributions may contain:

- original contributor work;
- modifications to ProofAlpha source;
- implementations based on public standards and protocols;
- dependencies with compatible, documented licenses;
- third-party material with clear attribution and redistribution rights.

## Prohibited material

Do not contribute:

- credentials or account information;
- proprietary strategy parameters or private datasets;
- generated databases, logs, or model files containing private information;
- third-party code without license permission;
- copied code whose origin cannot be documented;
- machine-specific paths or deployment secrets.

## Contribution certification

By submitting a contribution, the contributor confirms they have the right to license it under the project license. New runtime dependencies and imported components require provenance and license review and must be reflected in `THIRD_PARTY_NOTICES.md`.
