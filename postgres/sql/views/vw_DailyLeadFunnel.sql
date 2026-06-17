-- Postgres port of sql/views/vw_DailyLeadFunnel.sql
-- fub.vw_DailyLeadFunnel — lead conversion funnel by day + source.
-- T-SQL->PG: ISNULL->COALESCE, COUNT_BIG->COUNT, ClosedStage=1 -> boolean,
-- quoted PascalCase identifiers, no GO. "Closed" = deal stage has ClosedStage.

CREATE OR REPLACE VIEW fub.vw_DailyLeadFunnel AS
WITH leads AS (
    SELECT
        CAST("CreatedUtc" AS DATE)                  AS "LeadDate",
        COALESCE(NULLIF("Source", ''), '(unknown)') AS "LeadSource",
        "PersonId"
    FROM fub."People"
    WHERE "CreatedUtc" IS NOT NULL
),
first_event AS (
    SELECT
        "PersonId",
        MIN(COALESCE("OccurredUtc", "CreatedUtc")) AS "FirstEventUtc"
    FROM fub."Events"
    WHERE "PersonId" IS NOT NULL
    GROUP BY "PersonId"
),
deal_first AS (
    SELECT
        d."PrimaryPersonId" AS "PersonId",
        MIN(d."CreatedUtc") AS "FirstDealUtc",
        MIN(CASE WHEN s."ClosedStage"
                 THEN COALESCE(d."EnteredStageUtc", d."CreatedUtc") END) AS "FirstClosedUtc"
    FROM fub."Deals" d
    LEFT JOIN fub."Stages" s
      ON s."StageId" = CAST(d."StageId" AS VARCHAR(64)) AND s."StageKind" = 'Deal'
    WHERE d."PrimaryPersonId" IS NOT NULL AND d."PrimaryPersonId" <> ''
    GROUP BY d."PrimaryPersonId"
)
SELECT
    l."LeadDate",
    l."LeadSource",
    COUNT(*)                     AS "LeadsCreated",
    COUNT(fe."PersonId")         AS "EngagedContacts",
    COUNT(df."FirstDealUtc")     AS "DealsCreated",
    COUNT(df."FirstClosedUtc")   AS "DealsClosed",
    CASE WHEN COUNT(*) > 0
         THEN 100.0 * COUNT(fe."PersonId") / COUNT(*) ELSE 0 END AS "EngagedPct",
    CASE WHEN COUNT(*) > 0
         THEN 100.0 * COUNT(df."FirstDealUtc") / COUNT(*) ELSE 0 END AS "DealPct",
    CASE WHEN COUNT(*) > 0
         THEN 100.0 * COUNT(df."FirstClosedUtc") / COUNT(*) ELSE 0 END AS "ClosedPct"
FROM      leads      l
LEFT JOIN first_event fe ON fe."PersonId" = l."PersonId"
LEFT JOIN deal_first  df ON df."PersonId" = l."PersonId"
GROUP BY l."LeadDate", l."LeadSource";
