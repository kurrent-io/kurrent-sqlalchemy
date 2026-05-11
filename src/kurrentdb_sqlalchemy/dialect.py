"""SQLAlchemy dialect for KurrentDB's Arrow Flight SQL endpoint.

Wraps :class:`flightsql.sqlalchemy.FlightSQLDialect` with two changes:

1. **Crash-resistant probes.** KurrentDB Flight SQL returns ``FlightInfo``
   with empty ``endpoints`` for the metadata RPCs and rejects context-free
   queries like ``SELECT 1``. The upstream driver does
   ``info.endpoints[0].ticket`` without guards, so SQLAlchemy's normal
   connection-setup probes raise ``IndexError``. Every such probe is
   overridden to no-op or return safe defaults.

2. **Static schema reflection.** Until KurrentDB's Flight SQL implements
   the metadata commands, we expose the known event-log schema (one
   table, ``kdb.records``) so BI tools have something to populate the
   schema picker with. Override these methods in a subclass if your
   KurrentDB deployment exposes a different shape.
"""

from __future__ import annotations

from typing import Any

from flightsql.sqlalchemy import FlightSQLDialect
from sqlalchemy.types import (
    BigInteger,
    Boolean,
    LargeBinary,
    Text,
)


#: Schema name reported to BI tools. KurrentDB Flight SQL exposes its event
#: log under this prefix (e.g. ``SELECT * FROM kdb.records``).
KURRENTDB_SCHEMA = "kdb"

#: Table name within the schema.
KURRENTDB_TABLE = "records"

#: Static column definition for ``kdb.records``. Matches what KurrentDB
#: returns for a basic ``SELECT * FROM kdb.records LIMIT 1`` query as of
#: 26.1 RC2. Update if the server-side schema changes.
KURRENTDB_RECORDS_COLUMNS = [
    {"name": "log_position", "type": BigInteger(), "nullable": False, "default": None},
    {"name": "commit_position", "type": BigInteger(), "nullable": True, "default": None},
    {"name": "stream_revision", "type": BigInteger(), "nullable": False, "default": None},
    {"name": "created_at", "type": BigInteger(), "nullable": False, "default": None},
    {"name": "expires_at", "type": BigInteger(), "nullable": True, "default": None},
    {"name": "stream", "type": Text(), "nullable": False, "default": None},
    {"name": "stream_hash", "type": BigInteger(), "nullable": False, "default": None},
    {"name": "schema_name", "type": Text(), "nullable": False, "default": None},
    {"name": "category", "type": Text(), "nullable": False, "default": None},
    {"name": "deleted", "type": Boolean(), "nullable": False, "default": None},
    {"name": "schema_id", "type": Text(), "nullable": True, "default": None},
    {"name": "schema_format", "type": Text(), "nullable": True, "default": None},
    {"name": "record_id", "type": LargeBinary(), "nullable": False, "default": None},
    {"name": "data", "type": Text(), "nullable": True, "default": None},
    {"name": "metadata", "type": Text(), "nullable": True, "default": None},
]


class KurrentDBDialect(FlightSQLDialect):
    """SQLAlchemy dialect for KurrentDB Flight SQL."""

    name = "kurrentdb"

    # ---- Connection setup probes ----

    def initialize(self, connection: Any) -> None:
        # FlightSQLDialect.initialize calls flightsql_get_sql_info, which
        # crashes on KurrentDB's empty-endpoints CommandGetSqlInfo response.
        return

    def do_ping(self, dbapi_connection: Any) -> bool:
        # DefaultDialect.do_ping fires SELECT 1, which KurrentDB rejects.
        return True

    def _check_unicode_returns(self, connection: Any, additional_tests: Any = None) -> bool:
        return True

    def _get_default_schema_name(self, connection: Any) -> str:
        return KURRENTDB_SCHEMA

    def get_isolation_level(self, dbapi_connection: Any) -> str:
        return "AUTOCOMMIT"

    # ---- Static schema reflection ----
    #
    # KurrentDB Flight SQL doesn't implement GetCatalogs / GetDbSchemas /
    # GetTables / GetColumns yet — they return empty endpoints, which the
    # upstream driver crashes on. We return a hand-rolled schema so BI
    # tools have something usable until the server side catches up.

    def has_table(
        self,
        connection: Any,
        table_name: str,
        schema: str | None = None,
        **kw: Any,
    ) -> bool:
        return table_name == KURRENTDB_TABLE and (
            schema is None or schema == KURRENTDB_SCHEMA
        )

    def get_schema_names(self, connection: Any, **kw: Any) -> list[str]:
        return [KURRENTDB_SCHEMA]

    def get_table_names(
        self, connection: Any, schema: str | None = None, **kw: Any
    ) -> list[str]:
        if schema in (None, KURRENTDB_SCHEMA):
            return [KURRENTDB_TABLE]
        return []

    def get_view_names(
        self, connection: Any, schema: str | None = None, **kw: Any
    ) -> list[str]:
        return []

    def get_columns(
        self,
        connection: Any,
        table_name: str,
        schema: str | None = None,
        **kw: Any,
    ) -> list[dict[str, Any]]:
        if table_name == KURRENTDB_TABLE and schema in (None, KURRENTDB_SCHEMA):
            return list(KURRENTDB_RECORDS_COLUMNS)
        return []

    def get_pk_constraint(
        self,
        connection: Any,
        table_name: str,
        schema: str | None = None,
        **kw: Any,
    ) -> dict[str, Any]:
        return {"constrained_columns": [], "name": None}

    def get_foreign_keys(
        self,
        connection: Any,
        table_name: str,
        schema: str | None = None,
        **kw: Any,
    ) -> list[dict[str, Any]]:
        return []

    def get_indexes(
        self,
        connection: Any,
        table_name: str,
        schema: str | None = None,
        **kw: Any,
    ) -> list[dict[str, Any]]:
        return []
