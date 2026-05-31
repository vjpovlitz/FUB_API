/*
============================================================================
analytics.vw_Activity — cross-system activity stream

One normalized row per activity across both CRMs, so the Activity page is
vendor-neutral (product-portable). Unions:
  FUB:  Calls, Notes, Tasks, Events
  GHL:  ConversationMessages (Message), Appointments

Normalized grain:
    ActivityId, SourceSystem, ActivityType, Direction, PersonId,
    UserId, AgentName, Outcome, DurationSec, OccurredUtc

ActivityType in (Call, Note, Task, Event, Message, Appointment).
UserId '-1' = FUB system/automation (no Users row). Depends on BOTH ghl.* and
fub.* — applied separately (see vw_AllContacts).
============================================================================
*/

IF SCHEMA_ID('analytics') IS NULL EXEC('CREATE SCHEMA analytics');
GO

IF OBJECT_ID('analytics.vw_Activity', 'V') IS NOT NULL
    DROP VIEW analytics.vw_Activity;
GO

CREATE VIEW analytics.vw_Activity AS
-- FUB calls --------------------------------------------------------------
SELECT
    CAST(C.CallId AS VARCHAR(64))                  AS ActivityId,
    CAST('FollowUpBoss' AS VARCHAR(32))            AS SourceSystem,
    CAST('Call' AS VARCHAR(24))                    AS ActivityType,
    CAST(CASE WHEN C.IsIncoming = 1 THEN 'Inbound' ELSE 'Outbound' END AS VARCHAR(16)) AS Direction,
    CAST(C.PersonId AS VARCHAR(64))                AS PersonId,
    CAST(C.UserId AS VARCHAR(64))                  AS UserId,
    CAST(NULLIF(C.UserName,'') AS NVARCHAR(256))   AS AgentName,
    CAST(ISNULL(NULLIF(C.Outcome,''),'(unknown)') AS NVARCHAR(64)) AS Outcome,
    CAST(ISNULL(C.Duration,0) AS INT)              AS DurationSec,
    CAST(ISNULL(C.StartedAtUtc, C.CreatedUtc) AS DATETIME2(3)) AS OccurredUtc
FROM fub.Calls C

UNION ALL
-- FUB notes --------------------------------------------------------------
SELECT
    CAST(N.NoteId AS VARCHAR(64)), CAST('FollowUpBoss' AS VARCHAR(32)),
    CAST('Note' AS VARCHAR(24)), CAST('' AS VARCHAR(16)),
    CAST(N.PersonId AS VARCHAR(64)), CAST(N.CreatedById AS VARCHAR(64)),
    CAST(NULLIF(N.CreatedBy,'') AS NVARCHAR(256)),
    CAST(ISNULL(NULLIF(N.Type,''),'Note') AS NVARCHAR(64)),
    CAST(0 AS INT), CAST(N.CreatedUtc AS DATETIME2(3))
FROM fub.Notes N

UNION ALL
-- FUB tasks --------------------------------------------------------------
SELECT
    CAST(T.TaskId AS VARCHAR(64)), CAST('FollowUpBoss' AS VARCHAR(32)),
    CAST('Task' AS VARCHAR(24)), CAST('' AS VARCHAR(16)),
    CAST(T.PersonId AS VARCHAR(64)), CAST(T.AssignedUserId AS VARCHAR(64)),
    CAST(NULLIF(T.AssignedTo,'') AS NVARCHAR(256)),
    CAST(CASE WHEN T.IsCompleted = 1 THEN 'Completed'
              WHEN T.DueDateTimeUtc < GETUTCDATE() THEN 'Missed'
              ELSE 'Open' END AS NVARCHAR(64)),
    CAST(0 AS INT), CAST(T.CreatedUtc AS DATETIME2(3))
FROM fub.Tasks T

UNION ALL
-- FUB events -------------------------------------------------------------
SELECT
    CAST(E.EventId AS VARCHAR(64)), CAST('FollowUpBoss' AS VARCHAR(32)),
    CAST('Event' AS VARCHAR(24)), CAST('' AS VARCHAR(16)),
    CAST(E.PersonId AS VARCHAR(64)), CAST('' AS VARCHAR(64)),
    CAST(NULL AS NVARCHAR(256)),
    CAST(ISNULL(NULLIF(E.Type,''),'Event') AS NVARCHAR(64)),
    CAST(0 AS INT), CAST(ISNULL(E.OccurredUtc, E.CreatedUtc) AS DATETIME2(3))
FROM fub.Events E

UNION ALL
-- GHL conversation messages ---------------------------------------------
SELECT
    CAST(M.MessageId AS VARCHAR(64)), CAST('GoHighLevel' AS VARCHAR(32)),
    CAST('Message' AS VARCHAR(24)),
    CAST(CASE LOWER(M.Direction) WHEN 'inbound' THEN 'Inbound'
              WHEN 'outbound' THEN 'Outbound' ELSE '' END AS VARCHAR(16)),
    CAST(M.ContactId AS VARCHAR(64)), CAST('' AS VARCHAR(64)),
    CAST(NULL AS NVARCHAR(256)),
    CAST(ISNULL(NULLIF(M.MessageType,''),'Message') AS NVARCHAR(64)),
    CAST(0 AS INT), CAST(M.DateAddedUtc AS DATETIME2(3))
FROM ghl.ConversationMessages M

UNION ALL
-- GHL appointments -------------------------------------------------------
SELECT
    CAST(A.AppointmentId AS VARCHAR(64)), CAST('GoHighLevel' AS VARCHAR(32)),
    CAST('Appointment' AS VARCHAR(24)), CAST('' AS VARCHAR(16)),
    CAST(A.ContactId AS VARCHAR(64)), CAST(A.AssignedToUserId AS VARCHAR(64)),
    CAST(U.FullName AS NVARCHAR(256)),
    CAST(ISNULL(NULLIF(A.AppointmentStatus,''),'(unknown)') AS NVARCHAR(64)),
    CAST(0 AS INT), CAST(ISNULL(A.StartTimeUtc, A.DateAddedUtc) AS DATETIME2(3))
FROM ghl.Appointments A
LEFT JOIN ghl.Users U ON U.UserId = A.AssignedToUserId;
GO

/*
Smoke query:
    SELECT SourceSystem, ActivityType, COUNT(*) N
    FROM analytics.vw_Activity GROUP BY SourceSystem, ActivityType ORDER BY N DESC;
*/
