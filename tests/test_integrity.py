"""Unit tests for the referential-integrity gate's matching logic.

Exercises check_integrity helpers on synthetic rows (no dependency on the CSVs
on disk) so the orphan detection itself is covered.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_integrity import RULES, _dim_keys, _fact_values  # noqa: E402


def test_fact_values_single_skips_empty_and_strips():
    rows = [{"SourceId": "10"}, {"SourceId": ""}, {"SourceId": " 12 "}, {}]
    assert _fact_values(rows, "SourceId", multi=False) == {"10", "12"}


def test_fact_values_multi_splits_pipes():
    rows = [{"Tags": "a|b"}, {"Tags": "b|c"}, {"Tags": ""}, {"Tags": "d| "}]
    assert _fact_values(rows, "Tags", multi=True) == {"a", "b", "c", "d"}


def test_dim_keys_strips_and_drops_blank():
    rows = [{"UserId": "1"}, {"UserId": " 2 "}, {"UserId": ""}]
    assert _dim_keys(rows, "UserId") == {"1", "2"}


def test_orphan_detected_when_fact_value_missing_from_dim():
    fact = _fact_values([{"StageId": "2"}, {"StageId": "99"}], "StageId", multi=False)
    dim = _dim_keys([{"StageId": "2"}], "StageId")
    assert fact - dim == {"99"}


def test_no_orphan_when_all_resolve():
    fact = _fact_values([{"PersonId": "5"}, {"PersonId": "6"}], "PersonId", multi=False)
    dim = _dim_keys([{"PersonId": "5"}, {"PersonId": "6"}, {"PersonId": "7"}], "PersonId")
    assert fact - dim == set()


@pytest.mark.parametrize("rule", RULES, ids=lambda r: f"{r.fact_col}->{r.dim_file}")
def test_rules_reference_known_files(rule):
    known = {
        "People.csv", "Deals.csv", "Events.csv",
        "Users.csv", "Pipelines.csv", "Stages.csv", "Sources.csv", "Tags.csv",
    }
    assert rule.fact_file in known
    assert rule.dim_file in known
