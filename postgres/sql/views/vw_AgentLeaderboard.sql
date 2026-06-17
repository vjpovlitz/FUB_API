-- Postgres port of sql/views/vw_AgentLeaderboard.sql
-- fub.vw_AgentLeaderboard — per-agent activity rollup (keyed on UserId string).
-- T-SQL->PG: DATEADD/GETUTCDATE -> now() AT TIME ZONE 'utc' - INTERVAL,
-- ISNULL->COALESCE, COUNT_BIG->COUNT, ClosedStage=1 -> boolean.

CREATE OR REPLACE VIEW fub.vw_AgentLeaderboard AS
WITH agent_people AS (
    SELECT
        CAST("AssignedUserId" AS VARCHAR(64)) AS "UserId",
        COUNT(*) AS "LeadsAssigned",
        SUM(CASE WHEN "CreatedUtc" >= (now() AT TIME ZONE 'utc') - INTERVAL '7 days'
                 THEN 1 ELSE 0 END) AS "LeadsLast7",
        SUM(CASE WHEN "CreatedUtc" >= (now() AT TIME ZONE 'utc') - INTERVAL '30 days'
                 THEN 1 ELSE 0 END) AS "LeadsLast30"
    FROM fub."People"
    WHERE "AssignedUserId" IS NOT NULL
    GROUP BY CAST("AssignedUserId" AS VARCHAR(64))
),
agent_events AS (
    SELECT
        CAST(p."AssignedUserId" AS VARCHAR(64)) AS "UserId",
        COUNT(*) AS "EventsTotal",
        SUM(CASE WHEN COALESCE(e."OccurredUtc", e."CreatedUtc")
                      >= (now() AT TIME ZONE 'utc') - INTERVAL '7 days'
                 THEN 1 ELSE 0 END) AS "EventsLast7"
    FROM fub."Events" e
    JOIN fub."People" p ON p."PersonId" = e."PersonId"
    WHERE p."AssignedUserId" IS NOT NULL
    GROUP BY CAST(p."AssignedUserId" AS VARCHAR(64))
),
agent_deals AS (
    SELECT
        d."PrimaryUserId" AS "UserId",
        COUNT(*) AS "DealsTotal",
        SUM(CASE WHEN s."ClosedStage" THEN 1 ELSE 0 END) AS "DealsClosed",
        SUM(CASE WHEN NOT COALESCE(s."ClosedStage", FALSE)
                 THEN COALESCE(d."Price", 0) ELSE 0 END) AS "PipelineValueOpen",
        SUM(CASE WHEN s."ClosedStage"
                 THEN COALESCE(d."Price", 0) ELSE 0 END) AS "PipelineValueClosed"
    FROM fub."Deals" d
    LEFT JOIN fub."Stages" s ON s."StageId" = CAST(d."StageId" AS VARCHAR(64)) AND s."StageKind" = 'Deal'
    WHERE d."PrimaryUserId" IS NOT NULL AND d."PrimaryUserId" <> ''
    GROUP BY d."PrimaryUserId"
)
SELECT
    COALESCE(ap."UserId", COALESCE(ae."UserId", ad."UserId")) AS "UserId",
    COALESCE(ap."LeadsAssigned", 0)       AS "LeadsAssigned",
    COALESCE(ap."LeadsLast7", 0)          AS "LeadsLast7",
    COALESCE(ap."LeadsLast30", 0)         AS "LeadsLast30",
    COALESCE(ae."EventsTotal", 0)         AS "EventsTotal",
    COALESCE(ae."EventsLast7", 0)         AS "EventsLast7",
    COALESCE(ad."DealsTotal", 0)          AS "DealsTotal",
    COALESCE(ad."DealsClosed", 0)         AS "DealsClosed",
    COALESCE(ad."PipelineValueOpen", 0)   AS "PipelineValueOpen",
    COALESCE(ad."PipelineValueClosed", 0) AS "PipelineValueClosed"
FROM      agent_people ap
FULL JOIN agent_events ae ON ae."UserId" = ap."UserId"
FULL JOIN agent_deals  ad ON ad."UserId" = COALESCE(ap."UserId", ae."UserId");
