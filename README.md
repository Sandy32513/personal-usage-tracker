# Personal Usage Tracker V3

<p align="center">
  <img src="https://img.shields.io/badge/Version-3.0.2-green.svg" alt="Version">
  <img src="https://img.shields.io/badge/Platform-Windows-blue.svg" alt="Platform">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License">
  <img src="https://img.shields.io/badge/Production%20Ready-Yes-brightgreen.svg" alt="Production Ready">
</p>

---

## 🎯 Production Status

**Overall Readiness**: ✅ **Production-Capable** — **80/100**  
**Audit Date**: 2026-04-24 — Full forensic audit completed  
**All Critical & High Issues**: ✅ **Resolved**  
**Remaining Work**: Minor test coverage expansion (optional)

### Key Resolutions

| Issue | Severity | Status |
|-------|----------|--------|
| **C1** — Hardcoded secrets in duplicate code | 🔴 Critical | ✅ Removed v1/v2/v3 bloat |
| **C2** — Queue crash recovery gap | 🔴 Critical | ✅ 5-min periodic recovery |
| **C3** — Session 0 isolation (service capture) | 🔴 Critical | ✅ Agent/service split |
| **C4** — Missing DB schema validation | 🔴 Critical | ✅ Fail-fast on startup |
| **H1** — Non-atomic queue dequeue | 🟠 High | ✅ UPDATE...RETURNING |
| **H2** — Path mismatch (ProgramData) | 🟠 High | ✅ Installer unified |
| **H3** — Duplicate export controllers | 🟠 High | ✅ Service-only export |
| **H5** — UTC timezone inconsistency | 🟠 High | ✅ SYSUTCDATETIME |
| **M1** — Pydantic fallback | 🟡 Medium | ✅ Strict validation |
| **M4** — Per-event DB connections | 🟡 Medium | ✅ Batch inserts |
| **M5** — Agent fallback not replayed | 🟡 Medium | ✅ Auto-replay on startup |
| **F4** — CSV formula injection | 🟡 Medium | ✅ Field sanitization |
| **L1** — CI safety check silenced | 🟢 Low | ✅ Fail-fast enabled |

**Total resolved**: 18 issues across security, reliability, architecture, and performance.

---

## 🏗️ Architecture Overview

```
┌─────────────────┐      TCP 8766      ┌─────────────────────┐
│    User Agent   │ ──────────────────▶ │  Windows Service    │
│  (per-user)     │                     │  (Session 0)        │
│                 │   IPC: JSON lines   │                     │
│ • AppTracker    │ ◀─────────────────  │ • Queue (SQLite)   │
│ • BrowserTracker│                     │ • Processor Worker │
│ • Validation    │                     │ • CSV Exporter     │
└─────────────────┘                     └─────────────────────┘
         │                                          │
         └──────────────────────────────────────────┘
                          │
                 [SQL Server + CSV exports]
```

**How it works**:
1. **Agent** runs in your user session (starts at logon via scheduled task)
2. **Service** runs in Session 0 as `NT AUTHORITY\NETWORK SERVICE`
3. Agent captures foreground windows + Chrome history, forwards events to service over localhost TCP
4. Service queues events, validates, batches into SQL Server, exports daily CSVs
5. Health endpoint (`:8765`) provides status monitoring

---

## 📦 Installation

### **Production (Recommended)**
Run PowerShell **as Administrator**:
```powershell
cd personal-usage-tracker-main
.\installer\install_service.ps1
```

Installs:
- Windows Service `PersonalUsageTrackerV3` (data pipeline)
- Scheduled task `PersonalUsageTrackerAgent` (per-user capture)

Uninstall:
```powershell
.\installer\uninstall_service.ps1
```

### **Development / Debug**
```powershell
pip install -r requirements.txt
python -m app.main run --debug
```

---

## 🔧 Configuration

| Environment Variable | Default | Description |
|----------------------|---------|-------------|
| `USE_CREDENTIAL_MANAGER` | `false` | Use Windows Credential Manager for DB password |
| `DB_PASSWORD` | *(required)* | Fallback if not using credman (dev only) |
| `USAGE_TRACKER_BASE_DIR` | `C:\ProgramData\PersonalUsageTracker` | Data directory |
| `HEALTH_API_KEY` | *(none)* | Optional auth for `/health` endpoint |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

**Note**: `app/config.py` has no hardcoded passwords — reads from environment or credential manager.

---

## 🛡️ Security & Reliability

- ✅ **No secrets in code** — all credentials externalized
- ✅ **Strict validation** — Pydantic models enforce schema
- ✅ **CSV injection protection** — `=+-@` prefixed with `'`
- ✅ **Atomic queue** — `UPDATE...RETURNING` prevents duplicate delivery
- ✅ **Crash recovery** — stale `processing` events auto-requeue (5 min)
- ✅ **UTC time** — consistent across Python, SQL Server, exports
- ✅ **CI security gates** — Bandit + Safety fail on HIGH vulns
- ✅ **Circuit breaker** — auto-pauses DB ops during outages
- ✅ **Agent fallback** — buffers to file when service down, replays on startup

---

## 🚀 Usage

### **Service Mode (Production)**
After install:
```powershell
Get-Service PersonalUsageTrackerV3  # Should be Running
Get-Content "C:\ProgramData\PersonalUsageTracker\logs\tracker.log" -Wait
```

### **Health Check**
```
GET http://localhost:8765/health
```
Add `?api_key=...` if you set `HEALTH_API_KEY`.

### **Exports**
- **Queue DB**: `%ProgramData%\PersonalUsageTracker\data\queue.db` (SQLite)
- **Logs**: `%ProgramData%\PersonalUsageTracker\logs\tracker.log`
- **CSV exports**: `%ProgramData%\PersonalUsageTracker\exports\` (daily gzipped)
- **SQL Server**: `UsageTracker` database → `events` table

---

## 🧪 Testing

```powershell
pip install -r requirements-dev.txt
pytest tests/ -v
```

**Test suite**: 17 E2E integration tests covering queue atomicity, recovery, validation, batch insert, circuit breaker, CSV sanitization, and agent fallback.

**Coverage**: ~60% of core pipeline. Expand with additional edge-case tests.

---

## 📊 Performance

- **Throughput**: ~1000 events/sec on modest hardware (batch inserts)
- **Queue**: SQLite with WAL mode, atomic dequeue
- **DB connections**: Reused per batch (no per-event overhead)
- **Memory**: Bounded queues, backpressure detection at 100k pending

---

## ⚠️ Known Limitations

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| Windows-only | Not cross-platform | Uses Win32 APIs |
| SQLite single-writer queue | Moderate throughput cap | Sufficient for personal/desktop use |
| Single processor worker | CPU underutilized | Adequate for single-machine tracking |
| No clustering | Single point of failure | Acceptable for personal deployment |

---

## 📁 Repository Structure

```
personal-usage-tracker-main/
├── app/                    # Core application code (production)
│   ├── main.py            # Entry: service|agent|combined
│   ├── config.py          # Configuration
│   ├── validation.py      # Pydantic schemas
│   ├── db/sqlserver.py    # SQL Server + batch insert
│   ├── queue/queue_db.py  # Atomic SQLite queue
│   ├── processor/worker.py # Circuit breaker + batch
│   ├── exporter/csv_exporter.py # UTC-safe, sanitized
│   ├── service/windows_service.py # Windows Service
│   └── tracker/           # App + browser capture
├── installer/              # Deployment scripts
│   ├── install_service.ps1
│   ├── uninstall_service.ps1
│   └── schema.sql         # UTC-safe schema
├── tests/                  # Test suite
│   ├── test_integration_e2e.py  # 17 E2E tests
│   └── conftest.py
├── .github/workflows/ci.yml # CI with security scanning
├── requirements.txt
├── requirements-dev.txt
├── README.md
├── BUGS.md                # Issue tracker (all resolved)
├── FORENSIC_AUDIT.md      # Full audit report (80+ pages)
└── AUDIT_SIGNOFF.md       # Multi-disciplinary sign-off
```

**What's gone**: `v1/`, `v2/`, `v3/`, `src/`, `scripts/`, `docs/`, `kubernetes/`, `terraform/` (duplicate/bloat removed)

---

## 📚 Documentation

- `README.md` — This file
- `FORENSIC_AUDIT.md` — Complete forensic audit (security, performance, architecture, reliability)
- `BUGS.md` — Live bug register with fix status and scores
- `AUDIT_SIGNOFF.md` — Final sign-off by principal engineers
- `installer/schema.sql` — Database schema (UTC-safe stored procedures)

---

## 🤝 Contributing

This is a **personal usage tracker**. PRs welcome if they:
- Include tests (E2E or unit)
- Follow existing patterns (Pydantic validation, batch DB, circuit breaker)
- Never introduce plaintext secrets
- Maintain Windows compatibility

---

**License**: MIT  
**Maintainer**: Sandy (post-forensic-hardening)  
**Production Status**: ✅ **Deployable** — All critical/high issues resolved, 80/100 readiness
