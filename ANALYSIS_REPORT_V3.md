# Personal Usage Tracker V3 - End-to-End Analysis Report (v3)

> Version 3 is the operational dossier: the definitive risk register, step-by-step remediation plan, deferred task breakdown, and GitHub/redeployment playbook.

## 1. Definitive Risk Register

| ID | Severity | Perspective | Finding | Current State |
|---|---|---|---|---|
| C1 | 🔴 Critical | Security | Plaintext DB password fallback remains in `app/config.py` | Open |
| C2 | 🔴 Critical | Reliability | Queue rows in `processing` state are not recovered after crash/restart | Open |
| C3 | 🔴 Critical | Architecture | Service-mode capture likely conflicts with Windows Session 0 isolation | Open, inferred from architecture |
| H1 | 🟠 High | Reliability | Queue claim and delivery are not atomic or idempotent | Open |
| H2 | 🟠 High | DevOps | Frozen `ProgramData` path model is not enforced by installer/task scripts | Open |
| H3 | 🟠 High | Architecture | Export runs from both service code and scheduled-task path | Open |
| H4 | 🟠 High | Data correctness | Browser history cursor logic can miss or duplicate records | Open |
| H5 | 🟠 High | Data correctness | UTC claims in Python do not match SQL `GETDATE()` and `DATETIME2` usage | Open |
| H6 | 🟠 High | DevOps | Scheduled export depends on Python source tree, not packaged runtime | Open |
| M1 | 🟡 Medium | Validation | `pydantic` is missing in the observed local environment | Open |
| M2 | 🟡 Medium | Build hygiene | `requirements.txt` still includes unused `pandas` and mismatched versions | Open |
| M3 | 🟡 Medium | Observability | `health.py` and `config_watcher.py` are not integrated into live runtime control flow | Open |
| M4 | 🟡 Medium | Performance | SQL connection-per-event and full exports limit scale | Open |
| L1 | 🟢 Low | Maintainability | `config.py` prints path data at import time | Open |

## 2. Completed Stabilization Work Already In The Codebase

These items are already done in the current workspace and should not be reopened unless regression appears:

| ID | Task | Status | Priority |
|---|---|---|---|
| F1 | Fixed import/runtime blockers across validation, queue, main, exporter, and service modules | ✅ Completed | 🔴 Critical |
| F2 | Restored `export` CLI command and console run loop behavior | ✅ Completed | 🔴 Critical |
| F3 | Normalized browser-event validation and DB insertion field handling | ✅ Completed | 🔴 Critical |
| F4 | Made startup degrade gracefully when SQL Server is unavailable | ✅ Completed | 🟠 High |
| F5 | Repaired health utility crashes and queue size reporting | ✅ Completed | 🟡 Medium |
| F6 | Updated test harness to use isolated temp queue DB and skip SQL-only checks when needed | ✅ Completed | 🟠 High |
| F7 | Corrected build-spec root resolution and installer build invocation | ✅ Completed | 🟡 Medium |

## 3. Task Classification Matrix

| Task ID | Task | Status | Priority | Owner Lens | Outcome Needed |
|---|---|---|---|---|---|
| T01 | Remove plaintext credential fallback | ⏳ Pending | 🔴 Critical | Security | Secret must come only from env vars or Credential Manager |
| T02 | Add queue lease fields and startup recovery for stale `processing` rows | ⏳ Pending | 🔴 Critical | Senior Developer | No event may remain stranded after crash |
| T03 | Redesign capture for user-session execution instead of relying on raw service desktop access | ⏳ Pending | 🔴 Critical | Architect / Windows specialist | Foreground tracking must work in production deployment |
| T04 | Add atomic queue claim token and SQL idempotency key | ⏳ Pending | 🟠 High | Senior Developer / DB Engineer | Duplicate delivery should become a safe no-op |
| T05 | Unify installer, uninstaller, and scheduled task with frozen `ProgramData` path layout | 🔄 Partially Completed | 🟠 High | DevOps | Production pathing must be consistent |
| T06 | Choose a single export controller and delete the duplicate path | ⏳ Pending | 🟠 High | Architect / DevOps | Only one export runtime should exist |
| T07 | Replace browser `LIMIT 100` cursor logic with paginated watermarking | ⏳ Pending | 🟠 High | Senior Developer | High-volume browsing should not skip events |
| T08 | Migrate SQL time handling to UTC-safe schema/functions | ⏳ Pending | 🟠 High | DB Engineer | Reports should be timezone-correct |
| T09 | Make scheduled export runnable in packaged-only deployments | ⏳ Pending | 🟠 High | DevOps | Task should not require source Python tree |
| T10 | Install `pydantic` and align dependency versions | ⏳ Pending | 🟡 Medium | DevOps / Senior Developer | Validation behavior should match docs |
| T11 | Remove `pandas` and other stale dependency references from docs and requirements | ⏳ Pending | 🟡 Medium | DevOps | Reproducible environments |
| T12 | Either integrate or retire health/config-watcher utilities | ⏳ Pending | 🟡 Medium | Architect | Reduce dead or misleading feature surface |
| T13 | Batch DB inserts and reduce full-snapshot export cost | ⏳ Pending | 🟡 Medium | Performance / DB Engineer | Better runtime and network efficiency |
| T14 | Initialize Git and wire GitHub workflow for `Sandy32513/personal-usage-tracker` | ⏳ Pending | 🟡 Medium | DevOps | Repo should become pushable and releasable |
| T15 | Kafka integration | ⛔ Blocked / Not Possible | 🟢 Low | Architecture | No Kafka system exists in this codebase yet |

## 4. Step-By-Step Remediation Instructions

### T01 - Remove plaintext credential fallback

1. In `app/config.py`, delete the hardcoded fallback password.
2. Resolve credentials only from environment variables or Windows Credential Manager.
3. Fail fast with a clear startup error if no secret can be resolved.
4. Update installer and README to document the new secret requirement.

### T02 - Add queue crash recovery

1. Add `lease_owner`, `lease_expires_at`, and optionally `claimed_at` columns to `queue_events`.
2. Update dequeue logic to atomically claim rows inside a transaction.
3. On startup, reset expired leases from `processing` back to `pending`.
4. Add tests covering crash-after-claim and restart recovery.

### T03 - Fix the service/session architecture

1. Decide whether the product should be a per-user tray/agent app, a service-assisted agent, or a scheduled interactive task.
2. If service mode remains, move foreground capture into a user-session process and use IPC to pass events to the queue.
3. Keep the service limited to transport, recovery, and maintenance.
4. Validate on a real Windows login session, not only in console mode.

### T04 - Add idempotency and atomic delivery

1. Generate a deterministic event fingerprint from normalized payload fields.
2. Add a unique constraint or unique index in SQL Server for that fingerprint.
3. Claim queue rows atomically before processing them.
4. Treat duplicate key violations as successful completion rather than retryable failure.

### T05 - Unify runtime paths

1. Make `installer/install_service.ps1` create `C:\ProgramData\PersonalUsageTracker\data`, `logs`, and `exports`.
2. Make `uninstall_service.ps1` remove those paths instead of repo-relative directories.
3. Make the scheduled task use the same base directory and logging conventions.
4. Re-test both source mode and frozen mode separately.

### T06 - Choose one export controller

1. Pick either service-hosted exporter or Task Scheduler exporter.
2. Remove the unused path from code, scripts, and docs.
3. Add a smoke test for the surviving export path.

### T07 - Fix browser cursoring

1. Track a durable watermark in UTC.
2. Query Chrome history in ascending order with pagination until no rows remain.
3. Handle same-timestamp ties deterministically.
4. Add tests for more than 100 visits in one interval.

### T08 - Fix UTC semantics end-to-end

1. Migrate SQL timestamps from `DATETIME2` to `DATETIMEOFFSET` if feasible.
2. Replace `GETDATE()` with `SYSUTCDATETIME()` or explicit UTC handling.
3. Confirm exporter formatting and analytics procedures remain correct.
4. Document timezone expectations clearly.

### T09 - Make export packaged-runtime safe

1. Update `setup_export_task.ps1` so it can call the packaged executable or a known wrapper, not only Python source mode.
2. Ensure the packaged runtime knows where config and export directories live.
3. Validate on a machine without source checkout.

### T10-T13 - Hygiene, validation, and performance

1. Align `requirements.txt` with actual imports.
2. Install `pydantic` in dev and deployment environments.
3. Remove stale dependency references such as `pandas`.
4. Either integrate health/config watcher into the runtime or remove them.
5. Batch DB operations and move exports toward incremental logic if scale matters.

### T14 - GitHub enablement

1. Initialize Git in the workspace.
2. Add the remote `https://github.com/Sandy32513/personal-usage-tracker.git`.
3. Commit docs first, then open a hardening branch for code fixes.
4. Add CI after the repo is under source control.

### T15 - Deferred Kafka work

Kafka is not part of the current architecture. If Kafka becomes a requirement later, treat it as a new architecture project rather than a patch.

## 5. Deferred: Pending Credits / Resources

| Deferred ID | Item | Reason Deferred | Future Breakdown |
|---|---|---|---|
| D1 | Full user-session agent redesign | Requires architecture decision and Windows integration work | prototype tray agent, IPC protocol, service split |
| D2 | Exactly-once delivery semantics | Requires schema migration and queue redesign | lease model, fingerprints, duplicate-safe SQL |
| D3 | UTC data migration/backfill | Requires SQL migration planning | schema update, backfill, report validation |
| D4 | CI/CD and signed executable release pipeline | Requires Git repo, secrets, and Windows runner setup | GitHub Actions, build, package, release |
| D5 | Kafka integration | No Kafka system or contracts currently exist | design event schema, broker config, consumers |

## 6. README Update Payload

The README has been refreshed to include:

- the real current audit state
- known issues instead of "100% complete" claims
- a task matrix with status and priority labels
- GitHub and redeploy steps
- links to the three analysis report versions

## 7. GitHub Workflow For Sandy32513

```powershell
git init
git checkout -b audit/docs-refresh
git remote add origin https://github.com/Sandy32513/personal-usage-tracker.git
git add README.md BUGS.md ANALYSIS_REPORT_V1.md ANALYSIS_REPORT_V2.md ANALYSIS_REPORT_V3.md
git commit -m "docs: refresh tracker audit baseline"
git push -u origin audit/docs-refresh
```

After code hardening:

```powershell
git checkout -b fix/runtime-hardening
python -m compileall app run_tests.py
python run_tests.py
python -m app.main run
python -m app.main export
pyinstaller .\\build_exe.spec
git add .
git commit -m "fix: harden runtime, queue, and deployment"
git push -u origin fix/runtime-hardening
```

## 8. Full Redeployment Plan

1. Merge the docs-refresh branch.
2. Implement and validate T01 through T09 in a dedicated hardening branch.
3. Run smoke and regression tests.
4. Build the executable from `build_exe.spec`.
5. Stop the old service and any scheduled export task.
6. Back up SQL data plus any retained local queue state.
7. Provision `C:\ProgramData\PersonalUsageTracker`.
8. Deploy the corrected executable and install only the chosen single export controller.
9. Confirm app capture, browser capture, queue drain, DB insert, and CSV export on a real target machine.

## 9. Recreate-From-Scratch Blueprint

To recreate this project exactly as audited:

1. Create a Windows Python project with the folder structure listed in `ANALYSIS_REPORT_V1.md`.
2. Implement `AppTracker` with `win32gui` plus `psutil`.
3. Implement `BrowserTracker` by safely copying and querying Chrome `History`.
4. Implement a SQLite queue with retry metadata.
5. Add a background worker that forwards normalized events into SQL Server.
6. Add CSV export from SQL query results.
7. Add validation/redaction, a Windows service host, and installer scripts.
8. Preserve the current open issues if you want an exact recreation of this version; otherwise apply T01 through T14 to build the hardened version.

## 10. V3 Conclusion

The repo is no longer blocked by the earlier import/runtime defects, but it is still not a finished production system. The remaining work is now concentrated in architecture, reliability semantics, security hardening, and deployment discipline. That is good news: the next stage is no longer "make it run at all," it is "make the design honest and durable."

