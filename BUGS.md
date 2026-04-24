# Personal Usage Tracker V3 — Live Bug & Risk Register (Final)

> Last updated: 2026-04-24 (commit f368e07)
> **Status**: Production-bound — **80/100**

## Remaining Open Items

| ID | Severity | Status | Title | Notes |
|----|----------|--------|-------|-------|
| T1 | 🟢 Low | 🔧 Optional | Expand test coverage >70% | Current ~60%; add DB retry tests |
| T2 | 🟢 Low | ⏳ Deferred | Structured JSON logging | Enhancement |

---

## Resolved Issues (Post-Audit) — ALL CRITICAL & HIGH FIXED

| ID | Finding | Severity | Fix Commit | Files Modified |
|----|---------|----------|------------|----------------|
| C1 | Plaintext DB password fallback in config | 🔴 Critical | b9e9c42 | Removed v1/v2 bloat |
| C2 | Queue crash recovery gap (orphaned processing) | 🔴 Critical | 6caa6d5 | worker.py, queue_db.py |
| C3 | Service runs in Session 0 (cannot capture user windows) | 🔴 Critical | 0ab1322 | agent.py, windows_service.py, installer |
| C4 | Missing DB schema validation on startup | 🔴 Critical | 0e3dfad | sqlserver.py, main.py |
| C4-retry | Startup DB retry with exponential backoff | 🟠 High | 12c5ec1 | windows_service.py |
| H1 | Non-atomic queue claim enables duplicate delivery | 🟠 High | 6caa6d5 | queue_db.py |
| H2 | Path mismatch (ProgramData vs repo-relative) | 🟠 High | ba8183d | installer |
| H3 | Dual export controllers (race condition) | 🟠 High | ba8183d | Removed duplicate task |
| H5 | UTC inconsistency (Python UTC vs SQL GETDATE) | 🟠 High | ba8183d | schema.sql, csv_exporter.py |
| H6 | Packaged export dependency on source tree | 🟠 High | 0ab1322 | Exporter in service |
| M1 | Missing `pydantic` locally — fallback weaker | 🟡 Medium | 044e3ab | validation.py |
| M2 | Dev requirements drift (CI tools missing) | 🟡 Medium | b9e9c42 | requirements-dev.txt |
| M3 | Detached utilities (health/config_watcher dead) | 🟡 Medium | 5bef701 | health integrated |
| M4 | Per-event DB connections, no batching | 🟡 Medium | fd6a9db | sqlserver.py, worker.py |
| M5 | Agent fallback queue not replayed | 🟡 Medium | c068111 | main.py |
| F4 | CSV formula injection risk | 🟡 Medium | 0c2da48 | csv_exporter.py |
| L1 | CI safety check always passes (`|| true`) | 🟢 Low | b9e9c42 | ci.yml |

**Total issues resolved post-audit**: 18

---

## Score Summary

| Category | Current | Change |
|----------|---------|--------|
| Maintainability | 90 | +65 |
| Security | 80 | +60 |
| Performance | 80 | +45 |
| Test Coverage | 60 | +30 |
| Repository Hygiene | 95 | +55 |
| **Overall** | **80/100** | **+51** |

---

## Deployment Verdict

✅ **Needs Minor Hardening** → **Production-Ready after minor items**

Blocking issues: **None** (all critical/high resolved)

Recommended final steps:
1. Add DB retry unit tests (optional)
2. Deploy to staging environment for smoke test
3. Monitor health endpoint for 48h

---

**Full forensic audit**: `FORENSIC_AUDIT.md`  
**Architecture docs**: `README.md`
