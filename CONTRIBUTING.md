# Contributing

Thanks for your interest in improving `kurrent-sqlalchemy`.

## Reporting issues

Please include:

- The KurrentDB version you're running against (Flight SQL is experimental and behavior changes between releases).
- The Apache Superset version, if the issue involves Superset.
- The exact SQL that triggered the problem.
- The full traceback (from Superset logs or your Python script), not just the user-facing error.

If KurrentDB rejects a query that's syntactically valid PostgreSQL, that's most likely a KurrentDB Flight SQL server bug and should be reported to Kurrent rather than fixed here.

## Local development

```sh
git clone https://github.com/kurrent-io/kurrent-sqlalchemy.git
cd kurrent-sqlalchemy
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

The smoke tests don't require a running KurrentDB. If you want integration tests against a live KurrentDB, you'll need to spin one up locally — see Kurrent's documentation for setup.

## Pull request guidelines

- Run `pytest` before opening a PR.
- Add or update tests for behavior changes. The existing `tests/test_dialect.py` is the pattern.
- Update `CHANGELOG.md` under the `[Unreleased]` section.
- Keep PRs scoped — one fix or feature per PR makes review tractable.

## Release process (maintainers)

See `docs/PYPI-SETUP.md` for the PyPI publishing setup. Once configured:

1. Bump `version` in `pyproject.toml` and `__version__` in `src/kurrent_sqlalchemy/__init__.py`.
2. Move `## [Unreleased]` in `CHANGELOG.md` to a new dated version section.
3. Commit, tag (`git tag vX.Y.Z`), push (`git push && git push --tags`).
4. Create a GitHub Release pointing at the tag. The release workflow handles PyPI upload.

## License

By contributing, you agree your contributions will be licensed under the Apache License 2.0.
