# FlowPilot AI benchmark

This benchmark supports the HUMAIN Challenge 3: Autonomous Enterprise demo. It evaluates 25 fictional onboarding scenarios against the application's existing tools and SQLite helpers. It does not change application code or the database schema.

## Run from the repository root

Deterministic scripted mode is the default and makes no OpenAI API calls:

```powershell
.\.venv\Scripts\python.exe evaluation/run_benchmark.py
```

New mocked reports are written to `evaluation/mocked/results.csv`, `evaluation/mocked/summary.json`, and `evaluation/mocked/EVALUATION_REPORT.md`. Existing reports directly under `evaluation/` are historical artifacts and are preserved. The process exits with code 1 if any scenario fails or the production database fingerprint changes, and code 0 if all checks pass. Reports are still generated for failed scenarios.

Preview the live run without executing scenarios, initializing any database, making API calls, or writing reports:

```powershell
.\.venv\Scripts\python.exe evaluation/run_benchmark.py --dry-run --max-api-calls 100 --max-completion-tokens 1024
```

The preview lists all 25 scenarios, identifies the 4 direct approval tests (zero API calls), and shows script-plan reference counts alongside the maximum live call count. Actual live usage cannot be predicted from scripted results. There are 24 agent invocations, each currently limited to 8 rounds by the app (192 possible rounds before the shared cap). `--dry-run` takes precedence even if combined with `--live` and requires no API key.

Live mode is explicit and consumes paid API credits:

```powershell
.\.venv\Scripts\python.exe evaluation/run_benchmark.py --live --max-api-calls 100 --max-completion-tokens 1024
```

Live reports always use `evaluation/live/`; mocked reports use `evaluation/mocked/`. `--output-dir` changes the base directory and the appropriate mode subdirectory is added automatically. An explicit directory ending in `live` or `mocked` must match the selected mode. Existing opposite-mode reports cannot be overwritten, including through the report writer interface. Failed live calls never fall back to mocks.

CLI live/dry runs read the repository's existing `.env` with `python-dotenv`, without printing its contents, modifying it, or interpolating variables. Only `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_ORG_ID`, and `OPENAI_PROJECT_ID` are imported, and already-set environment values take precedence. SDK/HTTP debug logging is suppressed during sensitive operations; active API keys are redacted from saved evidence and commands as a second layer of protection. Mocked CLI runs do not load `.env` or need credentials.

`OPENAI_MODEL` defaults to `gpt-4.1-mini`; `--model` provides an explicit benchmark-only override without changing the app or `.env`. Live calls explicitly target `https://api.openai.com/v1`, not an environment-supplied proxy endpoint. A 60-second request timeout is applied.

## Cost controls

- `--max-api-calls` defaults to **100** and is shared by every scenario and repeated action. The counter advances before each request. Failed requests and timeouts count, and the budget is never reset between scenarios. Once exhausted, additional requests are blocked, affected scenarios fail with a budget reason, and direct approval tests can still run.
- SDK retries are set to **0**, so a single counted request cannot cause hidden automatic retries.
- `--max-completion-tokens` defaults to **1,024**, with **one** completion per request and `service_tier='default'`. These controls are added by the benchmark wrapper without modifying the agent implementation.
- `pricing.json` pins standard USD token prices and model limits with a source URL and verification date. The CLI refuses live/dry runs for an unpriced model or an invalid cap; use a reviewed `--pricing-file` for another model. Do not assume an arbitrary model shares the default model's rates or limits.

The deliberately pessimistic ceiling is:

```text
max_api_calls * (
    model_context_window_tokens * uncached_input_USD_per_million
    + max_completion_tokens * output_USD_per_million
) / 1,000,000
```

At the pinned GPT-4.1 mini rates ($0.40/M input and $1.60/M output), using its 1,047,576-token context window and the default 100 calls / 1,024 output cap gives **$42.06688**, or about **$42.07**. This charges the full context window on every call, making it far higher than a typical small onboarding prompt; it is not a forecast. [Official model pricing and limits](https://developers.openai.com/api/docs/models/gpt-4.1-mini). [Official output-cap and service-tier semantics](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create).

The call and completion limits are enforced locally. The dollar ceiling depends on the pinned price/model assumptions, excludes taxes, and is not an account-wide billing cap. Recheck prices for future runs. Usage metadata is recorded only when supplied by the provider; missing usage is not fabricated. The API-key owner remains responsible for any other concurrent API usage.

Regression tests, including benchmark integrity tests, use no real API calls:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Scenario catalog

| Category | Count | Interface |
| --- | ---: | --- |
| Successful onboarding | 5 | Agent |
| Duplicate/repeated requests | 4 | Agent |
| Missing information | 4 | Agent |
| Invalid inputs | 4 | Agent |
| Approval and authorization | 4 | Direct approval API |
| Robustness | 4 | Agent |

`scenarios.json` contains unique IDs, input requests, expected outcomes, explicit assertions, optional setup/fault injection, and per-action scripted model tool batches. Assertions and model scripts are separate. Live execution ignores the scripts entirely. Requests use absolute dates and fictional people. Multi-action scenarios share one temporary database; different scenarios never share their data.

Only the model client is mocked in offline mode. Live mode invokes the real OpenAI SDK with the cost controls above. `agent.run_agent`, its tool validation and dispatch, database operations, and `db.approve_github` execute normally. The fault scenario temporarily replaces the resource tool with a throwing function and verifies that it was actually invoked. All patches are scoped and restored. Run this as a separate process, not inside a running Streamlit process.

The database path is replaced before initialization or fixture setup. Every connection also checks that the current path still resolves to that scenario's temporary database; an attempt to restore the production path is blocked before opening a connection. The agent's allowlisted tools expose no database-path, SQL, or arbitrary filesystem interface. Reports reject linked destination files that could redirect writes into demo records. Production records are never seeded, queried, or updated by a scenario.

The application's server-side quota storage is also scoped to a temporary directory for each evaluation scenario. Evaluation therefore does not consume or reset the dashboard's shared quota file. The benchmark's separate run-wide live request budget remains enforced. Public UI presets are not used for the catalog: these controlled synthetic tests exercise the underlying agent directly. The dry-run round bound follows the application's configured per-execution limit (8 by default).

## Interpret the results

Mocked pass rates demonstrate that the expected tool sequences satisfy application invariants. They do **not** measure how well a real model understands rephrased instructions, extracts employee details, selects tools, or handles user intent.

A scenario passes only when every explicit assertion passes and no provider error or execution-limit failure occurs. Rates include all scenarios in each denominator. Specialized rates use all four scenarios in the corresponding category. Approval safety includes both correct approvals and rejected unauthorized attempts; it is not an authentication security score.

Missing/invalid scenarios require a specific validation error in a tool result as well as the expected database state. The application's public agent interface replaces no-tool model clarifications with a generic no-actions message. The benchmark therefore cannot confirm *which* missing field was detected from that message alone. Such a live outcome is reported as a failed observability assertion, even if abstaining was safe. It is never fabricated as successful field detection. I03 also distinguishes malformed user input in live mode from scripted malformed tool arguments in mock mode. The report documents these limits.

Average and median times include database setup, actions, state checks, and cleanup. They pool agent and direct approval scenarios; the result table identifies each interface. Scripted timings are not model latency. Token usage coverage is reported explicitly, and absent usage is not replaced with estimates.

The benchmark is small and synthetic, so its results do not support statistical generalization. It does not evaluate authenticated production approvals, real provisioning, browser rendering, concurrency, crash recovery, or production load. Existing actions commit independently; a failed later action can leave earlier records saved.

`summary.json` contains full assertion evidence, tool traces, per-action database snapshots, source/scenario hashes, and environment versions. The Markdown report includes the exact executed command and all failed assertions. Only fingerprints of the real `flowpilot.db` are read, never its employee records; a changed fingerprint is reported without overwriting that file.
