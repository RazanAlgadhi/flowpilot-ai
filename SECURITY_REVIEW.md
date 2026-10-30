# FlowPilot deployment review

Prepared 2026-10-30. Scope: local source, publishable files, configuration, public demo controls, offline regression tests, and Streamlit startup. No remote repository was accessed or created, no code was pushed, no cloud deployment was performed, and no paid OpenAI calls were made.

## File inventory

Created:

- `runtime_config.py`, `safeguards.py`, `demo_scenarios.py`
- `.streamlit/config.toml`, `.streamlit/secrets.example.toml`
- `tools/audit_repository.py`, `tools/smoke_streamlit.py`
- `test_deployment.py`, `SECURITY_REVIEW.md`

Modified:

- `app.py`, `agent.py`, `db.py`, `conftest.py`
- `.gitignore`, `.env.example`, `requirements.txt`
- `evaluation/run_benchmark.py`, `evaluation/README.md`
- `evaluation/mocked/results.csv`, `evaluation/mocked/summary.json`, `evaluation/mocked/EVALUATION_REPORT.md`
- `README.md`, `TEST_REPORT.md`

The actual `.env` and existing `flowpilot.db` were not modified. The employee/request database schema is unchanged; quota/lease tables live in a separate runtime database.

## Findings

- The workspace is **not a Git repository**. There are no local tracked files or commits to inspect. The audit reports `unavailable_no_git_repository`; this does not establish that a previous or remote repository never contained secrets. Rerun the audit after initializing/cloning the intended repository and before committing.
- The final publishable-source pattern scan found **no credential patterns**. Current `.env`, secret files, and employee databases are excluded from that content scan and were not displayed or copied. A pattern scan cannot detect every possible credential format.
- `.gitignore` excludes `.env` variants, virtual environments, caches, SQLite databases/backups/journals, Streamlit secrets, key material, local cloud/SSH configuration, old source backups, and live evaluation artifacts. Placeholder examples remain publishable. Git's own ignore matcher verifies the required exclusions. Ignoring a path does not remove it from existing history, and `git add -f` can override exclusions.
- `.env.example` and `.streamlit/secrets.example.toml` contain placeholders only. The actual `.env` was not modified. Configuration reads known fields without interpolating values; exception text and HTTP/provider logs are not exposed to viewers. Displayed tool evidence is redacted. The OpenAI client uses a fixed official endpoint, zero retries, and bounded completions.
- Public mode is enabled by default and offers only server-owned fictional requests. Tool validation rejects employee details/resources outside the selected scenario. Each browser session has an independent SQLite database selected by a server-generated token through thread-local context. The original local database is not copied into public sessions.
- The daily quota is reserved atomically in a separate SQLite control file before each model request. Tests verify concurrent threads and separate processes sharing that file. Failed requests consume quota, and unavailable quota storage blocks calls. Workflow leases prevent overlapping session workflows and rapid identical resubmissions.
- The agent exposes only validated employee/request/readback tools. There are no arbitrary shell, SQL, file-path, or filesystem tools. Simulated manager approvals remain labeled as unauthenticated.

## Validation

- Python 3.11.0; installed dependencies satisfy `requirements.txt`; `pip check` passes. Streamlit minimum raised to the tested 1.66.1 for its exception-display configuration. No new dependency added.
- Full regression suite: **162 passed, 0 failed, 0 skipped**. Details in [TEST_REPORT.md](TEST_REPORT.md).
- Mocked evaluation: **25/25 passed**. This is not a live model performance measurement.
- Streamlit startup health check passed, with no workflows submitted and daily API quota set to zero. Process stopped afterward.
- Original `flowpilot.db` SHA-256 matched the pre-change fingerprint. No demo records were changed.

## Remaining risks and deployment boundary

- This is ready for **manual publication and a limited synthetic hackathon demo**, not production HR data or authenticated multi-tenant use. Cloud deployment itself has not been tested here.
- SQLite storage and quota counters are ephemeral on Community Cloud and can disappear or reset on restarts, redeploys, or host/storage replacement. Separate hosts have separate counters; there is no durable cross-host/global-account quota. Use an external durable service for that requirement.
- Anonymous visitors can consume shared quota or hosting resources. Session separation is not authenticated identity, manager-name approval is not authenticated authorization, and the controls are not an abuse-proof billing cap.
- Lease expiration allows recovery after crashes and may permit overlap if an operation outlives the conservative lease duration. Session files are not automatically purged on disconnect; no formal retention policy is implemented.
- Private developer mode retains free-form inputs and the original local database. It has no authentication and must never be exposed publicly with real records.
- Live model behavior, third-party billing, deployed Linux/cloud behavior, and production-scale hostile traffic were not tested. No live accuracy or production-security guarantee is made.

Follow the manual steps in [README.md](README.md). Add the API key only through ignored local configuration or the Cloud Secrets interface, keep public mode enabled, choose Python 3.11, and use `app.py` as entry point.
