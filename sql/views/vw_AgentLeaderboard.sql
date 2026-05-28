/*
============================================================================
fub.vw_AgentLeaderboard — per-agent activity rollup

Keyed on the agent's UserId (string). FUB joins:
  - People.AssignedUserId (INT) -> cast to VARCHAR to match Users.UserId
  - Events -> People.AssignedUserId (the person's owner handles the touch)
  - Deals.PrimaryUserId (VARCHAR) -> Users.UserId

Metrics:
    LeadsAssigned / LeadsLast7 / LeadsLast30   people owned by the agent
    EventsTotal / EventsLast7                   inquiries/touches on their people
    DealsTotal / DealsClosed                    deals where PrimaryUserId = agent
    PipelineValueOpen / PipelineValueClosed     sum(Price) by closed-stage flag

"Closed" = the deal's StageId maps to a Stages row with ClosedStage=1
(FUB has no won/lost deal status — lifecycle is the pipeline stage).
============================================================================
*/

IF OBJECT_ID('fub.vw_AgentLeaderboard', 'V') IS NOT NULL
    DROP VIEW fub.vw_AgentLeaderboard;
GO

CREATE VIEW fub.vw_AgentLeaderboard AS
WITH
agent_people AS (
    SELECT
        CAST(AssignedUserId AS VARCHAR(64)) AS UserId,
        COUNT_BIG(*) AS LeadsAssigned,
        SUM(CASE WHEN CreatedUtc >= DATEADD(DAY, -7,  GETUTCDATE()) THEN 1 ELSE 0 END) AS LeadsLast7,
        SUM(CASE WHEN CreatedUtc >= DATEADD(DAY, -30, GETUTCDATE()) THEN 1 ELSE 0 END) AS LeadsLast30
    FROM fub.People
    WHERE AssignedUserId IS NOT NULL
    GROUP BY CAST(AssignedUserId AS VARCHAR(64))
),

agent_events AS (
    SELECT
        CAST(P.AssignedUserId AS VARCHAR(64)) AS UserId,
        COUNT_BIG(*) AS EventsTotal,
        SUM(CASE WHEN ISNULL(E.OccurredUtc, E.CreatedUtc) >= DATEADD(DAY, -7, GETUTCDATE())
                 THEN 1 ELSE 0 END) AS EventsLast7
    FROM fub.Events E
    JOIN fub.People P ON P.PersonId = E.PersonId
    WHERE P.AssignedUserId IS NOT NULL
    GROUP BY CAST(P.AssignedUserId AS VARCHAR(64))
),

agent_deals AS (
    SELECT
        D.PrimaryUserId AS UserId,
        COUNT_BIG(*) AS DealsTotal,
        SUM(CASE WHEN S.ClosedStage = 1 THEN 1 ELSE 0 END) AS DealsClosed,
        SUM(CASE WHEN ISNULL(S.ClosedStage, 0) = 0 THEN ISNULL(D.Price, 0) ELSE 0 END) AS PipelineValueOpen,
        SUM(CASE WHEN S.ClosedStage = 1 THEN ISNULL(D.Price, 0) ELSE 0 END) AS PipelineValueClosed
    FROM fub.Deals D
    LEFT JOIN fub.Stages S ON S.StageId = D.StageId AND S.StageKind = 'Deal'
    WHERE D.PrimaryUserId IS NOT NULL AND D.PrimaryUserId <> ''
    GROUP BY D.PrimaryUserId
)

SELECT
    ISNULL(AP.UserId, ISNULL(AE.UserId, AD.UserId)) AS UserId,
    ISNULL(AP.LeadsAssigned, 0)       AS LeadsAssigned,
    ISNULL(AP.LeadsLast7, 0)          AS LeadsLast7,
    ISNULL(AP.LeadsLast30, 0)         AS LeadsLast30,
    ISNULL(AE.EventsTotal, 0)         AS EventsTotal,
    ISNULL(AE.EventsLast7, 0)         AS EventsLast7,
    ISNULL(AD.DealsTotal, 0)          AS DealsTotal,
    ISNULL(AD.DealsClosed, 0)         AS DealsClosed,
    ISNULL(AD.PipelineValueOpen, 0)   AS PipelineValueOpen,
    ISNULL(AD.PipelineValueClosed, 0) AS PipelineValueClosed
FROM      agent_people AP
FULL JOIN agent_events AE ON AE.UserId = AP.UserId
FULL JOIN agent_deals  AD ON AD.UserId = ISNULL(AP.UserId, AE.UserId);
GO

/*
Example (with names):
    SELECT U.Name, LB.LeadsLast30, LB.EventsLast7, LB.DealsTotal,
           LB.DealsClosed, LB.PipelineValueOpen
    FROM fub.vw_AgentLeaderboard LB
    LEFT JOIN fub.Users U ON U.UserId = LB.UserId
    ORDER BY LB.LeadsAssigned DESC;
*/
