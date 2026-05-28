"""Unit tests for load_to_sql conversion logic (no DB / no pyodbc connection).

Verifies CSV-text -> SQL-bind-value conversion and the NVARCHAR(MAX) input-size
detection, both driven by fub_api.schema types.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from load_to_sql import _convert, _input_sizes  # noqa: E402
from fub_api.schema import SCHEMAS  # noqa: E402


def test_empty_string_is_null_for_every_type():
    for t in ("INT", "BIGINT", "BIT", "DATE", "DATETIME2(3)", "NVARCHAR(256)", "VARCHAR(64)"):
        assert _convert("", t) is None


def test_datetime_strips_z_and_t():
    assert _convert("2026-05-27T18:03:29.000Z", "DATETIME2(3)") == "2026-05-27 18:03:29.000"


def test_date_takes_first_ten_chars():
    assert _convert("2026-05-27", "DATE") == "2026-05-27"
    assert _convert("2026-05-27T00:00:00Z", "DATE") == "2026-05-27"


def test_bit_maps_one_zero_else_null():
    assert _convert("1", "BIT") == 1
    assert _convert("0", "BIT") == 0
    assert _convert("true", "BIT") is None


def test_int_parses_or_nulls():
    assert _convert("42", "INT") == 42
    assert _convert("9999999999", "BIGINT") == 9999999999
    assert _convert("not-a-number", "INT") is None


def test_decimal_parses_or_nulls():
    assert _convert("3.14", "DECIMAL(10,2)") == 3.14
    assert _convert("bad", "FLOAT") is None


def test_text_passthrough():
    assert _convert("🦀 maryland", "NVARCHAR(256)") == "🦀 maryland"
    assert _convert("fka_xxx", "VARCHAR(64)") == "fka_xxx"


def test_input_sizes_flags_only_max_columns():
    # People has a RawJson NVARCHAR(MAX) column -> override present at that index.
    cols, types, _ = SCHEMAS["People"]
    sizes = _input_sizes(cols, types)
    assert sizes is not None
    raw_idx = cols.index("RawJson")
    assert sizes[raw_idx] is not None
    assert sizes[cols.index("PersonId")] is None


def test_input_sizes_none_when_no_max_column():
    # Tags has no NVARCHAR(MAX) column -> no override needed.
    cols, types, _ = SCHEMAS["Tags"]
    assert _input_sizes(cols, types) is None
