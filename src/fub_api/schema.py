"""SQL Server type overlay for the CSV column lists.

The mapper `*_COLUMNS` lists in `mappers.py` are the single source of truth for
*which* columns exist and their order. This module pins a SQL Server type to
each one. `validate()` asserts the two stay in sync, so adding a column to a
mapper without typing it here is a hard error (caught by tests / generate_ddl).

Type conventions (DATA_RULES §2):
    Identifier   -> VARCHAR(64)
    String       -> NVARCHAR(n)   (n = mapper max_len)
    Big text/JSON-> NVARCHAR(MAX)
    Integer      -> INT / BIGINT
    Boolean      -> BIT
    Timestamp    -> DATETIME2(3)
    Date         -> DATE
Custom "number" fields are kept as NVARCHAR (extracted as raw text) so the
backend can cast them — see mappers._map_custom_fields.
"""
from __future__ import annotations

from fub_api.mappers import (
    CUSTOM_FIELD_TYPES,
    DEAL_COLUMNS,
    EVENT_COLUMNS,
    PEOPLE_COLUMNS,
    PIPELINE_COLUMNS,
    SOURCE_COLUMNS,
    STAGE_COLUMNS,
    TAG_COLUMNS,
    USER_COLUMNS,
    _custom_column,
)

_AUDIT_TYPES = {
    "SourceSystem": "VARCHAR(32)",
    "SourceSystemId": "VARCHAR(64)",
    "ExtractedAtUtc": "DATETIME2(3)",
    "RawJson": "NVARCHAR(MAX)",
}

PEOPLE_TYPES: dict[str, str] = {
    "PersonId": "VARCHAR(64)",
    "Name": "NVARCHAR(256)",
    "FirstName": "NVARCHAR(128)",
    "LastName": "NVARCHAR(128)",
    "Stage": "NVARCHAR(128)",
    "StageId": "INT",
    "Type": "NVARCHAR(64)",
    "Source": "NVARCHAR(128)",
    "SourceId": "INT",
    "LeadFlowId": "INT",
    "AssignedUserId": "INT",
    "AssignedTo": "NVARCHAR(128)",
    "AssignedLenderId": "INT",
    "AssignedLenderName": "NVARCHAR(128)",
    "AssignedPondId": "INT",
    "PrimaryEmail": "NVARCHAR(256)",
    "PrimaryPhone": "VARCHAR(32)",
    "Emails": "NVARCHAR(1024)",
    "Phones": "NVARCHAR(512)",
    "Tags": "NVARCHAR(2048)",
    "AddressStreet": "NVARCHAR(256)",
    "AddressCity": "NVARCHAR(128)",
    "AddressState": "NVARCHAR(64)",
    "AddressCode": "NVARCHAR(32)",
    "Price": "BIGINT",
    "IsDelayed": "BIT",
    "ContactedCount": "INT",
    "IsClaimed": "BIT",
    "WebsiteVisits": "INT",
    "DealStatus": "NVARCHAR(64)",
    "DealStage": "NVARCHAR(128)",
    "DealName": "NVARCHAR(256)",
    "DealCloseDate": "DATE",
    "DealPrice": "BIGINT",
    "CreatedVia": "NVARCHAR(64)",
    "CreatedUtc": "DATETIME2(3)",
    "UpdatedUtc": "DATETIME2(3)",
    "LastActivityUtc": "DATETIME2(3)",
    **_AUDIT_TYPES,
}
# Custom field columns: date-typed -> DATE, everything else -> NVARCHAR(512).
for _api_name, _ftype in CUSTOM_FIELD_TYPES.items():
    PEOPLE_TYPES[_custom_column(_api_name)] = "DATE" if _ftype == "date" else "NVARCHAR(512)"

DEAL_TYPES: dict[str, str] = {
    "DealId": "VARCHAR(64)",
    "Name": "NVARCHAR(512)",
    "DealType": "INT",
    "Status": "NVARCHAR(64)",
    "Price": "BIGINT",
    "OrderWeight": "INT",
    "Description": "NVARCHAR(4000)",
    "PipelineId": "INT",
    "PipelineName": "NVARCHAR(256)",
    "StageId": "INT",
    "StageName": "NVARCHAR(256)",
    "EnteredStageUtc": "DATETIME2(3)",
    "CommissionValue": "BIGINT",
    "AgentCommission": "BIGINT",
    "TeamCommission": "BIGINT",
    "TimeToClose": "INT",
    "ProjectedCloseDate": "DATE",
    "EarnestMoneyDueDate": "DATE",
    "MutualAcceptanceDate": "DATE",
    "DueDiligenceDate": "DATE",
    "FinalWalkThroughDate": "DATE",
    "PossessionDate": "DATE",
    "CustomClosingDate": "DATE",
    "PrimaryPersonId": "VARCHAR(64)",
    "PersonIds": "NVARCHAR(512)",
    "PersonNames": "NVARCHAR(1024)",
    "PrimaryUserId": "VARCHAR(64)",
    "UserIds": "NVARCHAR(256)",
    "UserNames": "NVARCHAR(512)",
    "CreatedUtc": "DATETIME2(3)",
    **_AUDIT_TYPES,
}

EVENT_TYPES: dict[str, str] = {
    "EventId": "VARCHAR(64)",
    "PersonId": "VARCHAR(64)",
    "Type": "NVARCHAR(128)",
    "Source": "NVARCHAR(128)",
    "Message": "NVARCHAR(4000)",
    "Description": "NVARCHAR(4000)",
    "NoteId": "VARCHAR(64)",
    "PageTitle": "NVARCHAR(512)",
    "PageUrl": "NVARCHAR(1024)",
    "PageDuration": "INT",
    "Property": "NVARCHAR(4000)",
    "PropertySearch": "NVARCHAR(4000)",
    "Additional": "NVARCHAR(4000)",
    "OccurredUtc": "DATETIME2(3)",
    "CreatedUtc": "DATETIME2(3)",
    "UpdatedUtc": "DATETIME2(3)",
    **_AUDIT_TYPES,
}


USER_TYPES: dict[str, str] = {
    "UserId": "VARCHAR(64)",
    "Name": "NVARCHAR(256)",
    "FirstName": "NVARCHAR(128)",
    "LastName": "NVARCHAR(128)",
    "Email": "NVARCHAR(256)",
    "Phone": "VARCHAR(32)",
    "Role": "NVARCHAR(64)",
    "Status": "NVARCHAR(64)",
    "Timezone": "NVARCHAR(64)",
    "IsOwner": "BIT",
    "PauseLeadDistribution": "BIT",
    "CanExport": "BIT",
    "CanCreateApiKeys": "BIT",
    "Fuid": "VARCHAR(64)",
    "LeadEmailAddress": "NVARCHAR(256)",
    "PictureUrl": "NVARCHAR(1024)",
    "GroupIds": "NVARCHAR(256)",
    "GroupNames": "NVARCHAR(1024)",
    "LastSeenIosUtc": "DATETIME2(3)",
    "LastSeenAndroidUtc": "DATETIME2(3)",
    "LastSeenFub2Utc": "DATETIME2(3)",
    "CreatedUtc": "DATETIME2(3)",
    "UpdatedUtc": "DATETIME2(3)",
    **_AUDIT_TYPES,
}

PIPELINE_TYPES: dict[str, str] = {
    "PipelineId": "VARCHAR(64)",
    "Name": "NVARCHAR(256)",
    "Description": "NVARCHAR(1024)",
    "OrderWeight": "INT",
    "StageCount": "INT",
    "StageIds": "NVARCHAR(512)",
    **_AUDIT_TYPES,
}

STAGE_TYPES: dict[str, str] = {
    "StageId": "VARCHAR(64)",
    "Name": "NVARCHAR(256)",
    "PipelineId": "INT",
    "StageKind": "VARCHAR(16)",
    "OrderWeight": "INT",
    "IsProtected": "BIT",
    "PeopleCount": "INT",
    "Color": "VARCHAR(32)",
    "ClosedStage": "BIT",
    "Description": "NVARCHAR(1024)",
    **_AUDIT_TYPES,
}

# Derived dimensions (from People.csv) — no RawJson; add the Derived flag.
SOURCE_TYPES: dict[str, str] = {
    "SourceId": "INT",
    "Name": "NVARCHAR(128)",
    "PeopleCount": "INT",
    "Derived": "BIT",
    "SourceSystem": "VARCHAR(32)",
    "SourceSystemId": "VARCHAR(64)",
    "ExtractedAtUtc": "DATETIME2(3)",
}

TAG_TYPES: dict[str, str] = {
    "TagName": "NVARCHAR(256)",
    "PeopleCount": "INT",
    "Derived": "BIT",
    "SourceSystem": "VARCHAR(32)",
    "SourceSystemId": "NVARCHAR(256)",
    "ExtractedAtUtc": "DATETIME2(3)",
}


# entity table name -> (ordered columns, type map, primary key column)
SCHEMAS: dict[str, tuple[list[str], dict[str, str], str]] = {
    "People": (PEOPLE_COLUMNS, PEOPLE_TYPES, "PersonId"),
    "Deals": (DEAL_COLUMNS, DEAL_TYPES, "DealId"),
    "Events": (EVENT_COLUMNS, EVENT_TYPES, "EventId"),
    "Users": (USER_COLUMNS, USER_TYPES, "UserId"),
    "Pipelines": (PIPELINE_COLUMNS, PIPELINE_TYPES, "PipelineId"),
    "Stages": (STAGE_COLUMNS, STAGE_TYPES, "StageId"),
    "Sources": (SOURCE_COLUMNS, SOURCE_TYPES, "SourceId"),
    "Tags": (TAG_COLUMNS, TAG_TYPES, "TagName"),
}


def validate() -> None:
    """Raise if any mapper column lacks a type or vice versa."""
    for table, (columns, types, pk) in SCHEMAS.items():
        missing = [c for c in columns if c not in types]
        extra = [c for c in types if c not in columns]
        if missing:
            raise ValueError(f"{table}: columns missing a SQL type: {missing}")
        if extra:
            raise ValueError(f"{table}: typed columns not in mapper: {extra}")
        if pk not in columns:
            raise ValueError(f"{table}: PK {pk} not in columns")


def base_type(sql_type: str) -> str:
    """Strip the length/precision: 'NVARCHAR(256)' -> 'NVARCHAR'."""
    return sql_type.split("(", 1)[0].strip().upper()
