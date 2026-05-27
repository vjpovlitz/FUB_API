"""FUB API row -> SQL-Server-shaped CSV row.

Every value passes through a `fub_api.sanitize.*` helper. Column lists are the
single source of truth for CSV headers AND for the SQL DDL — keep them in sync.

SourceSystem is always "FollowUpBoss" (DATA_RULES §4).
"""
from __future__ import annotations

from typing import Any

from fub_api.sanitize import (
    clean_bit,
    clean_date,
    clean_email,
    clean_id,
    clean_int,
    clean_phone,
    clean_text,
    clean_utc_ts,
)

SOURCE_SYSTEM = "FollowUpBoss"


# ---------------- Custom fields ----------------
# Generated from GET /customFields on 2026-05-27 (the connected account,
# 22 definitions). The CSV schema is fixed from this list so it's stable run to
# run; any custom field FUB adds later still lands in RawJson, so nothing is
# lost — regenerate this map and add columns when you want it promoted.
# Person custom fields require requesting `?fields=allFields` (the default
# People list omits them). date-typed -> clean_date, everything else -> clean_text.
CUSTOM_FIELD_TYPES: dict[str, str] = {
    "customBirthday": "date",
    "customClosingAnniversary": "date",
    "customColdCaller": "text",
    "customDateOfSale": "date",
    "customEstimatedAvailableEquity": "number",
    "customEstimatedEquity": "text",
    "customEstimatedLoanBalance": "number",
    "customHomeownerDeceased": "text",
    "customInterestRate": "text",
    "customLTVRatio": "text",
    "customLease": "text",
    "customLeaseExpiry": "text",
    "customLengthOfOwnership": "text",
    "customMonthlyRent": "text",
    "customMortgageAmount": "text",
    "customMortgagee": "text",
    "customOccupancy": "text",
    "customPropertiesAtMailingAddress": "text",
    "customPropertyCondition": "text",
    "customSRan": "text",
    "customSellerSIdealPrice": "number",
    "customWebsite": "text",
}


def _custom_column(api_name: str) -> str:
    """customMortgageAmount -> CustomMortgageAmount (stable PascalCase)."""
    return "Custom" + api_name[len("custom"):]


CUSTOM_COLUMNS = [_custom_column(n) for n in CUSTOM_FIELD_TYPES]


def _map_custom_fields(p: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for api_name, ftype in CUSTOM_FIELD_TYPES.items():
        raw = p.get(api_name)
        # numbers kept as text to preserve the source value exactly; the
        # backend can cast. dates normalized to YYYY-MM-DD.
        out[_custom_column(api_name)] = (
            clean_date(raw) if ftype == "date" else clean_text(raw, max_len=512)
        )
    return out


# ---------------- People ----------------

PEOPLE_COLUMNS = [
    "PersonId",
    "Name",
    "FirstName",
    "LastName",
    "Stage",
    "StageId",
    "Type",
    "Source",
    "SourceId",
    "LeadFlowId",
    "AssignedUserId",
    "AssignedTo",
    "AssignedLenderId",
    "AssignedLenderName",
    "AssignedPondId",
    "PrimaryEmail",
    "PrimaryPhone",
    "Emails",
    "Phones",
    "Tags",
    "AddressStreet",
    "AddressCity",
    "AddressState",
    "AddressCode",
    "Price",
    "IsDelayed",
    "ContactedCount",
    "IsClaimed",
    "WebsiteVisits",
    "DealStatus",
    "DealStage",
    "DealName",
    "DealCloseDate",
    "DealPrice",
    "CreatedVia",
    "CreatedUtc",
    "UpdatedUtc",
    "LastActivityUtc",
    *CUSTOM_COLUMNS,
    "RawJson",
    "SourceSystem",
    "SourceSystemId",
    "ExtractedAtUtc",
]


def _primary(items: list[dict] | None, value_key: str = "value") -> str:
    """Pull the primary entry's value from a FUB email/phone array."""
    if not items:
        return ""
    for it in items:
        if it.get("isPrimary") in (1, True, "1"):
            return str(it.get(value_key) or "")
    return str(items[0].get(value_key) or "")


def _joined(items: list[dict] | None, value_key: str = "value") -> str:
    if not items:
        return ""
    return "|".join(str(it.get(value_key) or "") for it in items if it.get(value_key))


def map_person(p: dict, *, extracted_at: str) -> dict[str, Any]:
    addresses = p.get("addresses") or []
    addr = addresses[0] if addresses else {}
    row: dict[str, Any] = {
        "PersonId": clean_id(p.get("id")),
        "Name": clean_text(p.get("name"), max_len=256),
        "FirstName": clean_text(p.get("firstName"), max_len=128),
        "LastName": clean_text(p.get("lastName"), max_len=128),
        "Stage": clean_text(p.get("stage"), max_len=128),
        "StageId": clean_int(p.get("stageId")),
        "Type": clean_text(p.get("type"), max_len=64),
        "Source": clean_text(p.get("source"), max_len=128),
        "SourceId": clean_int(p.get("sourceId")),
        "LeadFlowId": clean_int(p.get("leadFlowId")),
        "AssignedUserId": clean_int(p.get("assignedUserId")),
        "AssignedTo": clean_text(p.get("assignedTo"), max_len=128),
        "AssignedLenderId": clean_int(p.get("assignedLenderId")),
        "AssignedLenderName": clean_text(p.get("assignedLenderName"), max_len=128),
        "AssignedPondId": clean_int(p.get("assignedPondId")),
        "PrimaryEmail": clean_email(_primary(p.get("emails"))),
        "PrimaryPhone": clean_phone(_primary(p.get("phones"))),
        "Emails": clean_text(_joined(p.get("emails")), max_len=1024),
        "Phones": clean_text(_joined(p.get("phones")), max_len=512),
        "Tags": clean_text(p.get("tags"), max_len=2048),  # list -> pipe-joined
        "AddressStreet": clean_text(addr.get("street"), max_len=256),
        "AddressCity": clean_text(addr.get("city"), max_len=128),
        "AddressState": clean_text(addr.get("state"), max_len=64),
        "AddressCode": clean_text(addr.get("code"), max_len=32),
        "Price": clean_int(p.get("price")),
        "IsDelayed": clean_bit(p.get("delayed")),
        "ContactedCount": clean_int(p.get("contacted")),
        "IsClaimed": clean_bit(p.get("claimed")),
        "WebsiteVisits": clean_int(p.get("websiteVisits")),
        "DealStatus": clean_text(p.get("dealStatus"), max_len=64),
        "DealStage": clean_text(p.get("dealStage"), max_len=128),
        "DealName": clean_text(p.get("dealName"), max_len=256),
        "DealCloseDate": clean_date(p.get("dealCloseDate")),
        "DealPrice": clean_int(p.get("dealPrice")),
        "CreatedVia": clean_text(p.get("createdVia"), max_len=64),
        "CreatedUtc": clean_utc_ts(p.get("created")),
        "UpdatedUtc": clean_utc_ts(p.get("updated")),
        "LastActivityUtc": clean_utc_ts(p.get("lastActivity")),
        # RawJson preserves the complete record (incl. any custom/new field).
        # clean_text json-dumps the dict and strips newlines for CSV safety.
        "RawJson": clean_text(p),
        "SourceSystem": SOURCE_SYSTEM,
        "SourceSystemId": clean_id(p.get("id")),
        "ExtractedAtUtc": extracted_at,
    }
    row.update(_map_custom_fields(p))
    return row


# ---------------- Deals ----------------
# Deals return custom fields inline (no `allFields`); the account defines 1:
# customClosingDate (date). `people` is the funnel join key (array of
# {id,name}); `users` is the assigned agents (array of {id,name}).

DEAL_COLUMNS = [
    "DealId",
    "Name",
    "DealType",
    "Status",
    "Price",
    "OrderWeight",
    "Description",
    "PipelineId",
    "PipelineName",
    "StageId",
    "StageName",
    "EnteredStageUtc",
    "CommissionValue",
    "AgentCommission",
    "TeamCommission",
    "TimeToClose",
    "ProjectedCloseDate",
    "EarnestMoneyDueDate",
    "MutualAcceptanceDate",
    "DueDiligenceDate",
    "FinalWalkThroughDate",
    "PossessionDate",
    "CustomClosingDate",
    "PrimaryPersonId",
    "PersonIds",
    "PersonNames",
    "PrimaryUserId",
    "UserIds",
    "UserNames",
    "CreatedUtc",
    "RawJson",
    "SourceSystem",
    "SourceSystemId",
    "ExtractedAtUtc",
]


def _ids(items: list[dict] | None) -> str:
    if not items:
        return ""
    return "|".join(clean_id(it.get("id")) for it in items if it.get("id") is not None)


def _names(items: list[dict] | None) -> str:
    if not items:
        return ""
    return clean_text("|".join(str(it.get("name") or "") for it in items), max_len=1024)


def _first_id(items: list[dict] | None) -> str:
    if not items:
        return ""
    return clean_id(items[0].get("id"))


def map_deal(d: dict, *, extracted_at: str) -> dict[str, Any]:
    people = d.get("people") or []
    users = d.get("users") or []
    return {
        "DealId": clean_id(d.get("id")),
        "Name": clean_text(d.get("name"), max_len=512),
        "DealType": clean_int(d.get("type")),
        "Status": clean_text(d.get("status"), max_len=64),
        "Price": clean_int(d.get("price")),
        "OrderWeight": clean_int(d.get("orderWeight")),
        "Description": clean_text(d.get("description"), max_len=4000),
        "PipelineId": clean_int(d.get("pipelineId")),
        "PipelineName": clean_text(d.get("pipelineName"), max_len=256),
        "StageId": clean_int(d.get("stageId")),
        "StageName": clean_text(d.get("stageName"), max_len=256),
        "EnteredStageUtc": clean_utc_ts(d.get("enteredStageAt")),
        "CommissionValue": clean_int(d.get("commissionValue")),
        "AgentCommission": clean_int(d.get("agentCommission")),
        "TeamCommission": clean_int(d.get("teamCommission")),
        "TimeToClose": clean_int(d.get("timeToClose")),
        "ProjectedCloseDate": clean_date(d.get("projectedCloseDate")),
        "EarnestMoneyDueDate": clean_date(d.get("earnestMoneyDueDate")),
        "MutualAcceptanceDate": clean_date(d.get("mutualAcceptanceDate")),
        "DueDiligenceDate": clean_date(d.get("dueDiligenceDate")),
        "FinalWalkThroughDate": clean_date(d.get("finalWalkThroughDate")),
        "PossessionDate": clean_date(d.get("possessionDate")),
        "CustomClosingDate": clean_date(d.get("customClosingDate")),
        "PrimaryPersonId": _first_id(people),
        "PersonIds": _ids(people),
        "PersonNames": _names(people),
        "PrimaryUserId": _first_id(users),
        "UserIds": _ids(users),
        "UserNames": _names(users),
        "CreatedUtc": clean_utc_ts(d.get("createdAt")),
        "RawJson": clean_text(d),
        "SourceSystem": SOURCE_SYSTEM,
        "SourceSystemId": clean_id(d.get("id")),
        "ExtractedAtUtc": extracted_at,
    }


# ---------------- Events ----------------
# Activity log (emails, calls, inquiries, web visits, ...). `personId` is the
# funnel FK. No custom fields. `property`/`propertySearch` may be objects and
# `additional` a list — captured as text (clean_text json-dumps) + in RawJson.
# NOTE: /events is rate-limited to 10/window (vs 125) — pace via the throttle.

EVENT_COLUMNS = [
    "EventId",
    "PersonId",
    "Type",
    "Source",
    "Message",
    "Description",
    "NoteId",
    "PageTitle",
    "PageUrl",
    "PageDuration",
    "Property",
    "PropertySearch",
    "Additional",
    "OccurredUtc",
    "CreatedUtc",
    "UpdatedUtc",
    "RawJson",
    "SourceSystem",
    "SourceSystemId",
    "ExtractedAtUtc",
]


def map_event(e: dict, *, extracted_at: str) -> dict[str, Any]:
    return {
        "EventId": clean_id(e.get("id")),
        "PersonId": clean_id(e.get("personId")),
        "Type": clean_text(e.get("type"), max_len=128),
        "Source": clean_text(e.get("source"), max_len=128),
        "Message": clean_text(e.get("message"), max_len=4000),
        "Description": clean_text(e.get("description"), max_len=4000),
        "NoteId": clean_id(e.get("noteId")),
        "PageTitle": clean_text(e.get("pageTitle"), max_len=512),
        "PageUrl": clean_text(e.get("pageUrl"), max_len=1024),
        "PageDuration": clean_int(e.get("pageDuration")),
        "Property": clean_text(e.get("property"), max_len=4000),
        "PropertySearch": clean_text(e.get("propertySearch"), max_len=4000),
        "Additional": clean_text(e.get("additional"), max_len=4000),
        "OccurredUtc": clean_utc_ts(e.get("occurred")),
        "CreatedUtc": clean_utc_ts(e.get("created")),
        "UpdatedUtc": clean_utc_ts(e.get("updated")),
        "RawJson": clean_text(e),
        "SourceSystem": SOURCE_SYSTEM,
        "SourceSystemId": clean_id(e.get("id")),
        "ExtractedAtUtc": extracted_at,
    }


# ---------------- Users (dimension) ----------------
# Team members. Resolves AssignedUserId on People and PrimaryUserId/UserIds on
# Deals. `picture` is an object (we keep the original URL), `groups` an array of
# {id,name}, `mlsMemberships` an array (empty here) — full record in RawJson.

USER_COLUMNS = [
    "UserId",
    "Name",
    "FirstName",
    "LastName",
    "Email",
    "Phone",
    "Role",
    "Status",
    "Timezone",
    "IsOwner",
    "PauseLeadDistribution",
    "CanExport",
    "CanCreateApiKeys",
    "Fuid",
    "LeadEmailAddress",
    "PictureUrl",
    "GroupIds",
    "GroupNames",
    "LastSeenIosUtc",
    "LastSeenAndroidUtc",
    "LastSeenFub2Utc",
    "CreatedUtc",
    "UpdatedUtc",
    "RawJson",
    "SourceSystem",
    "SourceSystemId",
    "ExtractedAtUtc",
]


def map_user(u: dict, *, extracted_at: str) -> dict[str, Any]:
    picture = u.get("picture") or {}
    groups = u.get("groups") or []
    return {
        "UserId": clean_id(u.get("id")),
        "Name": clean_text(u.get("name"), max_len=256),
        "FirstName": clean_text(u.get("firstName"), max_len=128),
        "LastName": clean_text(u.get("lastName"), max_len=128),
        "Email": clean_email(u.get("email")),
        "Phone": clean_phone(u.get("phone")),
        "Role": clean_text(u.get("role"), max_len=64),
        "Status": clean_text(u.get("status"), max_len=64),
        "Timezone": clean_text(u.get("timezone"), max_len=64),
        "IsOwner": clean_bit(u.get("isOwner")),
        "PauseLeadDistribution": clean_bit(u.get("pauseLeadDistribution")),
        "CanExport": clean_bit(u.get("canExport")),
        "CanCreateApiKeys": clean_bit(u.get("canCreateApiKeys")),
        "Fuid": clean_text(u.get("fuid"), max_len=64),
        "LeadEmailAddress": clean_email(u.get("leadEmailAddress")),
        "PictureUrl": clean_text(picture.get("original"), max_len=1024),
        "GroupIds": clean_text(_ids(groups), max_len=256),
        "GroupNames": _names(groups),
        "LastSeenIosUtc": clean_utc_ts(u.get("lastSeenIos")),
        "LastSeenAndroidUtc": clean_utc_ts(u.get("lastSeenAndroid")),
        "LastSeenFub2Utc": clean_utc_ts(u.get("lastSeenFub2")),
        "CreatedUtc": clean_utc_ts(u.get("created")),
        "UpdatedUtc": clean_utc_ts(u.get("updated")),
        "RawJson": clean_text(u),
        "SourceSystem": SOURCE_SYSTEM,
        "SourceSystemId": clean_id(u.get("id")),
        "ExtractedAtUtc": extracted_at,
    }


# ---------------- Pipelines (dimension) ----------------
# Deal pipeline definitions. Resolves Deals.PipelineId. Each pipeline carries a
# denormalized `stages[]` array; we keep a count + the pipe-joined StageIds for
# convenience, and the authoritative per-stage rows live in the Stages table.

PIPELINE_COLUMNS = [
    "PipelineId",
    "Name",
    "Description",
    "OrderWeight",
    "StageCount",
    "StageIds",
    "RawJson",
    "SourceSystem",
    "SourceSystemId",
    "ExtractedAtUtc",
]


def map_pipeline(p: dict, *, extracted_at: str) -> dict[str, Any]:
    stages = p.get("stages") or []
    return {
        "PipelineId": clean_id(p.get("id")),
        "Name": clean_text(p.get("name"), max_len=256),
        "Description": clean_text(p.get("description"), max_len=1024),
        "OrderWeight": clean_int(p.get("orderWeight")),
        "StageCount": clean_int(len(stages)),
        "StageIds": clean_text(_ids(stages), max_len=512),
        "RawJson": clean_text(p),
        "SourceSystem": SOURCE_SYSTEM,
        "SourceSystemId": clean_id(p.get("id")),
        "ExtractedAtUtc": extracted_at,
    }


# ---------------- Stages (dimension) ----------------
# UNIFIED stage dimension resolving BOTH People.StageId and Deals.StageId.
# Two FUB sources, disjoint id ranges, merged into one table:
#   - GET /stages          -> person stages  (pipelineId=null; has peopleCount,
#                             isProtected, systems; no color/closedStage)
#   - /pipelines[].stages[] -> deal stages    (carry color + closedStage; lack
#                             peopleCount/isProtected; pipelineId = parent)
# The standalone /stages collection does NOT contain the deal-pipeline stages,
# so a person-only Stages table leaves every Deals.StageId orphaned. StageKind
# records which source a row came from. map_stage accepts either shape plus an
# optional pipeline_id (set for nested deal stages) and kind. Built by
# scripts/build_stages.py (needs two endpoints, so it's not a generic export).

STAGE_COLUMNS = [
    "StageId",
    "Name",
    "PipelineId",
    "StageKind",
    "OrderWeight",
    "IsProtected",
    "PeopleCount",
    "Color",
    "ClosedStage",
    "Description",
    "RawJson",
    "SourceSystem",
    "SourceSystemId",
    "ExtractedAtUtc",
]


def map_stage(
    s: dict,
    *,
    extracted_at: str,
    pipeline_id: int | str | None = None,
    kind: str = "Person",
) -> dict[str, Any]:
    pid = pipeline_id if pipeline_id is not None else s.get("pipelineId")
    return {
        "StageId": clean_id(s.get("id")),
        "Name": clean_text(s.get("name"), max_len=256),
        "PipelineId": clean_int(pid),
        "StageKind": clean_text(kind, max_len=16),
        "OrderWeight": clean_int(s.get("orderWeight")),
        "IsProtected": clean_bit(s.get("isProtected")),
        "PeopleCount": clean_int(s.get("peopleCount")),
        "Color": clean_text(s.get("color"), max_len=32),
        "ClosedStage": clean_bit(s.get("closedStage")),
        "Description": clean_text(s.get("description"), max_len=1024),
        "RawJson": clean_text(s),
        "SourceSystem": SOURCE_SYSTEM,
        "SourceSystemId": clean_id(s.get("id")),
        "ExtractedAtUtc": extracted_at,
    }


# ---------------- Sources (DERIVED dimension) ----------------
# FUB exposes no usable sources endpoint on the current key (/sources 404,
# /leadSources 403 — non-owner scope). Derived instead from the distinct
# (SourceId, Source) pairs already in People.csv. `Derived="1"` marks the
# provenance so these rows can be re-pulled authoritatively once an
# owner-scoped key is available. The aggregated input dict uses snake_case keys
# (source_id / name / people_count) built by scripts/derive_dims.py.

SOURCE_COLUMNS = [
    "SourceId",
    "Name",
    "PeopleCount",
    "Derived",
    "SourceSystem",
    "SourceSystemId",
    "ExtractedAtUtc",
]


def map_source(rec: dict, *, extracted_at: str) -> dict[str, Any]:
    return {
        "SourceId": clean_int(rec.get("source_id")),
        "Name": clean_text(rec.get("name"), max_len=128),
        "PeopleCount": clean_int(rec.get("people_count")),
        "Derived": "1",
        "SourceSystem": SOURCE_SYSTEM,
        "SourceSystemId": clean_id(rec.get("source_id")),
        "ExtractedAtUtc": extracted_at,
    }


# ---------------- Tags (DERIVED dimension) ----------------
# /tags is 403 on the current key. FUB tags are plain strings (no IDs), stored
# pipe-delimited on People.Tags, so the natural key is the tag name itself —
# that's also the only key the facts can join on. Derived from the distinct tag
# strings in People.csv. PK is TagName (NVARCHAR); emoji tags are expected.

TAG_COLUMNS = [
    "TagName",
    "PeopleCount",
    "Derived",
    "SourceSystem",
    "SourceSystemId",
    "ExtractedAtUtc",
]


def map_tag(rec: dict, *, extracted_at: str) -> dict[str, Any]:
    name = clean_text(rec.get("name"), max_len=256)
    return {
        "TagName": name,
        "PeopleCount": clean_int(rec.get("people_count")),
        "Derived": "1",
        "SourceSystem": SOURCE_SYSTEM,
        "SourceSystemId": name,
        "ExtractedAtUtc": extracted_at,
    }
