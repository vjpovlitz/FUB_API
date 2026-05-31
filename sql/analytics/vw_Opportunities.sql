/*
============================================================================
analytics.vw_Opportunities — cross-system deal/opportunity grain

UNION of ghl.Opportunities + fub.Deals into one normalized opportunity row
with a SourceSystem discriminator. The Pipeline page reads THIS, never the
per-CRM tables — vendor-neutral, product-portable.

Status normalization (the two CRMs model lifecycle differently):
  GHL: Status in (open|won|lost) -> Open|Won|Lost.
  FUB: NO won/lost status — a deal is Won when its stage maps to a
       fub.Stages row with ClosedStage = 1, otherwise Open. (No Lost in FUB.)

Value: GHL MonetaryValue / FUB Price, both -> DECIMAL(18,2).

Depends on BOTH ghl.* and fub.* — applied separately (see vw_AllContacts).

Columns:
    OpportunityId, SourceSystem, Name, Pipeline, Stage, Status, Value,
    AssignedUserId, AssignedAgent, CreatedUtc, ClosedUtc
============================================================================
*/

IF SCHEMA_ID('analytics') IS NULL EXEC('CREATE SCHEMA analytics');
GO

IF OBJECT_ID('analytics.vw_Opportunities', 'V') IS NOT NULL
    DROP VIEW analytics.vw_Opportunities;
GO

CREATE VIEW analytics.vw_Opportunities AS
SELECT
    CAST(O.OpportunityId AS VARCHAR(64))           AS OpportunityId,
    CAST('GoHighLevel' AS VARCHAR(32))             AS SourceSystem,
    CAST(O.Name AS NVARCHAR(256))                  AS Name,
    CAST(ISNULL(P.Name, '(none)') AS NVARCHAR(128)) AS Pipeline,
    CAST(ISNULL(S.Name, '(none)') AS NVARCHAR(128)) AS Stage,
    CAST(CASE LOWER(O.Status)
            WHEN 'won'  THEN 'Won'
            WHEN 'lost' THEN 'Lost'
            ELSE 'Open' END AS VARCHAR(16))        AS Status,
    CAST(ISNULL(O.MonetaryValue, 0) AS DECIMAL(18,2)) AS Value,
    CAST(O.AssignedToUserId AS VARCHAR(64))        AS AssignedUserId,
    CAST(U.FullName AS NVARCHAR(256))              AS AssignedAgent,
    CAST(O.DateAddedUtc  AS DATETIME2(3))          AS CreatedUtc,
    CAST(O.DateClosedUtc AS DATETIME2(3))          AS ClosedUtc
FROM ghl.Opportunities O
LEFT JOIN ghl.Pipelines      P ON P.PipelineId = O.PipelineId
LEFT JOIN ghl.PipelineStages S ON S.PipelineStageId = O.PipelineStageId
LEFT JOIN ghl.Users          U ON U.UserId = O.AssignedToUserId

UNION ALL

SELECT
    CAST(D.DealId AS VARCHAR(64))                  AS OpportunityId,
    CAST('FollowUpBoss' AS VARCHAR(32))            AS SourceSystem,
    CAST(D.Name AS NVARCHAR(256))                  AS Name,
    CAST(ISNULL(NULLIF(D.PipelineName,''), '(none)') AS NVARCHAR(128)) AS Pipeline,
    CAST(ISNULL(NULLIF(D.StageName,''), '(none)') AS NVARCHAR(128))    AS Stage,
    CAST(CASE WHEN ST.ClosedStage = 1 THEN 'Won' ELSE 'Open' END AS VARCHAR(16)) AS Status,
    CAST(ISNULL(D.Price, 0) AS DECIMAL(18,2))      AS Value,
    CAST(D.PrimaryUserId AS VARCHAR(64))           AS AssignedUserId,
    CAST(ISNULL(NULLIF(U.Name,''), D.UserNames) AS NVARCHAR(256)) AS AssignedAgent,
    CAST(D.CreatedUtc AS DATETIME2(3))             AS CreatedUtc,
    CAST(CASE WHEN ST.ClosedStage = 1 THEN D.EnteredStageUtc ELSE NULL END AS DATETIME2(3)) AS ClosedUtc
FROM fub.Deals D
LEFT JOIN fub.Stages ST ON ST.StageId = D.StageId AND ST.StageKind = 'Deal'
LEFT JOIN fub.Users  U  ON CAST(U.UserId AS VARCHAR(64)) = D.PrimaryUserId;
GO

/*
Smoke query:
    SELECT SourceSystem, Status, COUNT(*) Opps, SUM(Value) TotalValue
    FROM analytics.vw_Opportunities GROUP BY SourceSystem, Status;
*/
