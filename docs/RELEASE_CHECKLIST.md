# Release Checklist

Use this checklist before pushing a public release or applying to maintainer-support programs.

## 1. Clean public boundary

Confirm only source, docs, examples, workflows, and intended project metadata are staged.

```bash
git status --short --ignored
python scripts/check_repository_secrets.py
python scripts/verify_public_export.py --root .
```

Do not publish generated databases, private datasets, logs, model artifacts, virtual environments, local credentials, or machine-specific deployment files.

## 2. Supported runtime

Run release gates on Python 3.12 or 3.13. The project does not claim support for Python 3.14 yet.

```bash
python --version
proofalpha doctor --format json
```

## 3. Full verification gate

```bash
python -m unittest discover -s tests -q
python -m compileall -q src tests scripts
python -m ruff check src --select F821,F811
python scripts/check_repository_secrets.py
python scripts/verify_public_export.py --root .
python -m pip_audit -r requirements-core.txt
proofalpha doctor --format json
proofalpha list-skills --format json
proofalpha run --config examples/minimal_builtin_study.json --output-dir outputs/release-smoke
python -m build
```

Pyright annotation cleanup is known technical debt and should not be represented as a passing release gate.

## 4. Optional local checks

```bash
python -m pip install -e .[docs]
mkdocs build --strict
docker compose config --quiet
docker compose run --rm proofalpha
docker compose --profile demo run --rm demo
```

Run these where Docker and MkDocs are available. CI also covers docs and Docker smoke checks.

## 5. Public launch assets

Before announcing the repository, add or verify:

- README safe demo command.
- Expected demo artifacts and blocked-result explanation.
- Security, disclaimer, governance, support, and contribution docs.
- Apache-2.0 license and third-party notices.
- Issue templates and pull request template.
- CI workflows for tests, docs, package, Docker, and security.
- Brand assets or screenshots that do not reveal private data.

## 6. Release notes

A release note should include:

- version number;
- supported Python versions;
- safe demo command;
- key features;
- safety boundary;
- verification commands or CI status;
- known limitations;
- disclaimer that results are historical, simulated, or paper unless explicitly labeled otherwise.

## 7. Maintainer-program applications

Apply only with current, verifiable evidence:

- public repository URL;
- maintainer role;
- CI status;
- release history;
- stars, forks, downloads, contributors, issues, or external usage if available;
- clear explanation of how support improves public open-source maintenance.

Do not inflate adoption metrics or imply guaranteed trading outcomes.
