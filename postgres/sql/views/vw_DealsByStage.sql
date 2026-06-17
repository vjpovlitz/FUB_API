-- Postgres port of sql/views/vw_DealsByStage.sql
-- fub.vw_DealsByStage — deal pipeline rollup by stage.
-- IsClosedStage kept as 0/1 INT (BIT contract) via CASE over the BOOLEAN column.

CREATE OR REPLACE VIEW fub.vw_DealsByStage AS
SELECT
    d."StageId",
    COALESCE(NULLIF(d."StageName", ''), s."Name")  AS "StageName",
    d."PipelineId",
    COALESCE(s."OrderWeight", 999999)              AS "StageOrder",
    CASE WHEN COALESCE(s."ClosedStage", FALSE) THEN 1 ELSE 0 END AS "IsClosedStage",
    COUNT(*)                                       AS "DealCount",
    SUM(COALESCE(d."Price", 0))                    AS "TotalValue",
    AVG(CASE WHEN d."Price" IS NOT NULL THEN d."Price" END) AS "AvgValue"
FROM      fub."Deals"  d
LEFT JOIN fub."Stages" s ON s."StageId" = CAST(d."StageId" AS VARCHAR(64)) AND s."StageKind" = 'Deal'
GROUP BY
    d."StageId",
    COALESCE(NULLIF(d."StageName", ''), s."Name"),
    d."PipelineId",
    COALESCE(s."OrderWeight", 999999),
    CASE WHEN COALESCE(s."ClosedStage", FALSE) THEN 1 ELSE 0 END;
