/*
============================================================================
fub.vw_DailyLeadFunnel — lead conversion funnel by day + source

Mirrors ghl.vw_DailyLeadFunnel, adapted to the FUB data model:

    [1] Leads created     fub.People.CreatedUtc
    [2] Engaged           person has >=1 fub.Events row (inquiry/touch)
    [3] Has deal          person is a deal's PrimaryPersonId
    [4] Deal closed       that deal sits in a closed stage (Stages.ClosedStage=1)

Each person is attributed to the day/source they were CREATED. FUB has no
"won/lost" deal status (all Deals.Status='Active'); the deal lifecycle lives in
the pipeline stage, so "closed" = the deal's StageId maps to a ClosedStage.

Note: includes Trash-stage people (they were still created leads). Filter on a
joined People.Stage in the dashboard if you want them excluded.
============================================================================
*/

IF OBJECT_ID('fub.vw_DailyLeadFunnel', 'V') IS NOT NULL
    DROP VIEW fub.vw_DailyLeadFunnel;
GO

CREATE VIEW fub.vw_DailyLeadFunnel AS
WITH
leads AS (
    SELECT
        CAST(CreatedUtc AS DATE)                  AS LeadDate,
        ISNULL(NULLIF(Source, ''), '(unknown)')   AS LeadSource,
        PersonId
    FROM fub.People
    WHERE CreatedUtc IS NOT NULL
),

-- First inquiry/touch per person (engagement signal)
first_event AS (
    SELECT
        PersonId,
        MIN(ISNULL(OccurredUtc, CreatedUtc)) AS FirstEventUtc
    FROM fub.Events
    WHERE PersonId IS NOT NULL
    GROUP BY PersonId
),

-- Deals attributed to a person via PrimaryPersonId; closed = deal stage is a ClosedStage
deal_first AS (
    SELECT
        d.PrimaryPersonId AS PersonId,
        MIN(d.CreatedUtc) AS FirstDealUtc,
        MIN(CASE WHEN s.ClosedStage = 1 THEN ISNULL(d.EnteredStageUtc, d.CreatedUtc) END) AS FirstClosedUtc
    FROM fub.Deals d
    LEFT JOIN fub.Stages s
      ON s.StageId = d.StageId AND s.StageKind = 'Deal'
    WHERE d.PrimaryPersonId IS NOT NULL AND d.PrimaryPersonId <> ''
    GROUP BY d.PrimaryPersonId
)

SELECT
    L.LeadDate,
    L.LeadSource,
    COUNT_BIG(*)                          AS LeadsCreated,
    COUNT_BIG(FE.PersonId)                AS EngagedContacts,
    COUNT_BIG(DF.FirstDealUtc)            AS DealsCreated,
    COUNT_BIG(DF.FirstClosedUtc)          AS DealsClosed,
    CASE WHEN COUNT_BIG(*) > 0
         THEN 100.0 * COUNT_BIG(FE.PersonId) / COUNT_BIG(*) ELSE 0 END AS EngagedPct,
    CASE WHEN COUNT_BIG(*) > 0
         THEN 100.0 * COUNT_BIG(DF.FirstDealUtc) / COUNT_BIG(*) ELSE 0 END AS DealPct,
    CASE WHEN COUNT_BIG(*) > 0
         THEN 100.0 * COUNT_BIG(DF.FirstClosedUtc) / COUNT_BIG(*) ELSE 0 END AS ClosedPct
FROM       leads       L
LEFT JOIN  first_event FE ON FE.PersonId = L.PersonId
LEFT JOIN  deal_first  DF ON DF.PersonId = L.PersonId
GROUP BY L.LeadDate, L.LeadSource;
GO

/*
Smoke query:
    SELECT TOP 50 * FROM fub.vw_DailyLeadFunnel
    WHERE LeadDate >= DATEADD(DAY, -90, GETUTCDATE())
    ORDER BY LeadDate DESC, LeadsCreated DESC;
*/
