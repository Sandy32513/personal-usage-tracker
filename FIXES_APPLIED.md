# Fixes Applied — v3.0.1 (In Progress)

This document summarizes all changes made after comprehensive bug analysis.

## Files Modified

### Core Application
- `app/config.py` — Added MAX_QUEUE_SIZE, ENABLE_REDACTION, REDACT_PATTERNS; improved frozen exe base dir handling
- `app/main.py` — QueueFullError handling, better loop control, export command
- `app/tracker/app_tracker.py` — No changes (working)
- `app/tracker/browser_tracker.py` — Chrome path detection overhaul (multi-profile, WMI active user, env override); Chrome lock retry
- `app/queue/queue_db.py` — Max size enforcement, queue cleanup, index on next_retry_at, improved schedule_retry, QUEUE_FULL_ERROR class
- `app/db/sqlserver.py` — Connection timeout + pooling, fix SCOPE_IDENTITY()
- `app/processor/worker.py` — Added validation integration, queue full handling, automatic cleanup
- `app/exporter/csv_exporter.py` — Removed pandas, pure csv writer, daily rotation, fixed imports
- `app/service/windows_service.py` — Start/stop exporter, proper component lifecycle
- `app/validation.py` — NEW: Pydantic-based validation with PII redaction, fallback basic validator

### Installer & Build
- `installer/install_service.ps1` — Configure delayed auto-start, step renumbering
- `installer/uninstall_service.ps1` — No changes
- `installer/schema.sql` — No changes
- `build/build_exe.bat` — No changes
- `build_exe.spec` — Expanded hidden imports (pydantic, wmi, win32com, csv, re), removed pandas, added validation.py

### Documentation
- `README.md` — Added Security & Known Issues section, deployment checklist, monitoring, troubleshooting; referenced CHANGELOG & BUGS
- `BUGS.md` — NEW: Full bug analysis of 40 issues, now updated with fix status (14 fixed, 26 pending)
- `CHANGELOG.md` — NEW: Documenting v3.0.1 fixes
- `.gitignore` — Added data/, logs/, exports/, build/, dist/, __pycache__

### New Files
- `app/validation.py` — Data validation & redaction module
- `BUGS.md` — Comprehensive bug inventory
- `CHANGELOG.md` — Version history
- `app/exporter/export_task.py` — Standalone export script for Task Scheduler
- `installer/setup_export_task.ps1` — Task Scheduler registration helper
- `installer/csv_export_task.xml` — XML task definition (legacy)

---

## Bug Fixes Applied (14)

### Critical (6)
- **C-04** — Service recovery (documented)
- **C-05** — Console mode execution works
- **C-06** — SQL Server SCOPE_IDENTITY() fix
- **C-08** — Exporter thread stopped on shutdown
- **C-09** — Chrome history multi-profile + WMI detection
- **C-10** — Queue max size (1M) enforced

### High (7)
- **H-01** — DB connection timeout (30s) + pooling
- **H-02** — Queue index on next_retry_at
- **H-04** — Removed pandas → smaller build
- **H-05** — Full event validation + redaction
- **H-06** — Chrome DB copy retry (3 attempts)
- **H-07** — Service delayed auto-start
- **H-09** — Daily queue cleanup

### Medium (1)
- **M-04** — CSV daily rotation + pandas removed

---

## Remaining Production Blockers (Priority Order)

| Bug | Severity | Description | Fix Effort |
|-----|----------|-------------|------------|
| C-01 | 🔴 Critical | Service LocalSystem → dedicated account | 8 cred |
| C-02 | 🔴 Critical | Plaintext DB credentials → Credential Manager | 10 cred |
| C-03 | 🔴 Critical | Redaction default off → enable by default | 0 (already coded) |
| C-07 | 🔴 Critical | PyInstaller hidden imports (mostly done) | 3 cred (verify build) |
| H-03 | 🟠 High | Circuit breaker for DB outages | 6 cred |
| H-08 | 🟠 High | Sleep/hibernate detection | 5 cred |
| H-10 | 🟠 High | UTC timestamps | 6 cred |
| M-01–M-10 (except M-04) | 🟡 Medium | Various polish items | 2-4 each |
| L-01–L-10 | 🟢 Low | Cleanup | 1-2 each |

**Total remaining high-priority credits**: ~45-55

---

## Configuration Changes Required

### Mandatory (Before Production)

1. **Update SQL credentials** in `app/config.py`  
   Change `server`, `username`, `password` to your environment.

2. **Choose service account**:
   - Leave as LocalSystem (insecure) — **NOT recommended**
   - Change to `NETWORK SERVICE` or custom user — see README Security section
   - Run `sc.exe config PersonalUsageTrackerV3 obj= "NT AUTHORITY\NETWORK SERVICE"`

3. **Implement C-02** (optional but recommended):
   ```powershell
   cmdkey /add:UsageTrackerDB /user:usage_tracker_user /pass:YourPassword
   ```
   Update `config.py` to use `win32cred`.

4. **Ensure Pydantic installed** (for validation):  
   `pip install pydantic` (already in requirements)

5. **Rebuild executable**:  
   `.\build\build_exe.bat`

6. **Test manually**:  
   `.\dist\PersonalUsageTrackerV3.exe run --debug`

### Optional Enhancements

- Set `ENABLE_REDACTION = True` (default is True)
- Adjust `MAX_QUEUE_SIZE` if disk space constrained
- Reduce `TRACK_INTERVAL` for finer granularity (more DB load)
- Adjust `EXPORT_INTERVAL` for more frequent CSV updates

---

## Testing Checklist (Updated)

Run `python run_tests.py`:

- [x] Config loads
- [x] App tracker captures window
- [x] Browser tracker initializes
- [x] Queue enqueue/dequeue
- [x] Queue max size enforcement
- [x] SQL connection (if DB available)
- [x] Processor processes events
- [x] CSV export methods exist
- [x] Retry scheduling works
- [x] **NEW** Validation catches invalid events
- [ ] Chrome history extraction (requires Chrome)
- [ ] Service install/start (requires admin)

---

## Deployment Steps (v3.0.1)

1. On dev machine:
   ```powershell
   pip install -r requirements.txt
   python run_tests.py
   .\build\build_exe.bat
   ```

2. Copy `v3-tracker` folder to target server

3. On target (as Administrator):
   ```powershell
   cd C:\path\to\v3-tracker
   .\installer\install_service.ps1
   ```

4. Verify:
   ```powershell
   Get-Service PersonalUsageTrackerV3
   Get-Content logs\tracker.log -Wait
   ```

5. After 10 minutes, confirm CSV file in `exports/`

---

## Next Actions

### Immediate (Within 1 Week)
1. **C-01**: Create dedicated service account, update installer to use it, document steps
2. **C-02**: Implement win32cred-based credential retrieval in `config.py`
3. **C-03**: Verify redaction is enabled by default (already `ENABLE_REDACTION = True`)
4. **H-03**: Add circuit breaker to processor
5. **H-08**: Add monotonic clock check for sleep detection
6. **H-10**: Migrate timestamps to UTC (requires DB schema change)

### Short-term (1 Month)
- Implement health check endpoint (M-05)
- Add log rotation (L-01)
- Add structured logging (L-01)
- Add configuration hot-reload (M-10)
- Write unit tests with pytest (L-06)

### Long-term (Q3+)
- Multi-browser support (Firefox/Edge)
- Data archival strategy
- Prometheus metrics (L-09)
- Web dashboard for analytics

---

**Prepared by**: Automated Analysis (Kilo CLI)  
**Date**: 2025-04-17  
**Version**: v3.0.1 (in development)

For questions or to report new issues, refer to repository issues or contact maintainer.