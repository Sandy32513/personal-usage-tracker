# Personal Usage Tracker V3 - Live Bug And Risk Register

> This file tracks the current open issues after the latest repair pass. It replaces older "all fixed" snapshots.

## Current Open Findings

| ID | Severity | Status | Title | Summary |
|---|---|---|---|---|
| C1 | 🔴 Critical | ⏳ Pending | Plaintext DB password fallback | `app/config.py` still contains an insecure fallback secret |
| C2 | 🔴 Critical | ⏳ Pending | Queue crash recovery gap | `processing` rows are not automatically re-queued after crash/restart |
| C3 | 🔴 Critical | ⏳ Pending | Service/session architecture mismatch | Service-mode foreground capture is likely unreliable due to Session 0 isolation |
| H1 | 🟠 High | ⏳ Pending | Duplicate-delivery risk | Queue claim is not atomic and SQL insert path is not idempotent |
| H2 | 🟠 High | 🔄 Partially Completed | Frozen path mismatch | Runtime expects `ProgramData`, installer/task scripts still rely on repo-relative paths |
| H3 | 🟠 High | ⏳ Pending | Duplicate export controllers | Service and scheduled task both own export responsibilities |
| H4 | 🟠 High | ⏳ Pending | Browser cursor correctness | `LIMIT 100` plus naive watermarking can skip or replay visits |
| H5 | 🟠 High | ⏳ Pending | UTC inconsistency | Python uses UTC-oriented logic while SQL procedures still use `GETDATE()` |
| H6 | 🟠 High | ⏳ Pending | Packaged export gap | Scheduled export depends on source Python mode |
| M1 | 🟡 Medium | ⏳ Pending | Missing `pydantic` locally | Fallback validation is active in the observed environment |
| M2 | 🟡 Medium | ⏳ Pending | Dependency drift | `requirements.txt` and local environment versions do not match cleanly |
| M3 | 🟡 Medium | ⏳ Pending | Detached utilities | `health.py` and `config_watcher.py` are not live runtime features |
| M4 | 🟡 Medium | ⏳ Pending | Performance headroom | DB connection-per-event and full export snapshots limit scale |
| L1 | 🟢 Low | ⏳ Pending | Import-time path prints | `config.py` writes noisy path information on import |

## Already Fixed In This Workspace

| Fix | Status | Priority | Notes |
|---|---|---|---|
| Import/runtime blockers | ✅ Completed | 🔴 Critical | Validation, queue, main, exporter, and service imports are repaired |
| Queue initialization defects | ✅ Completed | 🔴 Critical | SQLite index creation and missing imports fixed |
| CLI export path | ✅ Completed | 🔴 Critical | `python -m app.main export` is wired again |
| Browser event schema mismatch | ✅ Completed | 🔴 Critical | Validation and DB insertion now accept canonical web-event fields |
| SQL-down startup behavior | ✅ Completed | 🟠 High | App can buffer locally even when DB is unavailable |
| Test harness isolation | ✅ Completed | 🟠 High | `run_tests.py` now uses a temp queue DB and skips DB-only checks cleanly |

## Next Fix Queue

| Task ID | Task | Status | Priority |
|---|---|---|---|
| T01 | Remove plaintext secret fallback | ⏳ Pending | 🔴 Critical |
| T02 | Add queue lease and stale-processing recovery | ⏳ Pending | 🔴 Critical |
| T03 | Redesign service capture around a user-session model | ⏳ Pending | 🔴 Critical |
| T04 | Add idempotency keys and atomic queue claims | ⏳ Pending | 🟠 High |
| T05 | Unify all packaged runtime paths under `ProgramData` | 🔄 Partially Completed | 🟠 High |
| T06 | Choose a single export controller | ⏳ Pending | 🟠 High |
| T07 | Fix browser pagination and UTC watermarking | ⏳ Pending | 🟠 High |
| T08 | Migrate SQL time handling to UTC-safe functions/types | ⏳ Pending | 🟠 High |
| T09 | Make scheduled export work without source checkout | ⏳ Pending | 🟠 High |
| T10 | Align requirements and install `pydantic` everywhere | ⏳ Pending | 🟡 Medium |
| T11 | Integrate or retire health/config utilities | ⏳ Pending | 🟡 Medium |
| T12 | Initialize Git and connect GitHub workflow | ⏳ Pending | 🟡 Medium |
| T13 | Kafka integration | ⛔ Blocked / Not Possible | 🟢 Low |

## Deferred: Pending Credits / Resources

| Deferred ID | Item | Status | Priority | Reason |
|---|---|---|---|---|
| D1 | User-session agent redesign | ⛔ Blocked / Not Possible | 🔴 Critical | Requires architecture work beyond a quick patch |
| D2 | Exactly-once delivery model | ⛔ Blocked / Not Possible | 🟠 High | Requires queue and SQL schema redesign |
| D3 | UTC schema migration with backfill | ⛔ Blocked / Not Possible | 🟠 High | Requires coordinated DB migration |
| D4 | CI/CD and signed build pipeline | ⛔ Blocked / Not Possible | 🟡 Medium | Requires Git, repo secrets, and Windows runners |

## References

- See `README.md` for the operator summary and roadmap.
- See `ANALYSIS_REPORT_V1.md` for the executive architecture overview.
- See `ANALYSIS_REPORT_V2.md` for the technical deep dive.
- See `ANALYSIS_REPORT_V3.md` for the full remediation and redeploy plan.
