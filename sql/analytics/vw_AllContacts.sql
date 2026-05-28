/*
============================================================================
analytics.vw_AllContacts — cross-system unified contact list

UNION of ghl.Contacts + fub.People into one normalized shape with a
SourceSystem discriminator. This is the proof that the multi-source warehouse
design works: one view spanning both CRMs, queryable + joinable downstream.

Lives in the `analytics` schema (created here if missing) — kept separate from
both source schemas. This view depends on BOTH ghl.* and fub.* existing in the
shared dcr_warehouse, so it is applied separately from the FUB loader's own
fub.vw_* views (which depend only on fub.*).

Normalized columns:
    ContactId      source PK (GHL ContactId / FUB PersonId)
    SourceSystem   'GoHighLevel' | 'FollowUpBoss'
    FullName, Email, Phone, Source, DateAddedUtc
============================================================================
*/

IF SCHEMA_ID('analytics') IS NULL EXEC('CREATE SCHEMA analytics');
GO

IF OBJECT_ID('analytics.vw_AllContacts', 'V') IS NOT NULL
    DROP VIEW analytics.vw_AllContacts;
GO

CREATE VIEW analytics.vw_AllContacts AS
SELECT
    CAST(ContactId   AS VARCHAR(64))   AS ContactId,
    CAST(SourceSystem AS VARCHAR(32))  AS SourceSystem,
    CAST(FullName    AS NVARCHAR(256)) AS FullName,
    CAST(Email       AS NVARCHAR(256)) AS Email,
    CAST(Phone       AS VARCHAR(64))   AS Phone,
    CAST(Source      AS NVARCHAR(128)) AS Source,
    CAST(DateAddedUtc AS DATETIME2(3)) AS DateAddedUtc
FROM ghl.Contacts

UNION ALL

SELECT
    CAST(PersonId     AS VARCHAR(64))   AS ContactId,
    CAST(SourceSystem AS VARCHAR(32))   AS SourceSystem,
    CAST(Name         AS NVARCHAR(256)) AS FullName,
    CAST(PrimaryEmail AS NVARCHAR(256)) AS Email,
    CAST(PrimaryPhone AS VARCHAR(64))   AS Phone,
    CAST(Source       AS NVARCHAR(128)) AS Source,
    CAST(CreatedUtc   AS DATETIME2(3))  AS DateAddedUtc
FROM fub.People;
GO

/*
Smoke query:
    SELECT SourceSystem, COUNT(*) AS Contacts
    FROM analytics.vw_AllContacts
    GROUP BY SourceSystem;
*/
