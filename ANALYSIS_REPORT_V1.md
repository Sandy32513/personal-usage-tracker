# Personal Usage Tracker V3 — End-to-End Technical Analysis Report (V1)

> **Report Version**: 3.0.1  
> **Analysis Date**: 2026-04-18  
> **Repository**: https://github.com/Sandy32513/personal-usage-tracker  
> **Analysis Scope**: Complete codebase audit from multi-perspective view

---

## Table of Contents

1. [Project Essence](#1-project-essence)
2. [Structural Blueprint](#2-structural-blueprint)
3. [Modular Decomposition](#3-modular-decomposition)
4. [Engineering Trade-offs](#4-engineering-trade-offs)
5. [Reconstruction Guide](#5-reconstruction-guide)

---

## 1. Project Essence

### 1.1 Core Purpose

**Personal Usage Tracker V3** is a Windows desktop telemetry pipeline designed to:

| Goal | Implementation |
|------|-------------|
| Capture foreground application usage | `AppTracker` polls active window every 5 seconds |
| Extract browser history | `BrowserTracker` copies and queries Chrome SQLite DB |
| Ensure zero data loss | `PersistentQueue` buffers events in SQLite |
| Store in enterprise database | SQL Server via ODBC |
| Export for analysis | Daily gzip-compressed CSV files |

### 1.2 Business Logic

```
User Goal → System Behavior → Data Flow → Output
─────────────────────────────────────────────
"Track my productivity" → Capture active apps → Queue → SQL → CSV reports
"Know my browsing" → Extract Chrome history → Queue → SQL → CSV reports  
"Ensure no data loss" → Persistent queue with retry → SQL → N/A
```

### 1.3 User Goals Satisfied

| User Goal | System Answer |
|----------|---------------|
| What apps do I use? | Foreground window capture |
| What websites do I visit? | Chrome history extraction |
| Is my data safe? | SQLite persistent queue |
| Can I run reports? | CSV export with compression |
| Does it run automatically? | Windows Service |

---

## 2. Structural Blueprint

### 2.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PERSONAL USAGE TRACKER V3                          │
│                   (Windows Service / Console)                        │
└────────────────────────────────────┬──────────────────────────────┬────┘
                                     │                           │
     ┌───────────────────────────────┐  │  ┌────────────────────────┐   │
     │   APP TRACKER (5 sec)        │  │  │ BROWSER TRACKER (30 sec) │   │
     │   psutil + win32gui          │  │  │ Chrome DB copy       │   │
     └─────────────┬───────────────┘  │  └──────────┬───────────┘   │
                   │                 │             │               │
                   └─────────────────┼─────────────┘               │
                                     ▼                             │
                    ┌────────────────────────┐                    │
                    │   PERSISTENT QUEUE     │                    │
                    │   (SQLite + WAL)     │                    │
                    │   Max 1M events      │                    │
                    └──────────┬──────────┘                    │
                               │                                │
                    ┌──────────▼──────────┐                  │
                    │  PROCESSOR WORKER  │                  │
                    │  Multi-worker      │                  │
                    │  Circuit Breaker   │                  │
                    └──────────┬──────────┘                  │
                               │                              │
                    ┌──────────▼──────────┐                  │
                    │  SQL SERVER DB      │ ◄──────────────────┘
                    │  (ODBC + pooling)  │
                    └──────────┬──────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                      ▼
  ┌──────────┐         ┌──────────┐          ┌──────────┐
  │ EVENTS   │         │  STORED  │          │   CSV    │
  │ TABLE    │         │  PROCS   │          │ EXPORT   │
  └──────────┘         └──────────┘          └──────────┘
```

### 2.2 Execution Conditions

| Requirement | Version | Notes |
|--------------|---------|-------|
| Windows | 10/11 (64-bit) | Required - Win32 APIs |
| Python | 3.9+ | For development only |
| SQL Server | 2016+ | Express or Standard |
| ODBC Driver | 17 | For SQL Server |
| Chrome | Latest | Browser tracking |

### 2.3 Folder Hierarchy

```
personal-usage-tracker/
├── v1/                          # Deprecated version
│   ├── README.md               # Deprecation notice
│   ├── app/                   # Original code
│   └── installer/            # Original installers
├── v2/                          # Developmental version
│   ├── README.md               # Dev warnings
│   ├── app/                   # Partial fixes
│   └── installer/
├── v3/                          # Production version (RECOMMENDED)
│   ├── README.md              # Production docs
│   ├── CHANGELOG.md          # Version history
│   ├── app/
│   │   ├── __init__.py
│   │   ├── config.py         # Central config (160 lines)
│   │   ├── config_watcher.py # Hot-reload (155 lines)
│   │   ├── health.py        # HTTP health (181 lines)
│   │   ├── main.py         # Entry point (268 lines)
│   │   ├── validation.py   # Validation (346 lines)
│   │   ├── db/
│   │   │   └── sqlserver.py # SQL handler (271 lines)
│   │   ├── exporter/
│   │   │   ├── csv_exporter.py  # CSV export (243 lines)
│   │   │   └── export_task.py   # Standalone (64 lines)
│   │   ├── processor/
│   │   │   └── worker.py       # Queue processor (259 lines)
│   │   ├── queue/
│   │   │   └── queue_db.py     # SQLite queue (438 lines)
│   │   ├── service/
│   │   │   └── windows_service.py # Service (262 lines)
│   │   └── tracker/
│   │       ├── app_tracker.py    # Window tracker (143 lines)
│   │       └── browser_tracker.py # Chrome tracker (244 lines)
│   ├── installer/            # Production installers
│   │   ├── install_service.ps1
│   │   ├── uninstall_service.ps1
│   │   ├── schema.sql
│   │   ├── setup_export_task.ps1
│   │   └── csv_export_task.xml
│   ├── requirements.txt     # 8 dependencies
│   ├── build_exe.spec       # PyInstaller spec
│   └── .gitignore
├── README.md              # Root README
├── CHANGELOG.md         # Version history
├── BUGS.md             # Bug analysis
├── TASK_MAG.md         # Task master
├── ANALYSIS_REPORT_V1.md  # This file
├── ANALYSIS_REPORT_V2.md  # Vulnerability audit
├── ANALYSIS_REPORT_V3.md  # Task management
├── FIXES_APPLIED.md     # Fix summary
└── run_tests.py        # Test suite
```

---

## 3. Modular Decomposition

### 3.1 Component Analysis

| Module | Purpose | Key Methods | Dependencies |
|--------|---------|------------|--------------|
| `app/config.py` | Central config | `_get_password_via_credmanager()`, `get_connection_string()`, `get_timestamp()` | win32cred, os, pathlib |
| `app/main.py` | Entry point | `UsageTrackerApp.run_forever()`, `UsageTrackerApp.initialize()` | All modules |
| `app/tracker/app_tracker.py` | Window capture | `get_foreground_window_info()`, `capture_event()` | psutil, win32gui |
| `app/tracker/browser_tracker.py` | Chrome history | `_get_chrome_history_copy()`, `extract_recent_history()` | sqlite3, shutil |
| `app/queue/queue_db.py` | Queue | `enqueue()`, `dequeue_batch()`, `check_backpressure()`, `repair_corruption()` | sqlite3, threading |
| `app/processor/worker.py` | Processor | `ProcessorWorker.start()`, `_process_batch()`, CircuitBreaker | threading |
| `app/db/sqlserver.py` | SQL Server | `insert_app_event()`, `insert_web_event()`, `test_connection()` | pyodbc |
| `app/exporter/csv_exporter.py` | CSV export | `export_all()`, `_export_app_usage()` | csv, gzip |
| `app/service/windows_service.py` | Service | `SvcDoRun()`, `SvcStop()` | pywin32 |
| `app/validation.py` | Validation | `validate_app_event()`, `validate_web_event()`, redaction | pydantic (optional) |
| `app/health.py` | Health check | `HealthServer.start()`, `get_health_data()` | http.server, psutil |

### 3.2 Data Flow Diagrams

#### Queue Processing Flow
```
dequeue_batch(batch_size=10)
       │
       ▼
┌──────────────────┐
│ Mark processing  │ ← Updates status in SQLite
└────┬───────────┘
       │
       ▼
┌──────────────────┐
│ Insert to SQL   │ ← Uses OUTPUT INSERTED.id
│ Server        │
└────┬───────────┘
       │
  ┌────┴────┐
  │         │
  ▼         ▼
Success    Failure
  │         │
  ▼         ▼
mark_   schedule_
completed retry()
```

#### Health Endpoint Flow
```
HTTP GET /health
      │
      ▼
┌─────────────────┐
│ Check auth     │ ← Bearer token (optional)
└────┬──────────┘
      │
      ▼
┌─────────────────┐
│ Gather metrics  │ ← Queue size, CPU, memory
└────┬──────────┘
      │
      ▼
┌─────────────────┐
│ Add alerts     │ ← Backpressure warnings
└────┬──────────┘
      │
      ▼
Response (JSON)
```

---

## 4. Engineering Trade-offs

### 4.1 Design Decisions

| Decision | Rationale | Benefit | Cost |
|----------|----------|---------|------|
| SQLite queue | No external dependencies | Easy deployment | Single-node bottleneck |
| Polling vs events | Simpler than hooks | Lower overhead | 5-second delay |
| Single-threaded processor | Simplicity | Less resource usage | Limited throughput |
| ODBC connection pool | Reuse connections | Better performance | Pool management overhead |
| WAL mode for SQLite | Concurrent reads | Better concurrency | Slightly higher disk usage |
| Multi-worker support | Parallel processing | Higher throughput | More complexity |

### 4.2 Latency vs Consistency

| Aspect | Choice | Impact |
|--------|--------|--------|
| Window capture latency | 5 seconds | Acceptable for productivity tracking |
| Queue drain latency | 10 seconds | Depends on batch size |
| Export latency | 10 minutes | Acceptable for daily reports |

### 4.3 Complexity vs Scalability

| Component | Current | Scalability Path |
|-----------|---------|------------------|
| Queue | Single SQLite | Add Redis for distributed |
| Processor | Single worker | Increase num_workers |
| Export | Full scan | Add incremental export |

---

## 5. Reconstruction Guide

### 5.1 Step-by-Step Rebuild

```python
# Step 1: Create the exact folder structure
# (See Section 2.3 above)

# Step 2: Implement core modules in this order:
# 1. config.py - Central configuration
# 2. validation.py - Input validation + redaction  
# 3. queue/queue_db.py - Persistent queue with WAL
# 4. tracker/app_tracker.py - Window capture
# 5. tracker/browser_tracker.py - Chrome extraction
# 6. db/sqlserver.py - SQL Server adapter
# 7. processor/worker.py - Queue processor with circuit breaker
# 8. exporter/csv_exporter.py - CSV export
# 9. service/windows_service.py - Windows service wrapper
# 10. health.py - Health endpoint
# 11. main.py - Entry point

# Step 3: Configure Windows Service
# Run: .\installer\install_service.ps1 as Administrator

# Step 4: Configure SQL Server
# Run: .\installer\schema.sql in SSMS
```

### 5.2 Key Configuration

```python
# app/config.py - Required settings
SQL_SERVER_CONFIG = {
    'driver': '{ODBC Driver 17 for SQL Server}',
    'server': 'localhost',  # Your SQL Server
    'database': 'UsageTracker',
    'username': 'usage_tracker_user',
    'password': 'YourPassword',  # Or use Credential Manager
}

# Operational settings
TRACK_INTERVAL = 5              # Window capture frequency
BROWSER_SCAN_INTERVAL = 30     # Chrome scan frequency  
MAX_QUEUE_SIZE = 1_000_000      # Queue limit
EXPORT_INTERVAL = 600          # CSV export (seconds)
USE_UTC = True                 # UTC timestamps
ENABLE_REDACTION = True        # PII redaction
```

### 5.3 Dependencies

```
# requirements.txt
psutil==5.9.6
pywin32==306
pyodbc==5.0.1
pydantic==2.0.0
WMI==1.5.1
```

---

## Summary

This V1 report provides the technical foundation for understanding the Personal Usage Tracker V3 system. The codebase is well-structured with:

- **Core modules**: 11 key Python modules
- **Architecture**: Tracker → Queue → Processor → SQL → CSV
- **Version isolation**: v1/, v2/, v3/ folders
- **52 previous fixes**: Already implemented

For Vulnerability Analysis (V2), see `ANALYSIS_REPORT_V2.md`.

---

*End of Analysis Report V1*