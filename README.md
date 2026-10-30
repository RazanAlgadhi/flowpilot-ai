# FlowPilot AI

FlowPilot is a Streamlit employee-onboarding demo for HUMAIN Challenge 3: Autonomous Enterprise. GPT-4.1 mini calls validated tools to create employee profiles and laptop, email, and GitHub requests. The dashboard shows employee details, request status, progress, and a collapsed execution trace. GitHub approval is a clearly labeled, unauthenticated simulation; no real equipment or accounts are provisioned.

**Streamlit entry point: `app.py`. Python: 3.11.** Public mode uses only predefined fictional employees and separates browser-session workspaces. It is not a production HR system.

## Architecture and stack

| Component | Responsibility |
| --- | --- |
| `app.py` | Native Streamlit dashboard, session workspace selection, simulation approvals |
| `agent.py` | OpenAI Chat Completions tool loop, argument/result validation, verified summaries, bounded model calls |
| `db.py` | SQLite employee/resource persistence, uniqueness, idempotency, manager validation; database context scoped to each execution thread |
| `runtime_config.py` | Streamlit secrets/environment/local configuration, secret redaction, credential-safe logging |
| `safeguards.py` | Atomic daily request quota and per-session workflow leases in a separate server-side SQLite file |
| `demo_scenarios.py` | Server-owned synthetic requests and permitted employee/resource values |
| `evaluation/` | 25-scenario mocked/opt-in live benchmark with isolated databases and separate reports |
| `tools/` | Read-only publication audit and no-workflow Streamlit startup smoke test |

Dependencies are in `requirements.txt`: Streamlit, OpenAI SDK, python-dotenv, and pytest. SQLite, context variables, and locking helpers use the Python standard library. No extra package was added for deployment safeguards. The Streamlit minimum is the locally tested 1.66.1 so deployments use the verified exception-display configuration.

The public request flow is: select a fictional scenario, acquire a server-side workflow lease, reserve daily quota before each model request, validate tool calls against the selected synthetic record, persist to that session's database, then read back and render the stored state. Successful tool actions commit individually; a later failure can leave earlier actions saved.

## Local installation

Use Python 3.11. From the project directory in PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# Only if .env does not already exist:
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Enter your own API key privately in the ignored `.env` file, an environment variable, or ignored `.streamlit/secrets.toml`. Never paste credentials into the app or commit them. The app can render without a key; executing onboarding requires one.

Public synthetic mode is the safe default locally and in the cloud. To retain free-form requests and view the original local `flowpilot.db` for **trusted local development only**, set a shell variable without modifying your existing `.env`:

```powershell
$env:FLOWPILOT_PUBLIC_DEMO = "false"
.\.venv\Scripts\python.exe -m streamlit run app.py
# Remove this override when returning to public demo mode:
Remove-Item Env:FLOWPILOT_PUBLIC_DEMO
```

Private developer mode has no authentication and shares its configured database. **Never deploy it publicly with real employee records.** Existing `flowpilot.db` is not migrated or copied into public workspaces.

## Configuration and secrets

Precedence is environment variables, then Streamlit root secrets, then local `.env`, then defaults. `.env` is read without interpolation and never rewritten. Only known configuration keys are used. `.env.example` and `.streamlit/secrets.example.toml` contain placeholders only.

| Name | Default | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | none | Required only for model requests; secret |
| `OPENAI_MODEL` | `gpt-4.1-mini` | Model selection |
| `FLOWPILOT_PUBLIC_DEMO` | `true` | Keep true for any public deployment |
| `FLOWPILOT_MAX_MODEL_CALLS` | `8` | Per-execution model request limit, permitted range 1–16 |
| `FLOWPILOT_MAX_OUTPUT_TOKENS` | `1024` | Per-request completion cap, permitted range 1–4096 |
| `FLOWPILOT_DAILY_API_QUOTA` | `100` | Shared daily request quota, UTC reset; 0 disables model requests |
| `FLOWPILOT_DATA_DIR` | OS temp directory + `/flowpilot` | Writable server runtime location for quotas, leases, and public session databases |
| `FLOWPILOT_DB_PATH` | existing `flowpilot.db` | Optional database path for private developer mode only |

The OpenAI client has automatic retries disabled, requests one completion, uses the standard service tier, and applies a 60-second timeout. Every attempted model request, including failed requests, consumes quota. Requests longer than 4,000 characters or containing the configured API key are rejected before transmission. Provider exceptions are replaced with safe messages; SDK/HTTP logging is suppressed during credential operations, and credentials are redacted from displayed/saved traces.

The quota is an atomic SQLite transaction in `control.sqlite3`, **not Streamlit session state**. It is shared by sessions and processes pointing to that same file. The workflow lease rejects concurrent submissions within a session and identical requests repeated within 30 seconds. Leases expire after a conservative timeout to recover from a crashed process. These controls reduce accidental duplicate spending; they are not an abuse-proof identity or billing system.

## Prepare GitHub manually

This workspace had no Git repository at the time of preparation, so no local commit history was available to audit. Do not assume that any previous remote repository is secret-free. The audit scans publishable source for credential patterns and, when a Git repository exists, checks tracked paths and reachable history/reflogs without printing secret values.

Run these read-only checks first:

```powershell
.\.venv\Scripts\python.exe tools/audit_repository.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe tools/smoke_streamlit.py
```

Then initialize and stage locally **when you choose to publish**:

```powershell
git init
git add .
git diff --cached --name-only
.\.venv\Scripts\python.exe tools/audit_repository.py
```

Review the staged filenames before committing. They must not include `.env`, virtual environments, caches, `.streamlit/secrets.toml`, private keys, local databases or their journals, or live evaluation reports. `.gitignore` covers these paths. Do not force-add ignored files. Ignore rules do not untrack an already committed file; the audit flags such cases. If a real credential is found in history, revoke/rotate it and resolve that history before publication.

Create an empty GitHub repository yourself. After the audit is clean and staged filenames are reviewed, replace `YOUR_USER/YOUR_REPO` below and run these commands manually:

```powershell
git commit -m "Prepare FlowPilot AI public demo"
git branch -M main
git remote add origin https://github.com/YOUR_USER/YOUR_REPO.git
git push -u origin main
```

No GitHub repository creation, project Git initialization, remote changes, push, or deployment was performed during preparation. The only temporary Git repositories created by the audit/tests are disposable local fixtures.

## Streamlit Community Cloud deployment

1. Publish the reviewed source to your GitHub repository. Include `requirements.txt`, application modules, `demo_scenarios.py`, `.streamlit/config.toml`, and the evaluation/tests you want to share. Exclude all local secrets and databases.
2. In Streamlit Community Cloud, create an app, select the repository and branch, and set the entry point to **`app.py`**.
3. Open **Advanced settings**, explicitly select **Python 3.11**, and enter root-level TOML secrets. Start with this placeholder template and replace the key privately in the Cloud interface:

```toml
OPENAI_API_KEY = "YOUR_OPENAI_API_KEY"
OPENAI_MODEL = "gpt-4.1-mini"
FLOWPILOT_PUBLIC_DEMO = true
FLOWPILOT_MAX_MODEL_CALLS = 8
FLOWPILOT_MAX_OUTPUT_TOKENS = 1024
FLOWPILOT_DAILY_API_QUOTA = 100
```

4. Deploy manually. Verify the synthetic-only selector and temporary-storage notice. Open a second browser session and check that its workspace starts empty. A real onboarding execution consumes paid API requests; do it only when you intend to.
5. Monitor usage in your OpenAI project. Set `FLOWPILOT_DAILY_API_QUOTA = 0` in Cloud secrets to disable new model requests if needed. Existing records can still be viewed and simulated approvals still work.

Official instructions: [repository, entry point, and Python selection](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy), [Cloud secrets management](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management). `.streamlit/config.toml` retains CORS/XSRF protection and hides browser exception details; the app also handles failures without rendering raw exceptions.

**SQLite storage on Community Cloud is ephemeral. Records and quota counters may disappear on a restart, redeploy, host replacement, or storage reset.** Public records live under the writable temp directory, with a random server-owned session token selecting each file. A browser reload/reconnection may establish a new session and lose access to the old workspace. Nothing here promises permanent employee storage.

## Tests and evaluation

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe tools/smoke_streamlit.py
.\.venv\Scripts\python.exe evaluation/run_benchmark.py
```

Tests use temporary databases, synthetic records, and mocked API responses. The startup smoke test starts a hidden local Streamlit process, checks its health endpoint, submits no workflows, sets the daily quota to zero, and stops the process. Neither command requires paid calls.

The benchmark includes 21 agent scenarios and 4 direct approval tests. **Mocked result: 25/25 passed; this is scripted workflow correctness, not live LLM performance.** Current reports are under `evaluation/mocked/`; historical root reports remain unchanged. See [TEST_REPORT.md](TEST_REPORT.md) for regression results and [evaluation/README.md](evaluation/README.md) for benchmark methods and limitations.

Preview live evaluation without executing it:

```powershell
.\.venv\Scripts\python.exe evaluation/run_benchmark.py --dry-run --max-api-calls 100 --max-completion-tokens 1024
```

Live evaluation requires `--live` and is **not** run automatically. It uses a separate run-wide budget, separate output directory, and temporary application quota/storage so it does not consume the dashboard's quota file or modify demo records. No live success rate has been measured in this preparation.

## Known limitations

- This is a synthetic, unauthenticated hackathon demo. Session separation is not authenticated tenant identity. Never use public mode for real employee information; never expose private developer mode publicly.
- Manager approval verifies a supplied name only. It is explicitly a simulation, not authorization by an authenticated manager.
- A malicious visitor can consume the shared quota or server resources. Anonymous sessions are not identities. The app is not a comprehensive bot-defense or rate-limiting service.
- The daily quota is global only across processes sharing one control database. It is neither durable across ephemeral storage resets nor global across independent hosts/replicas. Reliable multi-instance quotas require an external durable service. These limits are not an OpenAI account-wide dollar cap.
- Workflow leases have a recovery expiry; an unusually long-running operation beyond that expiry could overlap a replacement execution. Database uniqueness still prevents duplicate employee/resource identities.
- Browser-session databases and lease rows are not a permanent storage or retention system. They remain on local server storage until that storage is cleared; no authenticated account recovery or scheduled retention cleanup is implemented.
- Database actions commit individually. Later tool/API failures do not roll back earlier actions. Retries preserve resource approval status, and summaries read back stored records instead of trusting model-written success claims.
- Live model extraction, real provisioning, cloud-host behavior, and production-scale adversarial load have not been verified by offline tests. The static secret scan is pattern-based and cannot prove the absence of every possible secret.
