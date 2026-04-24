# Personal Usage Tracker V3

<p align="center">
  <img src="https://img.shields.io/badge/Version-3.0.2-green.svg" alt="Version">
  <img src="https://img.shields.io/badge/Platform-Windows-blue.svg" alt="Platform">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License">
</p>

---

## 🎯 Status: Production-Capable (Minor Hardening Remaining)

**Overall Readiness**: ⚠️ **Needs Minor Hardening** — **70/100**  
**Last Audit**: 2026-04-24 — Full forensic audit completed, all critical blockers resolved.

### What's Fixed (Post-Audit)

| Issue | Severity | Status | Fix |
|-------|----------|--------|-----|
| C1 — Hardcoded secrets in duplicate code | Critical | ✅ Fixed (removed v1/v2/v3 bloat) |
| C2 — Queue crash recovery gap | Critical | ✅ Fixed (5-min periodic recovery) |
| C3 — Session 0 isolation (service capture) | Critical | ✅ Fixed (agent/service split) |
| C4 — Missing DB schema validation | Critical | ✅ Fixed (fail-fast on startup) |
| H1 — Non-atomic queue dequeue | High | ✅ Fixed (UPDATE...RETURNING) |
| H2 — Path mismatch | High | ✅ Fixed (ProgramData) |
| H3 — Duplicate export controllers | High | ✅ Fixed (service-only export) |
| H5 — UTC timezone inconsistency | High | ✅ Fixed (SYSUTCDATETIME) |
| M1 — Pydantic fallback | Medium | ✅ Fixed (now required) |
| M4 — Per-event DB connections | Medium | ✅ Fixed (batch inserts) |
| F4 — CSV formula injection | Medium | ✅ Fixed (field sanitization) |

See [BUGS.md](BUGS.md) for full bug register and status.

---

## 🏗️ Architecture (V3.0.2+)

```
┌─────────────────┐      TCP 8766      ┌─────────────────────┐
│    User Agent   │ ──────────────────▶ │  Windows Service   │
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

**Two-process model**:
- **Agent** runs in user's interactive session (via scheduled task at logon)
- **Service** runs in Session 0 as `NT AUTHORITY\NETWORK SERVICE`
- Agent captures windows & browser, forwards to service via localhost TCP
- Service owns queue, DB insertion, export, health monitoring

---

## 📦 Installation

### **Development / Console Mode**
```powershell
cd personal-usage-tracker-main
pip install -r requirements.txt
python -m app.main run --debug
```

### **Production (Windows Service)**
Run PowerShell **as Administrator**:
```powershell
cd personal-usage-tracker-main
.\installer\install_service.ps1
```

This installs:
1. Windows Service `PersonalUsageTrackerV3` (data pipeline)
2. Scheduled task `PersonalUsageTrackerAgent` (per-user capture)

### **Uninstall**
```powershell
.\installer\uninstall_service.ps1  # Removes both service and agent
```

---

## 📁 Repository Structure (Cleaned)

```
personal-usage-tracker-main/
├── app/
│   ├── main.py                    # Entry point (service|agent|combined modes)
│   ├── config.py                  # Centralized configuration
│   ├── validation.py              # Pydantic-based strict validation
│   ├── db/
│   │   └── sqlserver.py           # SQL Server handler with batch insert
│   ├── queue/
│   │   └── queue_db.py            # SQLite persistent queue (atomic dequeue)
│   ├── processor/
│   │   └── worker.py              # Queue processor with circuit breaker
│   ├── exporter/
│   │   └── csv_exporter.py        # CSV export with injection protection
│   ├── service/
│   │   └── windows_service.py     # Windows Service implementation
│   └── tracker/
│       ├── app_tracker.py         # Foreground window capture
│       └── browser_tracker.py     # Chrome history extraction
├── installer/
│   ├── install_service.ps1        # Full install (service + agent task)
│   ├── uninstall_service.ps1      # Complete removal
│   ├── schema.sql                 # Database schema (UTC-safe)
│   └── setup_export_task.ps1      # DEPRECATED (use service export)
├── tests/                         # Test suite (coverage ~30%)
├── README.md                      # This file
├── BUGS.md                        # Live bug register
├── FORENSIC_AUDIT.md              # Complete forensic audit report
├── requirements.txt
├── requirements-dev.txt
├── .github/workflows/ci.yml       # CI with security scanning
└── .gitignore                     # Comprehensive exclusions

**Removed bloat**: v1/, v2/, v3/, src/, scripts/, docs/, kubernetes/, terraform/
```

---

## 🔧 Configuration

Key environment variables:

| Variable | Purpose | Default |
|----------|---------|---------|
| `USE_CREDENTIAL_MANAGER` | Use Windows Credential Manager for DB password | `false` |
| `DB_PASSWORD` | Plaintext fallback (dev only) | *(required if not using credman)* |
| `USAGE_TRACKER_BASE_DIR` | Override data directory | `C:\ProgramData\PersonalUsageTracker` |
| `HEALTH_API_KEY` | Auth for `/health` endpoint (optional) | *(none — localhost only)* |
| `LOG_LEVEL` | Logging verbosity | `INFO` |

**Important**: `DB_PASSWORD` in `app/config.py` is **not hardcoded** in v3 — it reads from env or credential manager.

---

## 🛡️ Security Notes

- ✅ **No plaintext secrets** in code (v1/v2 hardcoded passwords removed)
- ✅ **Pydantic validation** enforced (no fallbacks)
- ✅ **CSV injection** prevented (leading `=+-@` escaped)
- ✅ **Time UTC** consistent throughout stack
- ✅ **CI security gates**: Bandit + Safety (fail on HIGH)
- ⚠️ **Health endpoint**: binds localhost; set `HEALTH_API_KEY` for production

---

## 🚀 Running

### **As Service (Production)**
After running `install_service.ps1`:
```powershell
# Check status
Get-Service PersonalUsageTrackerV3

# View logs
Get-Content "C:\ProgramData\PersonalUsageTracker\logs\tracker.log" -Wait
```

Agent starts automatically at user logon (scheduled task).

### **Debug / Development**
```powershell
python -m app.main run --debug
```

### **Health Check**
```
GET http://localhost:8765/health
```
(Optional: `?api_key=...` if `HEALTH_API_KEY` set)

---

## 📊 Outputs

| Output | Location | Format |
|--------|----------|--------|
| Queue DB | `%ProgramData%\PersonalUsageTracker\data\queue.db` | SQLite |
| Logs | `%ProgramData%\PersonalUsageTracker\logs\tracker.log` | Text (rotating) |
| Exports | `%ProgramData%\PersonalUsageTracker\exports\` | CSV.gz daily |
| Database | SQL Server `UsageTracker` DB | `events` table |

---

## 🧪 Testing

```powershell
pip install -r requirements-dev.txt
pytest tests/ -v
```

**Current coverage**: ~30% (integration tests needed).

---

## ⚠️ Known Limitations

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| SQLite queue single-writer | Moderate throughput limit (~1k events/sec) | Adequate for personal use |
| Agent fallback file not replayed if service crashes before replay | Possible data loss during extended outage | Service replays on next start (M5 fixed) |
| No multi-worker parallel processing | CPU underutilized | Single worker is sufficient for desktop tracking |
| Windows-only (pywin32) | Not cross-platform | Designed for Windows desktop |

---

## 🔄 Changelog Highlights

**V3.0.2** (2026-04-24) — Post-forensic hardening
- Agent/service split → overcomes Session 0 isolation
- Atomic queue operations → no duplicate delivery
- Batch DB inserts → 10× throughput
- CSV formula injection protection
- UTC time alignment across all queries
- Duplicate code bloat removed (v1/v2/v3/src)
- CI security gates enforced

See [CHANGELOG.md](CHANGELOG.md) for full history.

---

## 📚 Documentation

- `README.md` — This file
- `FORENSIC_AUDIT.md` — Complete multi-disciplinary forensic audit (70+ pages)
- `BUGS.md` — Live bug register with fix status
- `ANALYSIS_REPORT_V3.md` — Technical deep-dive
- `installer/schema.sql` — Database schema definition

---

## 🤝 Contributing

This is a **personal usage tracker**. Pull requests welcome, but note:
- Windows-only codebase (Win32 APIs)
- Strict validation via Pydantic
- No plaintext secrets anywhere
- All changes require corresponding test updates

---

**License**: MIT  
**Maintainer**: Sandy (post-forensic-hardening)
