/*
============================================================================
analytics.vw_AgentLeaderboard — cross-system per-agent rollup

UNION of ghl.vw_AgentLeaderboard + fub.vw_AgentLeaderboard, normalized + the
agent's display name resolved from each CRM's Users dim, with a SourceSystem
discriminator. CRM-agnostic so the Agents page is vendor-neutral.

Normalized "activity" + "deals" because the two CRMs count different things:
  ActivityCount = GHL messages (out+in)        | FUB events
  DealsTotal    = GHL opportunities total       | FUB deals total
  DealsWon      = GHL opportunities won          | FUB deals closed
  PipelineValueOpen / PipelineValueWon          | (FUB "closed" == won)

Depends on BOTH ghl.* and fub.* — applied separately (see vw_AllContacts).

Columns:
    SourceSystem, UserId, AgentName, Role,
    LeadsAssigned, LeadsLast7, LeadsLast30,
    ActivityCount, DealsTotal, DealsWon,
    PipelineValueOpen, PipelineValueWon
============================================================================
*/

IF SCHEMA_ID('analytics') IS NULL EXEC('CREATE SCHEMA analytics');
GO

IF OBJECT_ID('analytics.vw_AgentLeaderboard', 'V') IS NOT NULL
    DROP VIEW analytics.vw_AgentLeaderboard;
GO

CREATE VIEW analytics.vw_AgentLeaderboard AS
SELECT
    CAST('GoHighLevel' AS VARCHAR(32))                          AS SourceSystem,
    CAST(LB.UserId AS VARCHAR(64))                              AS UserId,
    CAST(ISNULL(NULLIF(U.FullName,''), LB.UserId) AS NVARCHAR(256)) AS AgentName,
    CAST(U.Role AS NVARCHAR(64))                                AS Role,
    CAST(LB.LeadsAssigned AS BIGINT)                            AS LeadsAssigned,
    CAST(LB.LeadsLast7    AS INT)                               AS LeadsLast7,
    CAST(LB.LeadsLast30   AS INT)                               AS LeadsLast30,
    CAST(LB.MsgsOutbound + LB.MsgsInbound AS BIGINT)            AS ActivityCount,
    CAST(LB.OppsTotal AS BIGINT)                                AS DealsTotal,
    CAST(LB.OppsWon   AS INT)                                   AS DealsWon,
    CAST(LB.PipelineValueOpen AS DECIMAL(18,2))                 AS PipelineValueOpen,
    CAST(LB.PipelineValueWon  AS DECIMAL(18,2))                 AS PipelineValueWon
FROM ghl.vw_AgentLeaderboard LB
LEFT JOIN ghl.Users U ON U.UserId = LB.UserId

UNION ALL

SELECT
    CAST('FollowUpBoss' AS VARCHAR(32))                         AS SourceSystem,
    CAST(LB.UserId AS VARCHAR(64))                              AS UserId,
    CAST(ISNULL(NULLIF(U.Name,''), LB.UserId) AS NVARCHAR(256)) AS AgentName,
    CAST(U.Role AS NVARCHAR(64))                                AS Role,
    CAST(LB.LeadsAssigned AS BIGINT)                            AS LeadsAssigned,
    CAST(LB.LeadsLast7    AS INT)                               AS LeadsLast7,
    CAST(LB.LeadsLast30   AS INT)                               AS LeadsLast30,
    CAST(LB.EventsTotal AS BIGINT)                              AS ActivityCount,
    CAST(LB.DealsTotal  AS BIGINT)                              AS DealsTotal,
    CAST(LB.DealsClosed AS INT)                                 AS DealsWon,
    CAST(LB.PipelineValueOpen   AS DECIMAL(18,2))               AS PipelineValueOpen,
    CAST(LB.PipelineValueClosed AS DECIMAL(18,2))               AS PipelineValueWon
FROM fub.vw_AgentLeaderboard LB
LEFT JOIN fub.Users U ON CAST(U.UserId AS VARCHAR(64)) = LB.UserId;
GO

/*
Smoke query:
    SELECT SourceSystem, COUNT(*) Agents, SUM(LeadsAssigned) Leads
    FROM analytics.vw_AgentLeaderboard GROUP BY SourceSystem;
*/
