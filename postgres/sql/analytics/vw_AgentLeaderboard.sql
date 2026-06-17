-- Postgres port of sql/analytics/vw_AgentLeaderboard.sql
-- analytics.vw_AgentLeaderboard — UNION of ghl + fub per-agent rollups,
-- normalized + agent name resolved from each CRM's Users dim.
-- Depends on ghl.vw_AgentLeaderboard + fub.vw_AgentLeaderboard (+ Users dims).

CREATE SCHEMA IF NOT EXISTS analytics;

CREATE OR REPLACE VIEW analytics.vw_AgentLeaderboard AS
SELECT
    CAST('GoHighLevel' AS VARCHAR(32))                          AS "SourceSystem",
    CAST(lb."UserId" AS VARCHAR(64))                            AS "UserId",
    CAST(COALESCE(NULLIF(u."FullName",''), lb."UserId") AS VARCHAR(256)) AS "AgentName",
    CAST(u."Role" AS VARCHAR(64))                               AS "Role",
    CAST(lb."LeadsAssigned" AS BIGINT)                          AS "LeadsAssigned",
    CAST(lb."LeadsLast7"    AS INT)                             AS "LeadsLast7",
    CAST(lb."LeadsLast30"   AS INT)                             AS "LeadsLast30",
    CAST(lb."MsgsOutbound" + lb."MsgsInbound" AS BIGINT)        AS "ActivityCount",
    CAST(lb."OppsTotal" AS BIGINT)                              AS "DealsTotal",
    CAST(lb."OppsWon"   AS INT)                                 AS "DealsWon",
    CAST(lb."PipelineValueOpen" AS DECIMAL(18,2))               AS "PipelineValueOpen",
    CAST(lb."PipelineValueWon"  AS DECIMAL(18,2))               AS "PipelineValueWon"
FROM ghl.vw_AgentLeaderboard lb
LEFT JOIN ghl."Users" u ON u."UserId" = lb."UserId"

UNION ALL

SELECT
    CAST('FollowUpBoss' AS VARCHAR(32)),
    CAST(lb."UserId" AS VARCHAR(64)),
    CAST(COALESCE(NULLIF(u."Name",''), lb."UserId") AS VARCHAR(256)),
    CAST(u."Role" AS VARCHAR(64)),
    CAST(lb."LeadsAssigned" AS BIGINT),
    CAST(lb."LeadsLast7"    AS INT),
    CAST(lb."LeadsLast30"   AS INT),
    CAST(lb."EventsTotal" AS BIGINT),
    CAST(lb."DealsTotal"  AS BIGINT),
    CAST(lb."DealsClosed" AS INT),
    CAST(lb."PipelineValueOpen"   AS DECIMAL(18,2)),
    CAST(lb."PipelineValueClosed" AS DECIMAL(18,2))
FROM fub.vw_AgentLeaderboard lb
LEFT JOIN fub."Users" u ON CAST(u."UserId" AS VARCHAR(64)) = lb."UserId";
