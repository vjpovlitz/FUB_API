/*
============================================================================
fub.vw_DealsByStage — deal pipeline rollup by stage

One row per deal stage (joined to the deal-pipeline rows in fub.Stages so we
get OrderWeight for funnel ordering + the ClosedStage flag). FUB has no
won/lost deal status, so the pipeline stage IS the lifecycle.

    DealCount         deals currently in the stage
    TotalValue        sum(Price)
    AvgValue          avg(Price) over deals with a price
    IsClosedStage     1 if this stage is a closed/terminal stage
============================================================================
*/

IF OBJECT_ID('fub.vw_DealsByStage', 'V') IS NOT NULL
    DROP VIEW fub.vw_DealsByStage;
GO

CREATE VIEW fub.vw_DealsByStage AS
SELECT
    D.StageId,
    ISNULL(NULLIF(D.StageName, ''), S.Name)        AS StageName,
    D.PipelineId,
    ISNULL(S.OrderWeight, 999999)                  AS StageOrder,
    ISNULL(S.ClosedStage, 0)                       AS IsClosedStage,
    COUNT_BIG(*)                                   AS DealCount,
    SUM(ISNULL(D.Price, 0))                        AS TotalValue,
    AVG(CASE WHEN D.Price IS NOT NULL THEN D.Price END) AS AvgValue
FROM       fub.Deals  D
LEFT JOIN  fub.Stages S ON S.StageId = D.StageId AND S.StageKind = 'Deal'
GROUP BY
    D.StageId,
    ISNULL(NULLIF(D.StageName, ''), S.Name),
    D.PipelineId,
    ISNULL(S.OrderWeight, 999999),
    ISNULL(S.ClosedStage, 0);
GO

/*
Smoke query:
    SELECT * FROM fub.vw_DealsByStage ORDER BY StageOrder;
*/
