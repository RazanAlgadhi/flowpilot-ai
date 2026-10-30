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
| `evaluation/` | 25-case scripted benchmark plus a separate 15-case live held-out evaluation using isolated databases |
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

The final audit checks publishable files and local reachable history/reflogs without printing matched values. Current publication reports use portable paths. Older reachable Git objects still contain workstation-user paths, so the history privacy audit remains flagged; a new commit does not remove that history. Review [SUBMISSION_REVIEW.md](SUBMISSION_REVIEW.md) before publication. Remote or pruned history is outside this audit.

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

Review staged filenames before committing. Exclude `.env`, virtual environments, caches, `.streamlit/secrets.toml`, private keys, local databases/journals and original machine-specific live reports. Publish the reviewed live evidence under `evaluation/heldout/publication/` instead; its manifest distinguishes original hashes from sanitized-copy hashes. `.gitignore` excludes the original held-out reports and pilot directory. Do not force-add them. Ignore rules do not remove history. If a real credential is found, revoke/rotate it and address that history before publication.

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

**Live held-out result: 15/15 synthetic scenarios passed**, using the unchanged production agent and real GPT-4.1 mini tool calling. The pilot passed 3/3 with 9 API requests; the other 12 passed with 43. The combined report imports the pilot once, totaling **52 requests**. Returned model: `gpt-4.1-mini-2025-04-14`.

| Live metric | Recorded result |
| --- | --- |
| Exact scenario success | 15/15 |
| Employee field accuracy | 44/44 fields |
| Exact resource request accuracy | 11/11 applicable cases |
| GitHub approval-policy compliance | 5/5 applicable cases |
| Safe invalid/unsupported-input handling | 4/4 cases |
| Tool execution errors | 0/42 attempted model tool calls |
| Mean scenario time | 83.2126493 seconds / 15 = **5.55 seconds** |
| Separate direct simulator checks | 3/3; not model task successes |

Usage was recorded for **52/52 requests**: 23,246 input and 2,109 output tokens (25,355 total). At the frozen uncached standard-tier rates, estimated token cost is **$0.0126728** (about 1.27 US cents), not a verified invoice. Pilot estimate: $0.0022916; remaining estimate: $0.0103812. Preflight worst-case ceilings are budget estimates, not measured costs.

Scoring checks stored SQLite rows and tool traces, not just the final answer. Cases were separate from prior demos/fixtures, with expectations fixed before execution. This small, deliberately constructed synthetic set does **not** establish general enterprise reliability; invalid handling measures safe abstention, not clarification quality. Approvals are unauthenticated simulations, and nothing is provisioned.

See the [publication report](evaluation/heldout/publication/EVALUATION_REPORT.md), [machine-readable evidence](evaluation/heldout/publication/summary.json), and [held-out methodology](evaluation/heldout/README.md). Publication copies normalize only workstation paths; original local evidence and frozen scoring logic remain unchanged.

Reproduce all **offline** checks from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe tools/prepare_submission.py
.\.venv\Scripts\python.exe tools/audit_repository.py
.\.venv\Scripts\python.exe tools/smoke_streamlit.py
.\.venv\Scripts\python.exe evaluation/run_benchmark.py --output-dir .flowpilot/benchmark
```

Tests use temporary databases, synthetic records, and mocked API responses. The startup smoke test starts a hidden local Streamlit process, checks its health endpoint, submits no workflows, sets the daily quota to zero, and stops the process. These commands require no paid calls. The benchmark command above writes a fresh mocked run into ignored local storage so it does not replace reviewed publication reports or reintroduce workstation paths into tracked files.

The older benchmark includes 21 scripted agent scenarios and 4 direct approval tests. **Mocked result: 25/25 passed; this is workflow testing, not live LLM performance and is not pooled with the 15-case live score.** Reports are under `evaluation/mocked/`. Their local paths have been normalized for publication without changing results. See [SUBMISSION_REVIEW.md](SUBMISSION_REVIEW.md) for current regression/security results and [evaluation/README.md](evaluation/README.md) for the older benchmark methodology.

Preview live evaluation without executing it:

```powershell
.\.venv\Scripts\python.exe evaluation/run_benchmark.py --dry-run --max-api-calls 100 --max-completion-tokens 1024
```

Live evaluation requires explicit `--live` and is **not** part of the offline tests. Historical pilot and remaining commands, limits, dates and environments are preserved in the publication report. Repeating them consumes credits and is a new repeated evaluation, not another unseen measurement. Existing local outputs are protected against overwrite. A fresh checkout can reproduce the workflow by running the documented pilot and remaining commands with its own credentials after approval; original private artifacts are not needed to verify the published evidence offline.

## Known limitations

- This is a synthetic, unauthenticated hackathon demo. Session separation is not authenticated tenant identity. Never use public mode for real employee information; never expose private developer mode publicly.
- Manager approval verifies a supplied name only. It is explicitly a simulation, not authorization by an authenticated manager.
- A malicious visitor can consume the shared quota or server resources. Anonymous sessions are not identities. The app is not a comprehensive bot-defense or rate-limiting service.
- The daily quota is global only across processes sharing one control database. It is neither durable across ephemeral storage resets nor global across independent hosts/replicas. Reliable multi-instance quotas require an external durable service. These limits are not an OpenAI account-wide dollar cap.
- Workflow leases have a recovery expiry; an unusually long-running operation beyond that expiry could overlap a replacement execution. Database uniqueness still prevents duplicate employee/resource identities.
- Browser-session databases and lease rows are not a permanent storage or retention system. They remain on local server storage until that storage is cleared; no authenticated account recovery or scheduled retention cleanup is implemented.
- Database actions commit individually. Later tool/API failures do not roll back earlier actions. Retries preserve resource approval status, and summaries read back stored records instead of trusting model-written success claims.
- Live extraction was measured only on the 15 synthetic held-out cases. Real provisioning, cloud-host behavior, and production-scale adversarial load were not tested by that evaluation. Static privacy/secret scanning cannot prove the absence of every possible secret or personal information.
