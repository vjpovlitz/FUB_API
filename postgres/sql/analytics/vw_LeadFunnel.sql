-- Postgres port of sql/analytics/vw_LeadFunnel.sql
-- analytics.vw_LeadFunnel — UNION of ghl + fub daily lead funnels, normalized to
-- a CRM-agnostic grain with a SourceSystem discriminator.
-- Depends on ghl.vw_DailyLeadFunnel + fub.vw_DailyLeadFunnel.

CREATE SCHEMA IF NOT EXISTS analytics;

CREATE OR REPLACE VIEW analytics.vw_LeadFunnel AS
SELECT
    CAST("LeadDate"        AS DATE)         AS "LeadDate",
    CAST("LeadSource"      AS VARCHAR(128)) AS "LeadSource",
    CAST('GoHighLevel' AS VARCHAR(32))      AS "SourceSystem",
    CAST("LeadsCreated"    AS BIGINT)       AS "LeadsCreated",
    CAST("EngagedContacts" AS BIGINT)       AS "EngagedContacts",
    CAST("OppsCreated"     AS BIGINT)       AS "OppsCreated",
    CAST("OppsWon"         AS BIGINT)       AS "OppsWon",
    CAST("EngagedPct"      AS DECIMAL(5,1)) AS "EngagedPct"
FROM ghl.vw_DailyLeadFunnel

UNION ALL

SELECT
    CAST("LeadDate"        AS DATE),
    CAST("LeadSource"      AS VARCHAR(128)),
    CAST('FollowUpBoss' AS VARCHAR(32)),
    CAST("LeadsCreated"    AS BIGINT),
    CAST("EngagedContacts" AS BIGINT),
    CAST("DealsCreated"    AS BIGINT),
    CAST("DealsClosed"     AS BIGINT),
    CAST("EngagedPct"      AS DECIMAL(5,1))
FROM fub.vw_DailyLeadFunnel;
