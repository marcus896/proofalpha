# Third-Party Notices

ProofAlpha's core runtime depends on the packages below. Versions shown are the versions used during the public-export verification on 2026-06-26; supported ranges remain defined in `pyproject.toml` and `requirements-core.txt`.

| Package | Verified version | Purpose | License family | Distribution source |
|---|---:|---|---|---|
| DuckDB | 1.5.4 | Snapshot catalog and Parquet persistence | MIT | Python package metadata |
| NumPy | 2.2.6 | Numerical arrays and research calculations | BSD-3-Clause family | Python package metadata |
| Numba | 0.65.1 | Optional compiled simulation acceleration | BSD family | Python package metadata |
| Optuna | 4.9.0 | Bounded parameter search | MIT | Python package metadata |
| websockets | 15.0.1 | Public WebSocket collection | BSD-3-Clause | Python package metadata |

These packages may bundle or depend on additional components. Their installed distributions contain the authoritative license notices. Binary NumPy distributions may include OpenBLAS, LAPACK, and compiler runtime components under their respective licenses and exceptions.

Optional extras introduce additional dependencies. Before an optional extra is included in a release image or hosted service, maintainers must:

1. resolve the exact dependency graph in a clean environment;
2. run vulnerability and license audits;
3. preserve required notices;
4. update this file and the release SBOM.

Generated files, sample data, icons, fonts, screenshots, and copied specifications also require provenance and redistribution review.

ProofAlpha brand SVGs are original repository assets and do not bundle font files. They reference system font fallbacks only.
