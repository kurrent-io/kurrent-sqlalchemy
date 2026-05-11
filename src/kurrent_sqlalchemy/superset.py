"""Apache Superset integration for KurrentDB Flight SQL.

Importing this module requires Apache Superset to be installed.

Wire it up in ``superset_config.py``::

    from kurrent_sqlalchemy.superset import (
        KurrentDBEngineSpec,
        install_superset_patches,
    )

    DB_ENGINE_SPEC_OVERRIDES = {"kurrentdb": KurrentDBEngineSpec}
    FLASK_APP_MUTATOR = install_superset_patches

The three patches that ``install_superset_patches`` applies are not
optional — without them Superset will:

* Resolve KurrentDB connections to ``BaseEngineSpec`` rather than to
  ``KurrentDBEngineSpec``, because ``DB_ENGINE_SPEC_OVERRIDES`` only
  replaces existing engine entries and KurrentDB isn't a built-in one.
* Round-trip every outgoing SQL statement through sqlglot's parse/render
  cycle, which rewrites PostgreSQL JSON operators (``data::json->>'x'``)
  into Trino-style ``JSON_EXTRACT_SCALAR`` calls KurrentDB cannot execute.
* Call ``apply_limit_to_sql`` from older code paths that go through the
  ``Database`` model rather than the ``SQLScript`` pipeline.

All three are applied for KurrentDB connections only; other engines pass
through to Superset's original code.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

try:
    from superset.db_engine_specs.base import BaseEngineSpec
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "kurrent_sqlalchemy.superset requires Apache Superset to be "
        "installed. Install with `pip install kurrent-sqlalchemy[superset]`."
    ) from exc

from kurrent_sqlalchemy._internal import (
    DEFAULT_TEST_QUERY,
    ENV_TEST_QUERY,
    KURRENTDB_ENGINE_NAME,
    _TRAILING_LIMIT_RE,
    append_limit,
    maybe_inject_max_rows_cap,
)

import os
import re

logger = logging.getLogger(__name__)


# ===========================================================================
# Engine spec
# ===========================================================================


class KurrentDBEngineSpec(BaseEngineSpec):
    """Superset engine spec for KurrentDB Flight SQL."""

    engine = KURRENTDB_ENGINE_NAME
    engine_name = "KurrentDB Flight SQL"
    default_driver = "flightsql"

    @classmethod
    def get_test_query(cls) -> Optional[str]:
        return os.environ.get(ENV_TEST_QUERY, DEFAULT_TEST_QUERY)

    @classmethod
    def epoch_to_dttm(cls) -> str:
        # Flight SQL servers vary widely in datetime functions; let SQL pass
        # through unchanged. Subclass and override per deployment if needed.
        return "{col}"

    @classmethod
    def apply_limit_to_sql(
        cls, sql: str, limit: int, database: Any = None, force: bool = False
    ) -> str:
        return append_limit(sql, limit, force)

    @classmethod
    def set_or_update_query_limit(cls, sql: str, limit: int) -> str:
        return append_limit(sql, limit, force=True)

    @classmethod
    def get_limit_from_sql(cls, sql: str) -> Optional[int]:
        match = _TRAILING_LIMIT_RE.search(sql.rstrip().rstrip(";").rstrip())
        return int(re.search(r"\d+", match.group(0)).group(0)) if match else None


# ===========================================================================
# Patches
# ===========================================================================


def _install_db_engine_spec_patch() -> None:
    """Bind KurrentDBEngineSpec to KurrentDB connections.

    ``DB_ENGINE_SPEC_OVERRIDES`` only replaces existing spec entries in
    this Superset version. KurrentDB isn't built-in, so our override is
    silently dropped and connections fall back to BaseEngineSpec. Wrap
    ``Database.db_engine_spec`` directly so KurrentDB backends resolve to
    our class regardless of what the registry holds.
    """
    from superset.models.core import Database

    existing = Database.__dict__.get("db_engine_spec")
    if not isinstance(existing, property):
        logger.warning(
            "Database.db_engine_spec is not a property; skipping bind patch"
        )
        return

    if getattr(existing.fget, "_kurrentdb_patched", False):
        return

    original_fget = existing.fget

    def patched(self: Any) -> Any:
        try:
            result = original_fget(self)
        except Exception:  # noqa: BLE001 — be defensive
            result = None
        backend = getattr(self, "backend", None)
        if backend == KURRENTDB_ENGINE_NAME and (
            result is None
            or result is BaseEngineSpec
            or getattr(result, "engine", None) in ("", "base")
        ):
            return KurrentDBEngineSpec
        return result

    patched._kurrentdb_patched = True  # type: ignore[attr-defined]
    Database.db_engine_spec = property(patched)
    logger.info("kurrentdb: installed Database.db_engine_spec bind patch")


def _install_database_apply_limit_patch() -> None:
    """Bypass sqlglot for older code paths that go through Database."""
    from superset.models.core import Database

    if getattr(Database.apply_limit_to_sql, "_kurrentdb_patched", False):
        return

    original = Database.apply_limit_to_sql

    def apply_limit_to_sql(
        self: Any, sql: str, limit: int = 1000, force: bool = False
    ) -> str:
        engine = getattr(self.db_engine_spec, "engine", None)
        if engine == KURRENTDB_ENGINE_NAME:
            logger.debug("kurrentdb: Database.apply_limit_to_sql bypass (limit=%d)", limit)
            return append_limit(sql, limit, force)
        return original(self, sql, limit, force)

    apply_limit_to_sql._kurrentdb_patched = True  # type: ignore[attr-defined]
    Database.apply_limit_to_sql = apply_limit_to_sql
    logger.info("kurrentdb: installed Database.apply_limit_to_sql bypass")


def _install_sqlscript_patch() -> None:
    """Bypass sqlglot for SQL Lab's main code path.

    Superset's sql_lab.py builds its own pipeline directly via
    ``SQLScript(sql, engine=...)`` → ``statement.set_limit_value(...)`` →
    ``script.format()`` — none of which touches ``Database.apply_limit_to_sql``.
    Patching ``SQLScript.format`` catches every caller in one shot.

    The bypass also injects a default LIMIT cap from
    ``KURRENTDB_MAX_ROWS`` when the user's SQL has none.
    """
    from superset.sql.parse import SQLScript

    if getattr(SQLScript.format, "_kurrentdb_patched", False):
        return

    original_init = SQLScript.__init__
    original_format = SQLScript.format

    def patched_init(self: Any, *args: Any, **kwargs: Any) -> None:
        sql = args[0] if args else kwargs.get("sql_statements") or kwargs.get("sql")
        engine = (
            args[1]
            if len(args) > 1
            else (kwargs.get("engine") or kwargs.get("dialect"))
        )
        self._kurrentdb_original_sql = sql
        self._kurrentdb_engine = engine
        original_init(self, *args, **kwargs)

    def patched_format(self: Any, comments: bool = True) -> str:
        engine = getattr(self, "_kurrentdb_engine", None)
        if engine == KURRENTDB_ENGINE_NAME:
            logger.debug("kurrentdb: SQLScript.format bypass")
            sql = getattr(self, "_kurrentdb_original_sql", None)
            if sql is None:
                # Fall back to sqlglot if we somehow lost the original; better
                # to ship rewritten SQL than to break with a None.
                return original_format(self, comments=comments)
            return maybe_inject_max_rows_cap(sql)
        return original_format(self, comments=comments)

    patched_format._kurrentdb_patched = True  # type: ignore[attr-defined]
    SQLScript.__init__ = patched_init
    SQLScript.format = patched_format
    logger.info("kurrentdb: installed SQLScript.format bypass")


def _self_test() -> bool:
    """Verify all three patches are attached. Returns True on success."""
    from superset.models.core import Database
    from superset.sql.parse import SQLScript

    checks = {
        "db_engine_spec bind": getattr(
            Database.__dict__.get("db_engine_spec", property()).fget,
            "_kurrentdb_patched",
            False,
        ),
        "Database.apply_limit_to_sql bypass": getattr(
            Database.apply_limit_to_sql, "_kurrentdb_patched", False
        ),
        "SQLScript.format bypass": getattr(
            SQLScript.format, "_kurrentdb_patched", False
        ),
    }
    failures = [name for name, ok in checks.items() if not ok]
    if failures:
        logger.error(
            "kurrentdb: %d patch(es) NOT installed: %s. "
            "JSON operators may be rewritten and/or KurrentDB databases may "
            "resolve to BaseEngineSpec. Check earlier error logs for details.",
            len(failures),
            ", ".join(failures),
        )
        return False
    logger.info("kurrentdb: all patches installed and verified")
    return True


def install_superset_patches(app: Any) -> None:
    """FLASK_APP_MUTATOR-compatible hook.

    Installs all three Superset integration patches and runs a self-test.
    Safe to chain with other mutators::

        def my_mutator(app):
            install_superset_patches(app)
            ... other setup ...

        FLASK_APP_MUTATOR = my_mutator
    """
    # Order matters: bind the spec FIRST so subsequent code sees KurrentDB
    # connections as KurrentDB-engine'd, not 'base'.
    for installer in (
        _install_db_engine_spec_patch,
        _install_database_apply_limit_patch,
        _install_sqlscript_patch,
    ):
        try:
            installer()
        except Exception:
            logger.exception("kurrentdb: %s failed", installer.__name__)

    _self_test()


__all__ = ["KurrentDBEngineSpec", "install_superset_patches"]
