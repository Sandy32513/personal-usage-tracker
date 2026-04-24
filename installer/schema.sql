-- Personal Usage Tracker V3 - SQL Server Schema
-- Creates database, tables, indexes, and stored procedures
-- Run this in SQL Server Management Studio (SSMS)

PRINT '========================================'
PRINT 'Personal Usage Tracker V3 - Schema Setup'
PRINT '========================================'
PRINT ''

-- ============================================
-- 1. CREATE DATABASE
-- ============================================
IF NOT EXISTS (SELECT name FROM sys.databases WHERE name = 'UsageTracker')
BEGIN
    PRINT '[1/5] Creating database UsageTracker...'
    CREATE DATABASE UsageTracker
    PRINT '    Database created.'
END
ELSE
BEGIN
    PRINT '[1/5] Database UsageTracker already exists.'
END
GO

USE UsageTracker
GO

PRINT ''
PRINT '[2/5] Creating tables...'

-- ============================================
-- 2. MAIN EVENTS TABLE
-- ============================================
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[events]') AND type in (N'U'))
BEGIN
    CREATE TABLE [dbo].[events] (
        [id] BIGINT IDENTITY(1,1) PRIMARY KEY,
        [type] NVARCHAR(20) NOT NULL,              -- 'app' or 'web'
        [app_name] NVARCHAR(255) NULL,             -- Application name (e.g., 'chrome.exe')
        [window_title] NVARCHAR(1000) NULL,        -- Window title (for app events)
        [url] NVARCHAR(2000) NULL,                 -- URL (for web events)
        [title] NVARCHAR(1000) NULL,               -- Page title (for web events)
        [timestamp] DATETIME2 NOT NULL,            -- When event occurred (UTC)
        [duration_seconds] INT DEFAULT 0,          -- Duration if available
        [created_at] DATETIME2 DEFAULT GETDATE(),  -- Record creation time
        CONSTRAINT [chk_event_type] CHECK ([type] IN ('app', 'web'))
    )
    PRINT '    Table [events] created.'
END
ELSE
BEGIN
    PRINT '    Table [events] already exists.'
END
GO

-- ============================================
-- 3. INDEXES FOR PERFORMANCE
-- ============================================
PRINT ''
PRINT '[3/5] Creating indexes...'

-- Main time-based index for queries
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_events_timestamp' AND object_id = OBJECT_ID('events'))
BEGIN
    CREATE INDEX [IX_events_timestamp] ON [dbo].[events]([timestamp] DESC)
    PRINT '    Index [IX_events_timestamp] created.'
END

-- Index for app-based queries
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_events_app_name' AND object_id = OBJECT_ID('events'))
BEGIN
    CREATE INDEX [IX_events_app_name] ON [dbo].[events]([app_name])
    PRINT '    Index [IX_events_app_name] created.'
END

-- Index for type queries
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_events_type' AND object_id = OBJECT_ID('events'))
BEGIN
    CREATE INDEX [IX_events_type] ON [dbo].[events]([type])
    PRINT '    Index [IX_events_type] created.'
END

-- Composite index for common queries
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_events_type_timestamp' AND object_id = OBJECT_ID('events'))
BEGIN
    CREATE INDEX [IX_events_type_timestamp] ON [dbo].[events]([type], [timestamp] DESC)
    PRINT '    Index [IX_events_type_timestamp] created.'
END

-- Covering index for app usage reports
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_events_app_covering' AND object_id = OBJECT_ID('events'))
BEGIN
    CREATE INDEX [IX_events_app_covering] ON [dbo].[events]([type], [app_name], [timestamp] DESC)
        INCLUDE ([window_title], [duration_seconds])
    PRINT '    Index [IX_events_app_covering] created.'
END

-- Covering index for web usage reports
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_events_web_covering' AND object_id = OBJECT_ID('events'))
BEGIN
    CREATE INDEX [IX_events_web_covering] ON [dbo].[events]([type], [timestamp] DESC)
        INCLUDE ([url], [title], [duration_seconds])
    PRINT '    Index [IX_events_web_covering] created.'
END
GO

-- ============================================
-- 4. STORED PROCEDURES
-- ============================================
PRINT ''
PRINT '[4/5] Creating stored procedures...'

-- Get app usage statistics
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[sp_GetAppUsageStats]') AND type in (N'P'))
BEGIN
    EXEC('
    CREATE PROCEDURE [dbo].[sp_GetAppUsageStats]
        @Days INT = 7
    AS
    BEGIN
        SET NOCOUNT ON;
        
        SELECT 
            app_name,
            COUNT(*) as session_count,
            SUM(ISNULL(duration_seconds, 0)) as total_seconds,
            AVG(ISNULL(duration_seconds, 0)) as avg_seconds,
            MIN([timestamp]) as first_seen,
            MAX([timestamp]) as last_seen
        FROM [dbo].[events]
        WHERE [type] = ''app''
          AND [timestamp] >= DATEADD(day, -@Days, GETDATE())
        GROUP BY app_name
        ORDER BY total_seconds DESC;
    END
    ')
    PRINT '    Procedure [sp_GetAppUsageStats] created.'
END

-- Get top websites
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[sp_GetTopWebsites]') AND type in (N'P'))
BEGIN
    EXEC('
    CREATE PROCEDURE [dbo].[sp_GetTopWebsites]
        @Days INT = 7,
        @TopN INT = 20
    AS
    BEGIN
        SET NOCOUNT ON;
        
        SELECT TOP (@TopN)
            url,
            COUNT(*) as visit_count,
            SUM(ISNULL(duration_seconds, 0)) as total_seconds,
            MAX([timestamp]) as last_visit
        FROM [dbo].[events]
        WHERE [type] = ''web''
          AND [timestamp] >= DATEADD(day, -@Days, GETDATE())
        GROUP BY url
        ORDER BY visit_count DESC;
    END
    ')
    PRINT '    Procedure [sp_GetTopWebsites] created.'
END

-- Get daily summary
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[sp_GetDailySummary]') AND type in (N'P'))
BEGIN
    EXEC('
    CREATE PROCEDURE [dbo].[sp_GetDailySummary]
        @Days INT = 30
    AS
    BEGIN
        SET NOCOUNT ON;
        
        SELECT 
            CAST([timestamp] AS DATE) as date,
            [type],
            COUNT(*) as event_count,
            COUNT(DISTINCT app_name) as unique_apps,
            COUNT(DISTINCT url) as unique_urls
        FROM [dbo].[events]
        WHERE [timestamp] >= DATEADD(day, -@Days, GETDATE())
        GROUP BY CAST([timestamp] AS DATE), [type]
        ORDER BY date DESC;
    END
    ')
    PRINT '    Procedure [sp_GetDailySummary] created.'
END

-- Clean old data (archive/purge)
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[sp_CleanOldData]') AND type in (N'P'))
BEGIN
    EXEC('
    CREATE PROCEDURE [dbo].[sp_CleanOldData]
        @RetentionDays INT = 90
    AS
    BEGIN
        SET NOCOUNT ON;
        
        DELETE FROM [dbo].[events]
        WHERE [timestamp] < DATEADD(day, -@RetentionDays, GETDATE());
        
        SELECT @@ROWCOUNT as rows_deleted;
    END
    ')
    PRINT '    Procedure [sp_CleanOldData] created.'
END
GO

-- ============================================
-- 5. CREATE USER AND GRANT PERMISSIONS
-- ============================================
PRINT ''
PRINT '[5/5] Setting up database user and permissions...'

-- Note: Uncomment and modify these lines if you need a dedicated SQL user
/*
IF NOT EXISTS (SELECT * FROM sys.database_principals WHERE name = 'usage_tracker_user')
BEGIN
    CREATE USER [usage_tracker_user] FOR LOGIN [usage_tracker_user]
    PRINT '    User [usage_tracker_user] created.'
END

-- Grant permissions
EXEC sp_addrolemember ''db_datawriter'', ''usage_tracker_user''
EXEC sp_addrolemember ''db_datareader'', ''usage_tracker_user''
PRINT '    Permissions granted to [usage_tracker_user].'
*/
PRINT '    Note: SQL authentication should be configured in app/config.py'
PRINT '    Or use Windows Authentication (Trusted_Connection=yes)'
GO

-- ============================================
-- FINAL SUMMARY
-- ============================================
PRINT ''
PRINT '========================================'
PRINT 'SCHEMA SETUP COMPLETE!'
PRINT '========================================'
PRINT ''
PRINT 'Database: UsageTracker'
PRINT 'Tables:    events (with 4 covering indexes)'
PRINT 'Procs:     sp_GetAppUsageStats, sp_GetTopWebsites, sp_GetDailySummary, sp_CleanOldData'
PRINT ''
PRINT 'Next steps:'
PRINT '  1. Update app/config.py with your SQL Server credentials'
PRINT '  2. If using SQL Auth: Create login and user in SQL Server'
PRINT '  3. Test connection: python -m app.main run --debug'
PRINT ''
PRINT 'Sample SQL Auth user creation (run as sysadmin):'
PRINT '  CREATE LOGIN usage_tracker_user WITH PASSWORD = ''YourSecurePassword123!'''
PRINT '  USE UsageTracker'
PRINT '  CREATE USER usage_tracker_user FOR LOGIN usage_tracker_user'
PRINT '  ALTER ROLE db_datareader ADD MEMBER usage_tracker_user'
PRINT '  ALTER ROLE db_datawriter ADD MEMBER usage_tracker_user'
PRINT ''