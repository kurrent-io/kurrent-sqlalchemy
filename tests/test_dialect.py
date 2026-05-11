"""Smoke tests for kurrentdb-sqlalchemy.

These tests cover behavior that doesn't require a running KurrentDB —
imports, override attachment, schema reflection shape, helpers, and
SQLAlchemy entry-point discovery.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest


# ---- Dialect import + structure ----


def test_dialect_importable():
    from kurrentdb_sqlalchemy import KurrentDBDialect
    assert KurrentDBDialect.name == "kurrentdb"


def test_overrides_attached_to_class():
    """Every override must be on KurrentDBDialect, not inherited.
    Inherited methods would fall back to FlightSQLDialect which crashes
    on KurrentDB's empty-endpoints metadata responses."""
    from kurrentdb_sqlalchemy import KurrentDBDialect

    must_override = [
        "initialize",
        "do_ping",
        "_check_unicode_returns",
        "_get_default_schema_name",
        "get_isolation_level",
        "has_table",
        "get_schema_names",
        "get_table_names",
        "get_view_names",
        "get_columns",
        "get_pk_constraint",
        "get_foreign_keys",
        "get_indexes",
    ]
    for name in must_override:
        method = getattr(KurrentDBDialect, name)
        qual = method.__qualname__
        assert qual.startswith("KurrentDBDialect."), (
            f"{name} not overridden on KurrentDBDialect (qualname={qual})"
        )


# ---- Probe methods don't crash ----


def test_do_ping_returns_true():
    from kurrentdb_sqlalchemy import KurrentDBDialect
    assert KurrentDBDialect().do_ping(object()) is True


def test_initialize_is_noop():
    from kurrentdb_sqlalchemy import KurrentDBDialect
    assert KurrentDBDialect().initialize(object()) is None


# ---- Static schema reflection ----


def test_get_schema_names():
    from kurrentdb_sqlalchemy import KurrentDBDialect
    assert KurrentDBDialect().get_schema_names(object()) == ["kdb"]


def test_get_table_names_default_schema():
    from kurrentdb_sqlalchemy import KurrentDBDialect
    assert KurrentDBDialect().get_table_names(object()) == ["records"]


def test_get_table_names_with_kdb_schema():
    from kurrentdb_sqlalchemy import KurrentDBDialect
    assert KurrentDBDialect().get_table_names(object(), schema="kdb") == ["records"]


def test_get_table_names_unknown_schema():
    from kurrentdb_sqlalchemy import KurrentDBDialect
    assert KurrentDBDialect().get_table_names(object(), schema="other") == []


def test_get_columns_records():
    from kurrentdb_sqlalchemy import KurrentDBDialect
    cols = KurrentDBDialect().get_columns(object(), "records")
    names = [c["name"] for c in cols]
    # spot check a representative subset
    for expected in ("log_position", "stream", "category", "data", "metadata"):
        assert expected in names, f"{expected} missing from get_columns"
    # every column dict must have the SQLAlchemy reflection contract
    for col in cols:
        assert set(col.keys()) >= {"name", "type", "nullable", "default"}


def test_get_columns_unknown_table():
    from kurrentdb_sqlalchemy import KurrentDBDialect
    assert KurrentDBDialect().get_columns(object(), "other") == []


def test_has_table():
    from kurrentdb_sqlalchemy import KurrentDBDialect
    d = KurrentDBDialect()
    assert d.has_table(object(), "records") is True
    assert d.has_table(object(), "records", schema="kdb") is True
    assert d.has_table(object(), "records", schema="other") is False
    assert d.has_table(object(), "nonexistent") is False


# ---- Internal helpers ----


def test_append_limit_no_existing():
    from kurrentdb_sqlalchemy._internal import append_limit
    assert append_limit("SELECT * FROM t", 100) == "SELECT * FROM t\nLIMIT 100"


def test_append_limit_replaces_when_smaller():
    from kurrentdb_sqlalchemy._internal import append_limit
    result = append_limit("SELECT * FROM t LIMIT 1000", 50)
    assert result.endswith("LIMIT 50")
    assert "LIMIT 1000" not in result


def test_append_limit_preserves_when_larger():
    from kurrentdb_sqlalchemy._internal import append_limit
    # User asked for 10, system cap is 1000 — keep user's choice
    assert append_limit("SELECT * FROM t LIMIT 10", 1000) == "SELECT * FROM t LIMIT 10"


def test_append_limit_force_replaces():
    from kurrentdb_sqlalchemy._internal import append_limit
    # Use distinct digit counts so "LIMIT 5" can't be a substring of "LIMIT 1000"
    result = append_limit("SELECT * FROM t LIMIT 5", 1000, force=True)
    assert result.endswith("LIMIT 1000")
    assert "LIMIT 5" not in result


def test_append_limit_strips_trailing_semicolon():
    from kurrentdb_sqlalchemy._internal import append_limit
    assert append_limit("SELECT * FROM t;", 10) == "SELECT * FROM t\nLIMIT 10"


def test_has_trailing_limit():
    from kurrentdb_sqlalchemy._internal import has_trailing_limit
    assert has_trailing_limit("SELECT * FROM t LIMIT 10") is True
    assert has_trailing_limit("SELECT * FROM t LIMIT 10;") is True
    assert has_trailing_limit("SELECT * FROM t") is False
    assert has_trailing_limit("SELECT 'LIMIT 10' FROM t") is False  # not trailing


def test_maybe_inject_max_rows_cap_default():
    from kurrentdb_sqlalchemy._internal import maybe_inject_max_rows_cap
    # Default cap is 10000
    result = maybe_inject_max_rows_cap("SELECT * FROM t")
    assert result.endswith("LIMIT 10000")


def test_maybe_inject_max_rows_cap_preserves_user_limit():
    from kurrentdb_sqlalchemy._internal import maybe_inject_max_rows_cap
    assert maybe_inject_max_rows_cap("SELECT * FROM t LIMIT 5") == "SELECT * FROM t LIMIT 5"


def test_maybe_inject_max_rows_cap_disabled(monkeypatch):
    monkeypatch.setenv("KURRENTDB_MAX_ROWS", "0")
    from kurrentdb_sqlalchemy._internal import maybe_inject_max_rows_cap
    assert maybe_inject_max_rows_cap("SELECT * FROM t") == "SELECT * FROM t"


def test_maybe_inject_max_rows_cap_custom(monkeypatch):
    monkeypatch.setenv("KURRENTDB_MAX_ROWS", "500")
    from kurrentdb_sqlalchemy._internal import maybe_inject_max_rows_cap
    result = maybe_inject_max_rows_cap("SELECT * FROM t")
    assert result.endswith("LIMIT 500")


def test_maybe_inject_max_rows_cap_invalid_value(monkeypatch):
    """Bogus env value falls back to default rather than crashing."""
    monkeypatch.setenv("KURRENTDB_MAX_ROWS", "not-a-number")
    from kurrentdb_sqlalchemy._internal import maybe_inject_max_rows_cap
    result = maybe_inject_max_rows_cap("SELECT * FROM t")
    assert result.endswith("LIMIT 10000")


# ---- SQLAlchemy entry-point discovery ----


def test_entrypoint_registered():
    """The dialect should resolve via SQLAlchemy's registry without
    explicit import — that's how `kurrentdb+flightsql://` URIs work."""
    from sqlalchemy.dialects import registry
    cls = registry.load("kurrentdb.flightsql")
    assert cls.__name__ == "KurrentDBDialect"
