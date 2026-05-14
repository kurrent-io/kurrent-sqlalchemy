# kurrent-sqlalchemy

SQLAlchemy dialect and Apache Superset engine spec for [KurrentDB](https://kurrent.io)'s Arrow Flight SQL endpoint.

## Why this exists

KurrentDB ships an experimental Arrow Flight SQL surface for querying event streams via SQL. Pointing existing SQLAlchemy-based tools (Apache Superset, Metabase, Hex, etc.) at it doesn't work out of the box because:

- The upstream [`flightsql-dbapi`](https://github.com/influxdata/flightsql-dbapi) driver assumes a fully-implemented Flight SQL server. It does `info.endpoints[0].ticket` without guards on every metadata RPC. KurrentDB's Flight SQL returns empty `endpoints` for `CommandGetSqlInfo`, `GetCatalogs`, `GetDbSchemas`, and `GetTables`, so the driver crashes with `IndexError: list index out of range` on connection setup.
- KurrentDB rejects context-free queries like `SELECT 1`, which SQLAlchemy and Superset use as liveness probes.
- Apache Superset rewrites outgoing SQL through `sqlglot` (parsing as PostgreSQL but rendering with no dialect), which turns PostgreSQL JSON operators like `data::json->>'field'` into Trino-style `JSON_EXTRACT_SCALAR(CAST(data AS JSON), '$.field')` calls KurrentDB cannot execute.
- Superset's `DB_ENGINE_SPEC_OVERRIDES` config setting only *replaces existing* engine entries — it doesn't *add new ones* — so a naive override of a non-built-in engine like KurrentDB is silently dropped.

This package solves all four problems. The dialect handles crashes; the Superset integration handles SQL rewriting, engine binding, and result-size caps.

## Status

Beta. Tested against KurrentDB 26.1 RC2 experimental Flight SQL builds and Apache Superset 4.x.

Expect changes as KurrentDB's Flight SQL implementation matures — and the workarounds in this package to become unnecessary as that happens.

## Installation

```sh
pip install kurrent-sqlalchemy
```

For Apache Superset deployments, include the optional extra:

```sh
pip install kurrent-sqlalchemy[superset]
```

## Usage

### Plain SQLAlchemy

The dialect auto-registers via entry point on install — no explicit import needed.

```python
from sqlalchemy import create_engine, text

engine = create_engine("kurrentdb+flightsql://admin:changeit@localhost:2113")

with engine.connect() as conn:
    result = conn.execute(text(
        "SELECT data::json->>'OrderId' as order_id "
        "FROM kdb.records WHERE category = 'orders' LIMIT 10"
    ))
    for row in result:
        print(row)
```

KurrentDB Flight SQL connections are TLS-by-default. If KurrentDB uses a self-signed certificate, the client needs to trust it — set `GRPC_DEFAULT_SSL_ROOTS_FILE_PATH` to point at your CA bundle:

```sh
export GRPC_DEFAULT_SSL_ROOTS_FILE_PATH=/path/to/ca.crt
```

### Apache Superset

#### 1. Install into your Superset environment

If you're running Superset via the official Docker setup, add to `docker/requirements-local.txt`:

```
kurrent-sqlalchemy[superset]
```

Then restart **all** Superset services — web, worker, beat, init each run pip-install on startup independently:

```sh
docker compose stop superset superset-init superset-worker superset-worker-beat
docker compose up -d superset superset-init superset-worker superset-worker-beat
```

#### 2. Wire it up in `superset_config.py`

```python
from kurrent_sqlalchemy.superset import (
    KurrentDBEngineSpec,
    install_superset_patches,
)

DB_ENGINE_SPEC_OVERRIDES = {"kurrentdb": KurrentDBEngineSpec}
FLASK_APP_MUTATOR = install_superset_patches
```

If you already use `FLASK_APP_MUTATOR` for something else, chain them:

```python
def my_app_mutator(app):
    install_superset_patches(app)
    # ... your existing logic ...

FLASK_APP_MUTATOR = my_app_mutator
```

#### 3. If KurrentDB is running with TLS, mount the CA into the Superset containers

In your `docker-compose.yml`:

```yaml
x-superset-volumes: &superset-volumes
  - ./docker:/app/docker
  - superset_home:/app/superset_home
  - /path/to/your/kurrentdb/certs:/certs:ro

x-superset-environment: &superset-environment
  GRPC_DEFAULT_SSL_ROOTS_FILE_PATH: /certs/ca/ca.crt
```

Add `environment: *superset-environment` to each of the four superset services.

#### 4. Add the database in the Superset UI

- Settings → Database Connections → **+ Database**
- Supported Databases → **Other**
- SQLAlchemy URI: `kurrentdb+flightsql://admin:changeit@<host>:2113`
  - Use the Docker container hostname or IP if Superset reaches KurrentDB across a Docker network, **not** `localhost`.

After clicking Test Connection (or running any SQL Lab query), verify the patches installed correctly by checking the logs:

```sh
docker compose logs superset 2>&1 | grep kurrentdb
```

You should see:

```
kurrentdb: installed Database.db_engine_spec bind patch
kurrentdb: installed Database.apply_limit_to_sql bypass
kurrentdb: installed SQLScript.format bypass
kurrentdb: all patches installed and verified
```

If you see `kurrentdb: N patch(es) NOT installed`, something went wrong — check the surrounding logs for the exception.

## Configuration

Three environment variables tune behavior:

| Variable | Default | Purpose |
| --- | --- | --- |
| `KURRENTDB_TEST_QUERY` | `SELECT * FROM kdb.records LIMIT 1` | Superset's connection-test query. Override if your KurrentDB doesn't have the `kdb.records` table populated, or set to a query against a known-stable stream. |
| `KURRENTDB_MAX_ROWS` | `10000` | Maximum rows for any KurrentDB query without an explicit `LIMIT`. Set to `0` to disable the cap (queries stream until exhausted). |
| `GRPC_DEFAULT_SSL_ROOTS_FILE_PATH` | (system trust store) | Path to a CA PEM file for KurrentDB TLS verification. Required when KurrentDB uses a self-signed certificate. |

## Schema browser

The dialect reports a fixed static schema until KurrentDB Flight SQL implements its metadata commands. You'll see a single table `kdb.records` in Superset's schema picker, with the columns KurrentDB Flight SQL exposes for events: `log_position`, `commit_position`, `stream_revision`, `created_at`, `expires_at`, `stream`, `stream_hash`, `schema_name`, `category`, `deleted`, `schema_id`, `schema_format`, `record_id`, `data`, `metadata`.

For typed views over event streams, register virtual datasets in Superset — paste the SQL that projects the JSON fields you care about, give it a name, it becomes available in Explore. Example virtual dataset SQL:

```sql
SELECT
  stream,
  data::json->>'OrderId' as order_id,
  data::json->>'Amount' as amount,
  created_at
FROM kdb.records
WHERE category = 'orders'
```

## Known limitations

- **Schema is static.** The dialect's `get_table_names`, `get_columns`, etc. return hand-rolled metadata. If KurrentDB Flight SQL adds support for `CommandGetTables`, future versions can switch to live reflection.
- **No transactions.** Flight SQL has no transaction semantics. The dialect reports `AUTOCOMMIT`.
- **Server-side errors are opaque.** When KurrentDB's Flight SQL handler throws an unhandled exception, gRPC returns `Exception was thrown by handler.` with no detail. Check KurrentDB's own logs for the real stack trace.
- **Superset's `DEFAULT_SQLLAB_LIMIT` doesn't apply.** Superset's automatic LIMIT injection goes through sqlglot, which this package bypasses. Use `KURRENTDB_MAX_ROWS` instead.

## Caveat about `flightsql-dbapi`

The upstream [`influxdata/flightsql-dbapi`](https://github.com/influxdata/flightsql-dbapi) library was archived in March 2026. It still works and installs from PyPI, but won't receive further updates. A future major version of this package may switch to the [Apache Arrow ADBC](https://arrow.apache.org/adbc/) Flight SQL driver, which is maintained but doesn't currently ship its own SQLAlchemy dialect.

## Contributing

Issues and pull requests welcome. Please include the KurrentDB version you're running against — the Flight SQL implementation is moving, and what works on RC2 may not work on later builds.

## Releasing (maintainers)

Releases are driven by `scripts/release.sh`. Before running it:

1. Make sure all changes for the release are merged to `main`.
2. Ensure `CHANGELOG.md` has a `## [X.Y.Z] - Unreleased` section describing what's in the release.

Then from a clean checkout of `main`:

```sh
scripts/release.sh 0.2.1
```

The script will:

- Refuse to run if the working tree is dirty, you're not on `main`, or the tag already exists.
- Update `version` in `pyproject.toml` and `__version__` in `src/kurrent_sqlalchemy/__init__.py`.
- Replace `## [X.Y.Z] - Unreleased` in `CHANGELOG.md` with today's date.
- Show the diff and ask for confirmation.
- Commit, create an annotated `vX.Y.Z` tag, and push both to `origin`.

The tag push triggers `.github/workflows/publish.yml`, which builds the sdist + wheel, publishes to PyPI via trusted publishing, and creates the GitHub release using the matching CHANGELOG section as the release notes.

## License

Apache 2.0. See [LICENSE](LICENSE).
