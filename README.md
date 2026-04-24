# Personal Usage Tracker

<p align="center">
  <img src="https://img.shields.io/badge/Version-3.0.1-green.svg" alt="Version">
  <img src="https://img.shields.io/badge/Platform-Windows-blue.svg" alt="Platform">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License">
</p>

---

## 🚨 FORENSIC AUDIT REPORT (2026-04-24)

**Overall Health**: **NEEDS MAJOR REFACTOR** (**Score: 42/100**)

**Deployment Status**: ❌ **UNSAFE TO DEPLOY**

The system requires significant security fixes, architectural refactoring, and reliability improvements before production deployment. See [FORENSIC_AUDIT.md](FORENSIC_AUDIT.md) for the complete end-to-end forensic audit.

### Quick Summary

- **Security Score**: 25/100 - Plaintext password fallback, hardcoded secrets
- **Reliability Score**: 35/100 - Queue crash recovery broken, duplicate delivery risk
- **Architecture Score**: 30/100 - God objects, Session 0 isolation issue
- **Testing Score**: 55/100 - Missing integration/load/security tests
- **Performance Score**: 60/100 - Connection-per-event, no pooling
- **Maintainability Score**: 50/100 - Duplicate v1/v2/v3 directories

### Critical Issues (Must Fix Before Deployment)

| ID | Issue | Severity | Status |
|----|-------|----------|--------|
| C1 | Plaintext DB password fallback in config | 🔴 Critical | 🔧 Pending |
| C2 | Queue crash recovery gap (orphaned processing entries) | 🔴 Critical | 🔧 Pending |
| C3 | Service runs in Session 0 (cannot capture user windows) | 🔴 Critical | 🔧 Pending |
| H1 | Non-atomic queue claim enables duplicate delivery | 🔴 High | 🔧 Pending |
| H2 | Path mismatch (ProgramData vs repo-relative paths) | 🔴 High | 🔧 Pending |
| H3 | Dual export controllers (race condition) | 🔴 High | 🔧 Pending |

### Workarounds for Development Use Only

If using for development/testing (not production):

- Run as console app (`python -m app.main run --debug`), **NOT** as Windows Service
- Ensure `USE_CREDENTIAL_MANAGER=true` is set and credentials stored
- Set `ENABLE_REDACTION=true` (default)
- Monitor queue depth: `http://localhost:8765/health`
- Accept that tracking **won't work as service** due to Session 0 isolation

---

## ⚠️ Version Disclaimer

| Version | Status | Description |
|---------|--------|-------------|
| **v1** | ❌ Deprecated | Initial release (v3.0.0) - Contains known issues |
| **v2** | ⚠️ Developmental | Intermediate (v3.0.1-beta) - Functionally stable but may contain known bugs |
| **v3** | ✅ **RECOMMENDED** | Current stable (v3.0.1) - All 52 previous issues resolved |

> **IMPORTANT**: Version 2 is in a development stage. It is functionally stable but may contain known bugs. For production, use **Version 3** (with caveats - see audit report).

---

## 📊 REAL SYSTEM STATUS (V3)

While all known bugs (52) are fixed, the system is still evolving toward full production maturity.

### ✅ What's Working (V3.0.1)

| Feature | Status | Notes |
|---------|--------|-------|
| App Tracking | ✅ Working | Captures foreground window every 5 seconds |
| Browser Tracking | ✅ Working | Chrome history extraction |
| Persistent Queue | ✅ Working | SQLite-based, survives restarts |
| SQL Server Integration | ✅ Working | ODBC with connection pooling |
| CSV Export | ✅ Working | Daily rotation + gzip compression |
| Windows Service | ⚠️ **BROKEN** | Session 0 isolation prevents capture (see C3) |
| Security Hardening | ⚠️ **INCOMPLETE** | Plaintext fallback enabled if no credential manager |
| PII Protection | ✅ Working | Regex-based redaction |
| Input Validation | ✅ Working | Pydantic models |
| Circuit Breaker | ✅ Working | Auto-pause on failures |
| Service Recovery | ✅ Working | Auto-restart on failure |

### Known Architectural Limitations

| Limitation | Severity | Workaround | Notes |
|------------|----------|-----------|-------|
| SQLite queue is single-node bottleneck | ⚠️ Medium | Use moderate queue depth | Not designed for distributed processing |
| Processor is single-threaded | ⚠️ Medium | Batch size tuning | Cannot handle extreme load |
| No backpressure mechanism | ⚠️ Medium | Monitor queue size | Events may queue up during DB outages |
| CSV export not fully optimized | 🔵 Low | Daily rotation helps | Full snapshot every run |
| No alerting/monitoring system | 🔵 Low | Health endpoint available | localhost:8765/health |
| Service cannot capture user windows | 🔴 Critical | Run as console app only | Windows Session 0 isolation |
| Queue duplicates possible under load | 🔴 High | Single worker only | Non-atomic dequeue |

---

### 🚀 Next Improvements (V3.1)

| Improvement | Priority | Description |
|-------------|----------|-------------|
| Multi-worker processing | 🔴 High | Parallel queue processing |
| Queue optimization | 🔴 High | WAL mode for SQLite |
| Incremental export | 🔴 High | Export only new data |
| Metrics + alerting | ⚠️ Medium | Prometheus endpoint |
| Multi-browser support | ⚠️ Medium | Firefox, Edge tracking |

---

## 🚦 Quick Start (Version 3 - Development)

```powershell
cd personal-usage-tracker-main\personal-usage-tracker-main
pip install -r requirements.txt
python -m app.main run --debug
```

**Note**: Run as console app. Windows Service mode is not functional due to Session 0 isolation.

### Health Check

```powershell
# Check service health (if health server is running)
Invoke-WebRequest -Uri http://localhost:8765/health | ConvertFrom-Json
```

---

## 📦 Version Comparison

| Component | v1 (Deprecated) | v2 (Dev) | v3 (Production) |
|-----------|---------------|----------|----------------|
| Service Account | LocalSystem ❌ | NETWORK SERVICE | ⚠️ NETWORK SERVICE |
| Credentials | Plaintext ❌ | Option | ⚠️ Credential Manager |
| PII Protection | None | Basic | ✅ Full |
| Input Validation | None | Basic | ✅ Pydantic |
| Queue Limits | Unbounded ❌ | Partial | ✅ 1M |
| Circuit Breaker | None | ✅ Implemented | ✅ Stable |
| DB Timeout | Infinite ❌ | 30s | ✅ 30s + Pooling |
| Executable Size | ~200MB | ~100MB | ✅ ~100MB |

---

## 📁 Repository Structure

```
personal-usage-tracker/
├── app/                     # Main application package
│   ├── tracker/            # Tracking agents (app, browser)
│   ├── queue/              # Persistent SQLite queue
│   ├── processor/          # Queue worker (queue → SQL)
│   ├── exporter/           # CSV export (SQL → CSV)
│   ├── validation/         # PII redaction & validation
│   └── service/            # Windows service wrapper
├── src/                    # Legacy code (OLD tracker)
├── tests/                  # Test suite
├── tools/                  # Development utilities
├── packaging/windows/      # Windows installer files
├── infra/                  # Deployment configs
├── FORENSIC_AUDIT.md       # 🚨 Comprehensive security audit
└── README.md               # This file
```

---

## ✨ Features (Version 3)

- ✅ Zero data loss (persistent queue)
- ✅ Auto retry with exponential backoff
- ✅ Circuit breaker pattern
- ✅ PII redaction (configurable)
- ✅ Input validation (Pydantic)
- ✅ CSV daily rotation + gzip compression
- ✅ Health endpoint (localhost:8765)
- ✅ Config hot-reload
- ✅ Service recovery (auto-restart)

---

## 🛠️ Development

### Install Dependencies

```powershell
pip install -r requirements.txt
pip install -r requirements-dev.txt  # For testing
```

### Run Tests

```powershell
python -m pytest tests/ -v
python run_tests.py
```

### Run Audit

```powershell
# Review security and architectural findings
cat FORENSIC_AUDIT.md
```

---

## 🔒 Security

- PII redaction enabled by default (`ENABLE_REDACTION=true`)
- Credentials stored in Windows Credential Manager (recommended)
- SQL parameterization prevents SQL injection
- Input validation on all tracking events

**WARNING**: Plaintext password fallback exists if Credential Manager is not available. This is a **critical security vulnerability** (C1). Do not use in production until fixed.

---

## 📄 Documentation by Version

- **v1/README.md** - Deprecated version warnings
- **v2/README.md** - Developmental stage warnings  
- **v3/README.md** - Full production documentation
- **FORENSIC_AUDIT.md** - Comprehensive security & architecture audit

---

## 📈 Support

| Version | Support Level | Status |
|---------|--------------|--------|
| v1 | ❌ None | Deprecated |
| v2 | ⚠️ Community | Development |
| v3 | ✅ Full | Active (see audit) |

---

## ⚠️ Production Readiness

**Score**: 42/100 - **NOT SAFE FOR PRODUCTION**

See [FORENSIC_AUDIT.md](FORENSIC_AUDIT.md) for detailed findings and remediation plan.

**Estimated effort to production readiness**: 4-6 weeks

---

**Version**: 3.0.1  
**Repository**: Sandy32513/personal-usage-tracker  
**Last Audit**: 2026-04-24
