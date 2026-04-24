# Changelog — Personal Usage Tracker V3

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — v3.0.1 (Security & Reliability Update) — IN PROGRESS

### 🔒 Security Fixes (CRITICAL)
- **C-01** — Service account hardening: Installer now uses `NETWORK SERVICE` (least privilege) by default. Custom account support documented.
- **C-02** — Credential manager integration: Added `USE_CREDENTIAL_MANAGER` flag and `win32cred` helper to retrieve DB password from Windows Credential Manager. Plaintext password removed from config when enabled.
- **C-03** — Event validation & content redaction: New `app/validation.py` with Pydantic models + regex redaction for passwords, credit cards, SSNs, tokens. Configurable via `ENABLE_REDACTION`.
- **C-07** — PyInstaller hidden imports expanded: Added pydantic, wmi, win32com, csv, re to `build_exe.spec` to prevent runtime ModuleNotFoundError.
- **C-09** — Chrome history auto-detection: Multi-profile support (Default, Profile 1–9), WMI-based active console user detection, environment variable override. Works under service accounts.
- **C-10** — Queue size limits enforced: Max 1M events (configurable `MAX_QUEUE_SIZE`), prevents disk exhaustion. `QueueFullError` raised when full.
- **C-12** — Input validation layer: All events validated before DB insert via `EventValidator`. Rejects malformed data.

### 🛠️ Reliability Fixes (HIGH)
- **C-04** — Service recovery: Auto-restart on failure configured in installer (`sc.exe failure` actions).
- **C-05** — Console mode execution: `python -m app.main run` now works properly with tracking loop.
- **C-06** — SQL Server ID retrieval: Fixed `cursor.rowcount` → `SELECT SCOPE_IDENTITY()` in `sqlserver.py`.
- **C-08** — Exporter thread shutdown: Added `exporter.stop()` to `SvcStop()` prevents thread leak.
- **H-01** — Database connection timeout: Added 30s timeout + `pyodbc.pooling = True`.
- **H-02** — Queue performance index: Added `idx_next_retry` on `queue_events(next_retry_at)`.
- **H-04** — Removed pandas dependency: Replaced with built-in `csv` module; executable size reduced ~100MB.
- **H-05** — Event validation: Full Pydantic schema validation for app/web events, fallback basic validator.
- **H-06** — Chrome DB lock retry: 3 attempts with exponential-ish backoff on PermissionError.
- **H-07** — Service delayed auto-start: Installer sets `start= delayed-auto` to ensure SQL Server ready.
- **H-09** — Automatic queue cleanup: Processor runs daily `cleanup_old_events(30)` job.
- **M-04** — CSV daily rotation: Files named `app_usage_YYYY-MM-DD.csv`, retention 30 days.
- **H-03** — Circuit breaker: Processor halts DB operations after 5 consecutive failures, 60s recovery timeout.
- **H-08** — Sleep/hibernate handling: Monotonic clock detects system suspend; skips duplicate detection on resume.
- **H-10** — UTC timestamps: `USE_UTC` config flag + `get_timestamp()` helper; schema ready for `DATETIMEOFFSET` migration.

### 🐛 Bug Fixes (LOW/MEDIUM)
- L-08 — CSV UTF-8-BOM for Excel compatibility (already in code)
- General: Missing imports, thread lifecycle fixes, config improvements

### 📚 Documentation
- `TASK_MAG.md` — Comprehensive task board (52 issues) with status
- `BUGS.md` — Detailed bug analysis from 7 professional perspectives
- `CHANGELOG.md` — This file
- `README.md` — Security Configuration Guide, Deployment Tiers, Monitoring sections added

### 🏗️ Build & Deployment
- `installer/install_service.ps1` — Uses `NETWORK SERVICE`, sets delayed-auto-start, configures recovery actions
- `build_exe.spec` — Hidden imports expanded (`pydantic`, `wmi`, `win32com`, etc.)
- `requirements.txt` — Added `pydantic`, `WMI`
- `config.py` — New flags: `USE_CREDENTIAL_MANAGER`, `ENABLE_REDACTION`, `USE_UTC`, `MAX_QUEUE_SIZE`, `DATABASE_CONNECTION_TIMEOUT`

---

## [3.0.0] — 2025-04-17 (Initial Release)

First production release of Personal Usage Tracker V3.

### Added
- Full architecture: Tracker → Queue → Processor → SQL Server → CSV Export
- Zero data loss guarantee via persistent queue
- Retry logic with exponential backoff
- Windows Service deployment (pywin32)
- Chrome history tracking (multi-profile ready)
- Application window tracking (psutil + win32gui)
- SQL Server backend with indexes & stored procedures
- Periodic CSV export (Task Scheduler integration)
- PyInstaller build to single .exe
- PowerShell installers

### Known Issues (v3.0.0) — All Fixed in v3.0.1
- C-01 — Service LocalSystem → now NETWORK SERVICE
- C-02 — Plaintext credentials → Credential Manager support
- C-03 — No validation → full validation + redaction
- C-05 — Broken console mode → fixed
- C-06 — rowcount bug → SCOPE_IDENTITY()
- C-08 — Exporter leak → stopped on shutdown
- C-09 — Chrome path → multi-profile + WMI
- C-10 — No queue limit → max 1M events
- H-01 — No DB timeout → 30s timeout + pooling
- H-02 — Missing index → idx_next_retry added
- H-04 — Pandas bloat → removed, csv only
- H-05 — No validation → Pydantic models
- H-06 — Chrome lock → retry 3x
- H-07 — No delayed start → delayed-auto configured
- H-09 — No cleanup → daily automated cleanup
- M-04 — No CSV rotation → daily dated files

---

## Versioning Scheme

- **Major** (x.0.0): Breaking changes, architecture shifts
- **Minor** (x.y.0): New features, security fixes
- **Patch** (x.y.z): Bug fixes, documentation updates

---

## Upgrade Path

### From v3.0.0 → v3.0.1

1. Stop the service: `Stop-Service PersonalUsageTrackerV3`
2. Pull updated code (or copy new files)
3. Update Python deps: `pip install -r requirements.txt --upgrade` (pydantic, WMI added)
4. Rebuild: `.\build\build_exe.bat`
5. Reinstall service (recommended for account change):
   ```powershell
   .\installer\uninstall_service.ps1
   .\installer\install_service.ps1
   ```
6. Start service: `Start-Service PersonalUsageTrackerV3`
7. Verify logs: `Get-Content logs\tracker.log`

**Database changes**: None — schema unchanged

**Configuration changes**:
- New flags: `USE_CREDENTIAL_MANAGER`, `ENABLE_REDACTION`, `USE_UTC`, `MAX_QUEUE_SIZE`, `DATABASE_CONNECTION_TIMEOUT`
- Review `config.py` and adjust as needed

---

**Last updated**: 2025-04-17  
**Maintainer**: Usage Tracker Team  
**Contact**: GitHub issues