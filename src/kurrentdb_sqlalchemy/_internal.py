"""Internal helpers shared by the dialect and Superset integration."""

from __future__ import annotations

import os
import re

KURRENTDB_ENGINE_NAME = "kurrentdb"

# Environment variables
ENV_MAX_ROWS = "KURRENTDB_MAX_ROWS"
ENV_TEST_QUERY = "KURRENTDB_TEST_QUERY"

# 10k rows is a reasonable default safety cap on otherwise-unbounded SELECTs.
# Set ``KURRENTDB_MAX_ROWS=0`` to disable, or to any positive int to override.
DEFAULT_MAX_ROWS = 10000

DEFAULT_TEST_QUERY = "SELECT * FROM kdb.records LIMIT 1"

_TRAILING_LIMIT_RE = re.compile(r"\s+LIMIT\s+\d+\s*;?\s*$", re.IGNORECASE)


def has_trailing_limit(sql: str) -> bool:
    """True if the SQL already ends in a LIMIT N clause."""
    return bool(_TRAILING_LIMIT_RE.search(sql.rstrip().rstrip(";").rstrip()))


def append_limit(sql: str, limit: int, force: bool = False) -> str:
    """Plain-text LIMIT append/replace. Never touches sqlglot.

    If ``force`` is True or the existing LIMIT is larger than ``limit``, the
    existing LIMIT is replaced. Otherwise the input is returned unchanged.
    """
    stripped = sql.rstrip().rstrip(";").rstrip()
    match = _TRAILING_LIMIT_RE.search(stripped)
    if match:
        existing = int(re.search(r"\d+", match.group(0)).group(0))
        if not force and limit >= existing:
            return stripped
        stripped = _TRAILING_LIMIT_RE.sub("", stripped)
    return f"{stripped}\nLIMIT {limit}"


def maybe_inject_max_rows_cap(sql: str) -> str:
    """Inject a default LIMIT cap on KurrentDB queries that don't have one.

    KurrentDB Flight SQL has no built-in result-size guard. Without this, a
    bare ``SELECT * FROM kdb.records`` against a large cluster will stream
    until something OOMs on the BI tool side. Cap can be tuned or disabled
    via ``KURRENTDB_MAX_ROWS`` env var.
    """
    try:
        cap = int(os.environ.get(ENV_MAX_ROWS, str(DEFAULT_MAX_ROWS)))
    except ValueError:
        cap = DEFAULT_MAX_ROWS
    if cap <= 0:
        return sql  # explicit disable
    if has_trailing_limit(sql):
        return sql  # user supplied their own
    return append_limit(sql, cap, force=False)
