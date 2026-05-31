/*
============================================================================
analytics.vw_LeadFunnel — cross-system daily lead funnel

UNION of ghl.vw_DailyLeadFunnel + fub.vw_DailyLeadFunnel, normalized to one
CRM-agnostic funnel grain with a SourceSystem discriminator. The dashboard
reads THIS, never the per-CRM funnel views directly — so the funnel page is
vendor-neutral and the app is portable to a multi-tenant product.

Canonical funnel: LeadsCreated -> EngagedContacts -> OppsCreated -> OppsWon.
  GHL "Opps" = Opportunities (OppsCreated/OppsWon).
  FUB "Opps" = Deals          (DealsCreated/DealsClosed).
GHL-only appointment columns (ApptsBooked/Showed) are intentionally dropped —
they don't generalize across CRMs.

Depends on BOTH ghl.* and fub.* — applied separately from the fub loader's
fub.vw_* step (same as vw_AllContacts).

Columns:
    LeadDate, LeadSource, SourceSystem,
    LeadsCreated, EngagedContacts, OppsCreated, OppsWon,
    EngagedPct  (carried from the source view)
============================================================================
*/

IF SCHEMA_ID('analytics') IS NULL EXEC('CREATE SCHEMA analytics');
GO

IF OBJECT_ID('analytics.vw_LeadFunnel', 'V') IS NOT NULL
    DROP VIEW analytics.vw_LeadFunnel;
GO

CREATE VIEW analytics.vw_LeadFunnel AS
SELECT
    CAST(LeadDate     AS DATE)         AS LeadDate,
    CAST(LeadSource   AS NVARCHAR(128)) AS LeadSource,
    CAST('GoHighLevel' AS VARCHAR(32)) AS SourceSystem,
    CAST(LeadsCreated    AS BIGINT)    AS LeadsCreated,
    CAST(EngagedContacts AS BIGINT)    AS EngagedContacts,
    CAST(OppsCreated     AS BIGINT)    AS OppsCreated,
    CAST(OppsWon         AS BIGINT)    AS OppsWon,
    CAST(EngagedPct      AS DECIMAL(5,1)) AS EngagedPct
FROM ghl.vw_DailyLeadFunnel

UNION ALL

SELECT
    CAST(LeadDate     AS DATE)         AS LeadDate,
    CAST(LeadSource   AS NVARCHAR(128)) AS LeadSource,
    CAST('FollowUpBoss' AS VARCHAR(32)) AS SourceSystem,
    CAST(LeadsCreated    AS BIGINT)    AS LeadsCreated,
    CAST(EngagedContacts AS BIGINT)    AS EngagedContacts,
    CAST(DealsCreated    AS BIGINT)    AS OppsCreated,
    CAST(DealsClosed     AS BIGINT)    AS OppsWon,
    CAST(EngagedPct      AS DECIMAL(5,1)) AS EngagedPct
FROM fub.vw_DailyLeadFunnel;
GO

/*
Smoke query:
    SELECT SourceSystem, SUM(LeadsCreated) Leads, SUM(OppsWon) Won
    FROM analytics.vw_LeadFunnel GROUP BY SourceSystem;
*/
