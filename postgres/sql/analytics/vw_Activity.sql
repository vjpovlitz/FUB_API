-- Postgres port of sql/analytics/vw_Activity.sql
-- analytics.vw_Activity — cross-system activity stream (FUB Calls/Notes/Tasks/
-- Events + GHL Messages/Appointments). Booleans (IsIncoming/IsCompleted) compared
-- directly; GETUTCDATE -> now() AT TIME ZONE 'utc'. Depends on ghl.* and fub.*.

CREATE SCHEMA IF NOT EXISTS analytics;

CREATE OR REPLACE VIEW analytics.vw_Activity AS
-- FUB calls --------------------------------------------------------------
SELECT
    CAST(c."CallId" AS VARCHAR(64))                AS "ActivityId",
    CAST('FollowUpBoss' AS VARCHAR(32))            AS "SourceSystem",
    CAST('Call' AS VARCHAR(24))                    AS "ActivityType",
    CAST(CASE WHEN c."IsIncoming" THEN 'Inbound' ELSE 'Outbound' END AS VARCHAR(16)) AS "Direction",
    CAST(c."PersonId" AS VARCHAR(64))              AS "PersonId",
    CAST(c."UserId" AS VARCHAR(64))                AS "UserId",
    CAST(NULLIF(c."UserName",'') AS VARCHAR(256))  AS "AgentName",
    CAST(COALESCE(NULLIF(c."Outcome",''),'(unknown)') AS VARCHAR(64)) AS "Outcome",
    CAST(COALESCE(c."Duration",0) AS INT)          AS "DurationSec",
    CAST(COALESCE(c."StartedAtUtc", c."CreatedUtc") AS TIMESTAMP(3)) AS "OccurredUtc"
FROM fub."Calls" c

UNION ALL
-- FUB notes --------------------------------------------------------------
SELECT
    CAST(n."NoteId" AS VARCHAR(64)), CAST('FollowUpBoss' AS VARCHAR(32)),
    CAST('Note' AS VARCHAR(24)), CAST('' AS VARCHAR(16)),
    CAST(n."PersonId" AS VARCHAR(64)), CAST(n."CreatedById" AS VARCHAR(64)),
    CAST(NULLIF(n."CreatedBy",'') AS VARCHAR(256)),
    CAST(COALESCE(NULLIF(n."Type",''),'Note') AS VARCHAR(64)),
    CAST(0 AS INT), CAST(n."CreatedUtc" AS TIMESTAMP(3))
FROM fub."Notes" n

UNION ALL
-- FUB tasks --------------------------------------------------------------
SELECT
    CAST(t."TaskId" AS VARCHAR(64)), CAST('FollowUpBoss' AS VARCHAR(32)),
    CAST('Task' AS VARCHAR(24)), CAST('' AS VARCHAR(16)),
    CAST(t."PersonId" AS VARCHAR(64)), CAST(t."AssignedUserId" AS VARCHAR(64)),
    CAST(NULLIF(t."AssignedTo",'') AS VARCHAR(256)),
    CAST(CASE WHEN t."IsCompleted" THEN 'Completed'
              WHEN t."DueDateTimeUtc" < (now() AT TIME ZONE 'utc') THEN 'Missed'
              ELSE 'Open' END AS VARCHAR(64)),
    CAST(0 AS INT), CAST(t."CreatedUtc" AS TIMESTAMP(3))
FROM fub."Tasks" t

UNION ALL
-- FUB events -------------------------------------------------------------
SELECT
    CAST(e."EventId" AS VARCHAR(64)), CAST('FollowUpBoss' AS VARCHAR(32)),
    CAST('Event' AS VARCHAR(24)), CAST('' AS VARCHAR(16)),
    CAST(e."PersonId" AS VARCHAR(64)), CAST('' AS VARCHAR(64)),
    CAST(NULL AS VARCHAR(256)),
    CAST(COALESCE(NULLIF(e."Type",''),'Event') AS VARCHAR(64)),
    CAST(0 AS INT), CAST(COALESCE(e."OccurredUtc", e."CreatedUtc") AS TIMESTAMP(3))
FROM fub."Events" e

UNION ALL
-- GHL conversation messages ---------------------------------------------
SELECT
    CAST(m."MessageId" AS VARCHAR(64)), CAST('GoHighLevel' AS VARCHAR(32)),
    CAST('Message' AS VARCHAR(24)),
    CAST(CASE lower(m."Direction") WHEN 'inbound' THEN 'Inbound'
              WHEN 'outbound' THEN 'Outbound' ELSE '' END AS VARCHAR(16)),
    CAST(m."ContactId" AS VARCHAR(64)), CAST('' AS VARCHAR(64)),
    CAST(NULL AS VARCHAR(256)),
    CAST(COALESCE(NULLIF(m."MessageType",''),'Message') AS VARCHAR(64)),
    CAST(0 AS INT), CAST(m."DateAddedUtc" AS TIMESTAMP(3))
FROM ghl."ConversationMessages" m

UNION ALL
-- GHL appointments -------------------------------------------------------
SELECT
    CAST(a."AppointmentId" AS VARCHAR(64)), CAST('GoHighLevel' AS VARCHAR(32)),
    CAST('Appointment' AS VARCHAR(24)), CAST('' AS VARCHAR(16)),
    CAST(a."ContactId" AS VARCHAR(64)), CAST(a."AssignedToUserId" AS VARCHAR(64)),
    CAST(u."FullName" AS VARCHAR(256)),
    CAST(COALESCE(NULLIF(a."AppointmentStatus",''),'(unknown)') AS VARCHAR(64)),
    CAST(0 AS INT), CAST(COALESCE(a."StartTimeUtc", a."DateAddedUtc") AS TIMESTAMP(3))
FROM ghl."Appointments" a
LEFT JOIN ghl."Users" u ON u."UserId" = a."AssignedToUserId";
