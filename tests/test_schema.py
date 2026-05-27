"""Schema/mapper sync tests. If these fail, the DDL won't match the CSVs."""
from __future__ import annotations

import pytest

from fub_api.mappers import (
    DEAL_COLUMNS,
    EVENT_COLUMNS,
    PEOPLE_COLUMNS,
    PIPELINE_COLUMNS,
    SOURCE_COLUMNS,
    STAGE_COLUMNS,
    TAG_COLUMNS,
    USER_COLUMNS,
    map_deal,
    map_event,
    map_person,
    map_pipeline,
    map_source,
    map_stage,
    map_tag,
    map_user,
)
from fub_api.schema import SCHEMAS, base_type, validate


def test_validate_passes():
    validate()  # raises on any column/type drift


def test_every_schema_table_present():
    assert set(SCHEMAS) == {
        "People", "Deals", "Events",
        "Users", "Pipelines", "Stages", "Sources", "Tags",
    }


@pytest.mark.parametrize("table,columns", [
    ("People", PEOPLE_COLUMNS),
    ("Deals", DEAL_COLUMNS),
    ("Events", EVENT_COLUMNS),
    ("Users", USER_COLUMNS),
    ("Pipelines", PIPELINE_COLUMNS),
    ("Stages", STAGE_COLUMNS),
    ("Sources", SOURCE_COLUMNS),
    ("Tags", TAG_COLUMNS),
])
def test_schema_columns_match_mapper(table, columns):
    sch_cols, types, pk = SCHEMAS[table]
    assert sch_cols == columns
    assert pk in columns
    assert all(c in types for c in columns)


@pytest.mark.parametrize("mapper,columns", [
    (map_person, PEOPLE_COLUMNS),
    (map_deal, DEAL_COLUMNS),
    (map_event, EVENT_COLUMNS),
    (map_user, USER_COLUMNS),
    (map_pipeline, PIPELINE_COLUMNS),
    (map_stage, STAGE_COLUMNS),
    (map_source, SOURCE_COLUMNS),
    (map_tag, TAG_COLUMNS),
])
def test_mapper_emits_exactly_declared_columns(mapper, columns):
    # Empty input still yields every column (missing values -> "").
    row = mapper({}, extracted_at="2026-05-27T00:00:00.000Z")
    assert set(row) == set(columns)
    assert row["SourceSystem"] == "FollowUpBoss"
    assert row["ExtractedAtUtc"] == "2026-05-27T00:00:00.000Z"


def test_base_type_strips_length():
    assert base_type("NVARCHAR(256)") == "NVARCHAR"
    assert base_type("DATETIME2(3)") == "DATETIME2"
    assert base_type("BIT") == "BIT"
