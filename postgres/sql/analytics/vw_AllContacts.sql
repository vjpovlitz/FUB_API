-- Postgres port of sql/analytics/vw_AllContacts.sql
-- analytics.vw_AllContacts — UNION of ghl.Contacts + fub.People (cross-system).
-- Depends on BOTH ghl.* and fub.* — apply after both schemas are loaded.

CREATE SCHEMA IF NOT EXISTS analytics;

CREATE OR REPLACE VIEW analytics.vw_AllContacts AS
SELECT
    CAST("ContactId"    AS VARCHAR(64))  AS "ContactId",
    CAST("SourceSystem" AS VARCHAR(32))  AS "SourceSystem",
    CAST("FullName"     AS VARCHAR(256)) AS "FullName",
    CAST("Email"        AS VARCHAR(256)) AS "Email",
    CAST("Phone"        AS VARCHAR(64))  AS "Phone",
    CAST("Source"       AS VARCHAR(128)) AS "Source",
    CAST("DateAddedUtc" AS TIMESTAMP(3)) AS "DateAddedUtc"
FROM ghl."Contacts"

UNION ALL

SELECT
    CAST("PersonId"     AS VARCHAR(64)),
    CAST("SourceSystem" AS VARCHAR(32)),
    CAST("Name"         AS VARCHAR(256)),
    CAST("PrimaryEmail" AS VARCHAR(256)),
    CAST("PrimaryPhone" AS VARCHAR(64)),
    CAST("Source"       AS VARCHAR(128)),
    CAST("CreatedUtc"   AS TIMESTAMP(3))
FROM fub."People";
