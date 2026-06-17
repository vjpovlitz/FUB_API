-- Postgres port of sql/analytics/vw_Opportunities.sql
-- analytics.vw_Opportunities — UNION of ghl.Opportunities + fub.Deals into one
-- normalized opportunity grain. FUB "Won" = stage maps to ClosedStage=TRUE.
-- Depends on ghl.* and fub.*. Note the Deals.StageId(int)->Stages.StageId(varchar) cast.

CREATE SCHEMA IF NOT EXISTS analytics;

CREATE OR REPLACE VIEW analytics.vw_Opportunities AS
SELECT
    CAST(o."OpportunityId" AS VARCHAR(64))            AS "OpportunityId",
    CAST('GoHighLevel' AS VARCHAR(32))                AS "SourceSystem",
    CAST(o."Name" AS VARCHAR(256))                    AS "Name",
    CAST(COALESCE(p."Name", '(none)') AS VARCHAR(128)) AS "Pipeline",
    CAST(COALESCE(s."Name", '(none)') AS VARCHAR(128)) AS "Stage",
    CAST(CASE lower(o."Status")
            WHEN 'won'  THEN 'Won'
            WHEN 'lost' THEN 'Lost'
            ELSE 'Open' END AS VARCHAR(16))           AS "Status",
    CAST(COALESCE(o."MonetaryValue", 0) AS DECIMAL(18,2)) AS "Value",
    CAST(o."AssignedToUserId" AS VARCHAR(64))         AS "AssignedUserId",
    CAST(u."FullName" AS VARCHAR(256))                AS "AssignedAgent",
    CAST(o."DateAddedUtc"  AS TIMESTAMP(3))           AS "CreatedUtc",
    CAST(o."DateClosedUtc" AS TIMESTAMP(3))           AS "ClosedUtc"
FROM ghl."Opportunities" o
LEFT JOIN ghl."Pipelines"      p ON p."PipelineId" = o."PipelineId"
LEFT JOIN ghl."PipelineStages" s ON s."PipelineStageId" = o."PipelineStageId"
LEFT JOIN ghl."Users"          u ON u."UserId" = o."AssignedToUserId"

UNION ALL

SELECT
    CAST(d."DealId" AS VARCHAR(64)),
    CAST('FollowUpBoss' AS VARCHAR(32)),
    CAST(d."Name" AS VARCHAR(256)),
    CAST(COALESCE(NULLIF(d."PipelineName",''), '(none)') AS VARCHAR(128)),
    CAST(COALESCE(NULLIF(d."StageName",''), '(none)') AS VARCHAR(128)),
    CAST(CASE WHEN st."ClosedStage" THEN 'Won' ELSE 'Open' END AS VARCHAR(16)),
    CAST(COALESCE(d."Price", 0) AS DECIMAL(18,2)),
    CAST(d."PrimaryUserId" AS VARCHAR(64)),
    CAST(COALESCE(NULLIF(u."Name",''), d."UserNames") AS VARCHAR(256)),
    CAST(d."CreatedUtc" AS TIMESTAMP(3)),
    CAST(CASE WHEN st."ClosedStage" THEN d."EnteredStageUtc" ELSE NULL END AS TIMESTAMP(3))
FROM fub."Deals" d
LEFT JOIN fub."Stages" st
  ON st."StageId" = CAST(d."StageId" AS VARCHAR(64)) AND st."StageKind" = 'Deal'
LEFT JOIN fub."Users"  u ON CAST(u."UserId" AS VARCHAR(64)) = d."PrimaryUserId";
