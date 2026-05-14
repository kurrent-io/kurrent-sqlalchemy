# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.1] - 2026-05-14

### Added

- First PyPI release under the new `kurrent-sqlalchemy` name.
- GitHub Actions workflow (`.github/workflows/publish.yml`) that builds the
  package on `v*` tag push, uploads it to PyPI via trusted publishing, and
  creates a GitHub release with notes drawn from the matching CHANGELOG
  section.
- `scripts/release.sh` to automate the release cut: bumps version in
  `pyproject.toml` and `__init__.py`, dates the CHANGELOG entry, commits,
  tags, and pushes.
- Standard Python `.gitignore`.

### Changed

- Renamed PyPI distribution from `kurrentdb-sqlalchemy` to `kurrent-sqlalchemy`
  and Python module from `kurrentdb_sqlalchemy` to `kurrent_sqlalchemy` so
  package names align with the `kurrent-io/kurrent-sqlalchemy` repository.
- The SQLAlchemy URL scheme (`kurrentdb+flightsql://`), dialect class
  (`KurrentDBDialect`), and engine spec class (`KurrentDBEngineSpec`) are
  unchanged. Existing connection strings and Superset configurations
  continue to work without modification — only the import path changes.

### Migration from 0.2.0

\`\`\`python
# Before
from kurrentdb_sqlalchemy.superset import KurrentDBEngineSpec, install_superset_patches

# After
from kurrent_sqlalchemy.superset import KurrentDBEngineSpec, install_superset_patches
\`\`\`

## [0.2.0] - Unreleased

### Added

- Static schema reflection for `kdb.records`. Superset's schema browser now
  shows a populated table with the known KurrentDB event-log column set
  instead of an empty list.
- `KURRENTDB_MAX_ROWS` environment variable (default `10000`) to cap result
  size on KurrentDB queries that don't include their own `LIMIT`. Set to `0`
  to disable.
- `install_superset_patches` self-tests every patch after installation and
  logs an error if any failed to attach, surfacing broken deployments
  during startup rather than at first query.
- `Database.db_engine_spec` bind patch ensures KurrentDB connections
  resolve to `KurrentDBEngineSpec` rather than falling back to
  `BaseEngineSpec`. This works around `DB_ENGINE_SPEC_OVERRIDES` only
  replacing existing engine entries in Apache Superset 4.x.

### Changed

- Diagnostic stderr prints replaced with standard Python logging.
  Install/lifecycle messages log at INFO; per-query bypass messages log at
  DEBUG. Set `kurrentdb_sqlalchemy.superset` log level to control noise.
- Package author/maintainer set to Kurrent, Inc.
- Status bumped from Alpha to Beta.

## [0.1.0] - 2026-05-08

### Added

- Initial `KurrentDBDialect` extending `flightsql.sqlalchemy.FlightSQLDialect`.
- Overrides for `initialize`, `do_ping`, `_check_unicode_returns`,
  `_get_default_schema_name`, `get_isolation_level`, `has_table`, and the
  reflection methods to handle KurrentDB Flight SQL's empty-endpoints
  responses without crashing.
- Optional `KurrentDBEngineSpec` for Apache Superset with configurable
  test query via `KURRENTDB_TEST_QUERY` environment variable.
- SQLAlchemy entry point registration so `kurrentdb+flightsql://` URIs
  resolve automatically after install.
- Smoke tests covering import, override attachment, and entry point
  discovery.
- GitHub Actions CI for Python 3.9 through 3.12.
