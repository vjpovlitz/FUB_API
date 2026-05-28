"""Unit tests for the fub_mcp guardrails + formatting (no DB required)."""
from __future__ import annotations

import pytest

from fub_mcp.db import to_markdown, validate_select
from fub_mcp.tools.base import check_choice, check_date


# --- validate_select: allow reads ---
@pytest.mark.parametrize("sql", [
    "SELECT TOP 5 * FROM fub.People",
    "  select PersonId from fub.People  ",
    "WITH x AS (SELECT 1 AS n) SELECT n FROM x",
    "SELECT TOP 1 * FROM fub.People;",  # trailing semicolon is stripped
])
def test_validate_select_allows_reads(sql):
    cleaned = validate_select(sql)
    assert cleaned.lower().startswith(("select", "with"))
    assert ";" not in cleaned


# --- validate_select: reject everything else ---
@pytest.mark.parametrize("sql", [
    "DELETE FROM fub.People",
    "UPDATE fub.Tags SET TagName='x'",
    "INSERT INTO fub.People (PersonId) VALUES ('1')",
    "DROP TABLE fub.People",
    "ALTER TABLE fub.People ADD x int",
    "TRUNCATE TABLE fub.Events",
    "MERGE fub.People AS t USING fub.People AS s ON 1=1",
    "SELECT * INTO fub.Copy FROM fub.People",   # INTO writes a table
    "WAITFOR DELAY '00:00:05'",                  # DoS
    "EXEC sp_who",
    "SELECT 1; DROP TABLE fub.People",           # multiple statements
])
def test_validate_select_rejects_writes(sql):
    with pytest.raises(ValueError):
        validate_select(sql)


def test_validate_select_rejects_empty():
    with pytest.raises(ValueError):
        validate_select("   ")


# --- check_choice (identifier whitelist) ---
def test_check_choice_ok():
    assert check_choice("LeadsAssigned", ("LeadsAssigned", "DealsClosed"), "order_by") == "LeadsAssigned"


def test_check_choice_rejects_injection():
    with pytest.raises(ValueError):
        check_choice("LeadsAssigned; DROP TABLE x", ("LeadsAssigned",), "order_by")


# --- check_date ---
def test_check_date_ok():
    assert check_date("2026-05-28", "since") == "2026-05-28"


@pytest.mark.parametrize("bad", ["2026-13-01", "yesterday", "05/28/2026", ""])
def test_check_date_rejects_bad(bad):
    with pytest.raises(ValueError):
        check_date(bad, "since")


# --- to_markdown ---
def test_to_markdown_table():
    out = to_markdown(["A", "B"], [[1, "x"], [2, "y"]], truncated=False, cap=200)
    assert out.startswith("| A | B |")
    assert "_2 row(s)._" in out


def test_to_markdown_truncation_note():
    out = to_markdown(["A"], [[1]], truncated=True, cap=1)
    assert "truncated" in out


def test_to_markdown_empty():
    assert "No rows matched." in to_markdown(["A"], [], truncated=False, cap=10)


def test_to_markdown_escapes_pipes():
    out = to_markdown(["A"], [["a|b"]], truncated=False, cap=10)
    assert "a\\|b" in out
