# FORENSIC AUDIT REPORT
**Personal Usage Tracker V3**  
**Audit Date**: 2026-04-24  
**Auditor**: Kilo Multi-Disciplinary Engineering Task Force  
**Status**: ❌ **UNSAFE TO DEPLOY**  
**Score**: 42/100

---

## A. EXECUTIVE SUMMARY

**Overall Health Assessment**: **NEEDS MAJOR REFACTOR** (Score: **42/100**)

The Personal Usage Tracker V3 presents itself as production-ready but suffers from **critical architectural debt**, **security vulnerabilities**, and **operational risks**. While the code demonstrates sophisticated intent (zero-loss queue, circuit breakers, PII redaction), it contains **fatal flaws** that render it unsafe for production deployment.

### Critical Findings:

1. **C1 - Plaintext DB Password Fallback**: `app/config.py` contains an insecure credential fallback that exposes database credentials.
2. **C2 - Queue Crash Recovery Gap**: `processing` state entries are not automatically re-queued after crash/restart, leading to data loss.
3. **C3 - Service Architecture Broken**: Windows Service runs in Session 0, making foreground window capture impossible (core feature non-functional).
4. **H1 - Non-Atomic Queue Operations**: Race condition allows duplicate event delivery under load.
5. **H2 - Path Configuration Mismatch**: Runtime expects `ProgramData` but scripts use repo-relative paths.
6. **H3 - Dual Export Controllers**: Service thread and scheduled task both export, risking file corruption and double-export.

### Key Statistics:

- **Total Issues Identified**: 34
- **Critical**: 4 (C1-C4)
- **High**: 6 (H1-H6)
- **Medium**: 4 (M1-M4)
- **Low**: 2 (L1-L3)
- **Deprecated/To Remove**: 18 (v1/v2/v3 duplicate trees, cache files, runtime artifacts)

**Deployment Verdict**: **DO NOT DEPLOY TO PRODUCTION**. The system requires immediate security patches, architectural refactoring, and comprehensive testing before production use.

---

## B. CATEGORIZED BUG REPORTS

### 🔴 CRITICAL SEVERITY

| ID | File:Line | Issue | Impact | Fix Required |
|---|---|---|---|---|
| **C1** | `app/config.py:56-65` | Plaintext DB password fallback when `USE_CREDENTIAL_MANAGER=false` OR env var missing. Code checks `if not DB_PASSWORD:` which allows empty string instead of failing secure. | **Database credentials exposed**; credential manager failure leads to plaintext password in memory/config. | **Remove fallback entirely**. Require either Credential Manager or env var. Fail fast with clear error: "No DB password configured. Set USE_CREDENTIAL_MANAGER=true or DB_PASSWORD." |
| **C2** | `app/queue/queue_db.py:60-68` | `_recover_stale_processing()` called **only on startup** with default 30-minute timeout. If worker crashes while processing, queue entries remain in `processing` state indefinitely. | **Data loss** during DB outages; events stuck in "processing" never retry until next full system restart (30+ min). | Add periodic stale-check in processor heartbeat (every 5 min). Reduce default timeout to 5 minutes. Call before every dequeue batch. |
| **C3** | `app/service/windows_service.py` | Windows Service runs in **Session 0**. `win32gui.GetForegroundWindow()` only sees Session 0 windows (services), **NOT user desktop**. Trackers capture nothing when running as service. | **Core functionality (tracking) completely broken** in production deployment mode. | Redesign to use per-session agent or switch to low-level keyboard/mouse hooks that cross session boundaries. Alternatively, run as user process (not service). |
| **C4** | `app/db/sqlserver.py:89-101` | `test_connection()` swallows exceptions and returns `False` silently. Main app interprets `False` as "warning" and continues with **queue-only mode**, never validating that required tables exist. | **Data silently lost** if DB exists but schema missing. Queue grows unbounded; no alerting. | Add schema validation on connection. Check for required tables (`events`, queue tables). Fail fast if missing. |

### 🔴 HIGH SEVERITY

| ID | File:Line | Issue | Impact | Fix Required |
|---|---|---|---|---|
| **H1** | `app/queue/queue_db.py:154-171` | **Non-atomic claim**: `dequeue_batch()` SELECTs rows without locking. Multiple workers can SELECT same rows. Individual `mark_processing()` calls create race condition allowing **duplicate delivery** if two workers grab same event. | Duplicate events in analytics; data integrity violation; incorrect usage metrics. | Use `UPDATE ... OUTPUT` with `SKIP LOCKED` or transaction with `SELECT FOR UPDATE` to atomically claim batch. Implement idempotency keys. |
| **H2** | `installer/` + `scripts/` + `app/` | Path mismatch: Config defaults to `C:\ProgramData\PersonalUsageTracker`. `git-push.sh`, `install_service.ps1`, `setup_watchdog_service.py` use **repo-relative paths** (`./daily_csvs/`, `./usage_log.db`). | **Files written to wrong directories**; service can't find its own data after install. Runtime vs build-time path confusion. | Unify all paths under `ProgramData`. Update scripts to use environment variable or absolute paths. Set `USAGE_TRACKER_BASE_DIR` consistently. |
| **H3** | `app/main.py:112-116` + `app/exporter/csv_exporter.py` | **Dual export controllers**: Scheduled Task (`csv_export_task.xml`) runs `python -m app.main export` separately from service's `CSVExporter` thread. Both query same DB tables with no coordination. | **Data corruption** if exports overlap; duplicate rows in CSV exports; file lock conflicts. | Remove scheduled task. Let service's `CSVExporter` handle all exports. Add export locking or use database-level advisory locks. |
| **H4** | `app/tracker/browser_tracker.py:97-103` | Chrome history query uses `LIMIT 100` per scan. If >100 visits occur between 30-second scans, older visits are **never captured** (watermark advances but skipped rows lost). No ordering guarantee on concurrent inserts. | **Undercounting web activity**; missing history events during high-traffic browsing sessions. | Remove LIMIT; use monotonic increasing `visit_time` watermark. Track last-seen `(visit_time, id)` tuple for correct pagination. |
| **H5** | `app/db/sqlserver.py` + `app/config.py` | Python uses UTC (`USE_UTC=True` default). SQL Server `GETUTCDATE()` used in `created_at` default. But export queries use `GETDATE()` (local time). Timezone mismatch corrupts date-range filters. | **Incorrect date boundaries** in exports; events appear on wrong days; data loss in daily exports. | Consistently use `GETUTCDATE()` everywhere. Or store all times as local with explicit TZ column + offset. Never mix. |
| **H6** | `app/main.py:112-116` | CSV exporter uses `EXPORT_INTERVAL = 600` (10 min) but only runs while **Python process is active**. Packaged EXE (PyInstaller) has no persistent scheduler. Scheduled task is separate with no coordination. | **Export fails silently** if service stops or EXE not running. No guarantee exporter runs at all after reboot. | Integrate export into service loop with proper state handling. Or use SQL Agent Job for SQL-side export. Add health check for export status. |

### 🟡 MEDIUM SEVERITY

| ID | File:Line | Issue | Impact | Fix Required |
|---|---|---|---|---|
| **M1** | `app/validation.py:44` | `PYODANTIC_AVAILABLE` check falls back to `basic_validation` if pydantic missing. `requirements.txt` lists `pydantic>=2.0.0,<2.14` but version not pinned. Environment may have older version with missing features. | **Validation weaker than expected**; PII redaction may not apply consistently. Security downgrade. | Pin exact pydantic version: `pydantic>=2.5.0,<2.14`. Remove fallback or make it hard error. Ensure pydantic is always available. |
| **M2** | `requirements-dev.txt` vs CI | `requirements-dev.txt` has only 27 bytes (pytest only). Missing `flake8`, `mypy`, `bandit`, `safety` referenced in `.github/workflows/ci.yml`. | **CI/CD broken**; lint and security scan steps will fail at runtime. | Sync dev requirements: add `flake8`, `mypy`, `bandit`, `safety`, `pytest-cov`. Pin versions. |
| **M3** | `app/health.py` + `config_watcher.py` | `HealthServer` runs but **not integrated** with worker status. Reports only queue size, not processor health. `config_watcher.py` exists but never imported/used. | **Health endpoint gives false positives**; config changes not hot-reloaded. Monitoring blind spots. | Wire health to actual processor metrics (processed count, errors, circuit breaker state). Implement/inject config watcher or remove. |
| **M4** | `app/db/sqlserver.py:202-214` | Every event insert opens/closes connection (`_get_connection()`). `pyodbc.pooling = True` set but pool not reused. High latency per event. | **Performance bottleneck** at scale; excessive connection overhead. Throughput limited. | Use connection pool (e.g., persistent connection per worker thread). Keep connection open for batch operations. |

### 🟢 LOW SEVERITY

| ID | File:Line | Issue | Impact | Fix Required |
|---|---|---|---|---|
| **L1** | `app/config.py:161-162` | `log_config()` prints `BASE_DIR` etc at **import time** (when module loaded). Causes noise in logs every time config imported. | **Log spam**; hard to trace actual runtime issues. | Remove print or move to debug level. Only log on explicit call, not import. |
| **L2** | `app/queue/queue_db.py:182-188` | `schedule_retry()` uses `datetime.now().isoformat()` then parses string for comparison. Inefficient. | Minor CPU waste; code smell. Not critical. | Pass `datetime` objects. Avoid string round-trip. |
| **L3** | `.github/workflows/ci.yml:52-58` | `safety check || true` always returns success even if vulns found. `docker-compose.yml` has hardcoded `SA_PASSWORD`. | **False sense of security**; secrets in version control. CI won't fail on vulnerabilities. | Make safety fail build on vulns (`safety check --fail-level HIGH`). Use GitHub secrets for passwords. |

