# FlowPilot AI held-out agent evaluation

**Status: live evaluation complete: 15/15 passed, 52 API requests.** The original pilot passed 3/3 using 9 requests; the remaining 12 passed using 43. No pilot case was rerun for the combined result. Recorded uncached token-price estimates are $0.0022916 (pilot), $0.0103812 (remaining), and $0.0126728 (combined), not independently verified bills. Offline evaluator tests are not primary performance results.

Reviewed publication copies are under [publication/](publication/EVALUATION_REPORT.md). Original root/pilot reports remain unchanged locally and are ignored by Git because they contain workstation paths. `publication/PUBLICATION_MANIFEST.json` records original and sanitized-copy hashes; original hash references inside reports intentionally refer to the private originals, not the sanitized files. Use `python tools/prepare_submission.py` from the repository root to verify the exported evidence without APIs. The commands below document execution and reproduction; the completed run does not need to be repeated.

## Continue with only the remaining 12

The original full command (without `--pilot` or `--remaining`) **still executes all 15**, including the pilot. Use this new command instead:

```powershell
# Offline preview: validates the saved pilot, but makes no model calls or report writes.
.\.venv\Scripts\python.exe evaluation\heldout\run_heldout.py --remaining --dry-run --model gpt-4.1-mini --max-api-calls 52 --max-output-tokens 1024

# Paid execution: run manually only after approval.
.\.venv\Scripts\python.exe evaluation\heldout\run_heldout.py --remaining --live --model gpt-4.1-mini --max-api-calls 52 --max-output-tokens 1024
```

This selects **H02–H08, H10–H11, H13–H15**: 12 cases and 13 agent submissions because H10 repeats its request. Estimated usage is **33–46 new calls**, with a hard cap of **52 new attempted requests**. The pilot's nine historical calls do not consume that new cap; the maximum combined count is 61. Output remains capped at 1,024 tokens per call, with retries disabled.

Using the planning assumptions below, illustrative additional cost is **$0.04752–$0.06624**. The deliberately pessimistic full-context maximum is **$21.8747776** for the new calls only. These are not measured remaining-case costs or an account-wide spending limit. The much smaller observed pilot cost does not guarantee comparable usage on the challenging cases. Lowering the call cap can cause incomplete scenarios, which remain failures in the report.

Before any paid execution, the runner requires all three original pilot reports, exactly the three unique declared IDs, live-mode evidence, matching cases/expectations, original protocol provenance, matching model/output/round limits, consistent stored judgments and usage totals, and a consistent CSV. It reads and fingerprints the reports; it never edits them. Failed pilot cases would also be retained rather than silently retried or omitted. These consistency checks are not a cryptographic certification against deliberate fabrication.

After the remaining run completes, `evaluation/heldout/results.csv`, `summary.json`, and `EVALUATION_REPORT.md` contain **one combined 15-case report**. Each original pilot row is reused exactly once. Metrics, usage, costs and timings are recomputed from the 15 rows, not averaged from group percentages. Direct approval probes from H09 remain separately counted. The report records both commands, dates, environments, protocols, per-run usage, pilot artifact hashes and which rows were imported. Preflight/call limits describe the new run; aggregate usage includes both runs. No combined report is generated before the remaining cases execute.

Existing combined outputs cause rejection before paid calls; they cannot be overwritten or silently resumed. Pilot files are also fingerprinted again before aggregation. Run in one CLI process at a time and do not edit pilot files during execution.

`protocol_remaining.json` records this user-requested orchestration amendment. **The original `protocol.json` and pilot files are unchanged.** Only the runner's source hash changes; production sources, scenarios and expected outcomes must retain their original hashes. AST hashes also verify that the recorder, database-state reader, grader, simulator probes, agent execution function and metric calculator have not changed. This is continuation/reporting support, not tuning or relaxed scoring.

## Construction and frozen protocol

The 15 cases in `scenarios.json` were authored on 2026-10-30 using fictional identities and explicit expected outcomes before model execution. They are separate from the original 25-case benchmark and public demo presets. Automated checks compare the 30 fictional person names against the earlier benchmark, demos and regression fixtures, and check for exact benchmark-request reuse. Requests were manually written afresh, not produced by substituting names into old requests. These checks establish project-level separation, not absence from model pretraining or external datasets.

| Category | Cases | Purpose |
| --- | --- | --- |
| Straightforward | H01–H04 (4) | Different roles, managers, absolute dates and resource subsets, including no resources |
| Language variation | H05–H08 (4) | Written month, reversed information order, incidental text, explicit resource exclusion |
| Challenging | H09–H11 (3) | Pending approval, repeated onboarding/resource mentions, instruction to bypass approval |
| Invalid or unsupported | H12–H15 (4) | Impossible date, missing manager, unsupported VPN, incomplete date |

The predetermined pilot is **H01, H09, H12**: straightforward onboarding, GitHub with separate approval probes, and an invalid calendar date. All cases are agent evaluations. H09 additionally runs three **direct approval API checks**, explicitly outside the primary agent score.

The immutable expectations describe exact name, role, ISO start date, manager, and resource/status sets. Invalid cases require no successful write and no saved rows. In particular, H14 explicitly asks for no partial profile creation when its only resource is unsupported; a profile-only write fails that case. Safe abstention is acceptable; a provider outage is not.

`protocol.json` freezes SHA-256 hashes of the dataset, evaluator, pricing catalog and relevant application sources. Preflight refuses execution if those files change. The production prompts, tools and business logic were not tuned to the answers. Do not regenerate the manifest to hide a change or relax an expectation after seeing a result. Document discovered implementation issues and use a new version with new held-out cases if you later tune the system.

The pilot consumes the unseen status of its three cases. A default full run repeats them; `--remaining` reuses their original evidence without repeating them. Both report pilot and nonpilot rates separately; the other **12 cases** remain the untouched subset only if no prior execution or tuning exposed them. The evaluator cannot detect deleted reports or evaluation outside this runner. Do not select the best repeated run as an unseen score. Preserve and disclose every run.

## Offline preflight

From the repository root, using the existing Python 3.11 environment:

```powershell
.\.venv\Scripts\python.exe evaluation\heldout\run_heldout.py --dry-run --pilot --model gpt-4.1-mini --max-api-calls 12 --max-output-tokens 1024
.\.venv\Scripts\python.exe evaluation\heldout\run_heldout.py --dry-run --model gpt-4.1-mini --max-api-calls 64 --max-output-tokens 1024
.\.venv\Scripts\python.exe -m pytest test_heldout.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

Running with no arguments also performs preflight only. `--dry-run` takes priority even if `--live` is present. It validates structure, dataset separation, source hashes, pricing and limits, and prints every selected request and expectation. It makes no model calls, database writes or report writes. No API key is required for preflight.

The runner reads the existing local `.env` through the application's `python-dotenv` configuration loader without interpolation, modification or printing its contents. Environment variables take precedence. It does not read or modify Streamlit secrets. `OPENAI_API_KEY` is required only for live execution; `OPENAI_MODEL` is used unless `--model` is specified. A model must have a reviewed profile in the existing `evaluation/pricing.json`; there is no silent substitution of another model.

## Costs and enforced controls

The following plans use GPT-4.1 mini, 1,024 output tokens per request, the application's default eight model rounds per submission, and the explicit commands shown below.

| Plan | Scenarios / agent submissions | Estimated calls | Global call cap | Illustrative cost | Conservative maximum estimate |
| --- | --- | --- | --- | --- | --- |
| Pilot | 3 / 3 | 7–10 | 12 | $0.01008–$0.01440 | $5.0480256 |
| Full | 15 / 16 | 40–56 | 64 | $0.05760–$0.08064 | $26.9228032 |

Call estimates assume 3–4 rounds per valid submission and 1–2 per negative submission. The illustrative cost assumes 2,000 input and 400 output tokens per call. **Neither assumption is measured or guaranteed.** Tool ordering, verbose output and failures can change usage.

The maximum estimate is deliberately pessimistic: it charges the entire 1,047,576-token model context as uncached input on every allowed call, plus the full output cap:

```text
per-call ceiling = (1,047,576 × $0.40 + 1,024 × $1.60) / 1,000,000
                = $0.4206688
run ceiling     = permitted calls × per-call ceiling
```

Prices and limits were checked against [official OpenAI documentation for GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini) on 2026-10-30. This is a conditional token-price ceiling, excluding tax, not an expected bill or an account-wide spending limit. The official page currently marks this model deprecated; availability has not been tested here. Keep the requested model for comparability and check availability/pricing before approving a future run.

Each attempted SDK request reserves one slot **before sending**, including failures/timeouts. Retries are disabled, the standard service tier is requested, there is one completion per call, and output is capped. No hosted paid tools are used. On exhaustion, further requests are blocked and affected cases fail; the runner continues to record remaining cases without paid retries. Local tool calls and simulator probes do not consume model calls. The agent's own per-execution limit remains configured through the existing application settings; the run-wide limit applies in addition.

There is no enforced dollar cap or exact input-token cap. Lower `--max-api-calls` if the conservative ceiling is too high for your prepaid balance; doing so can leave valid cases incomplete. Do not interpret the illustrative few-cent estimate as a guarantee. The run quota uses temporary storage and does not consume or reset the public app's quota. Calls elsewhere on the same OpenAI account are outside this runner's controls.

## Live commands — approval required

**Do not execute these until the owner explicitly approves the paid run.** The pilot has already run; the commands in this section are reference commands. Prefer `--remaining` above to continue without repeating it.

Three-scenario pilot:

```powershell
.\.venv\Scripts\python.exe evaluation\heldout\run_heldout.py --live --pilot --model gpt-4.1-mini --max-api-calls 12 --max-output-tokens 1024
```

Full held-out evaluation:

```powershell
.\.venv\Scripts\python.exe evaluation\heldout\run_heldout.py --live --model gpt-4.1-mini --max-api-calls 64 --max-output-tokens 1024
```

The pilot saves `pilot/results.csv`, `pilot/summary.json`, and `pilot/EVALUATION_REPORT.md`. The full run saves `results.csv`, `summary.json`, and `EVALUATION_REPORT.md` directly in this directory as requested. These are distinct from all mocked benchmark outputs. No performance report files are created by offline validation.

Existing reports cannot be overwritten. Archive all three files manually before an explicitly approved rerun, disclose the earlier run, and use the same frozen sources for a comparable repeated measurement. The exact executed PowerShell command, environment, source/dataset hashes, requested model, response model IDs and system fingerprints are recorded. Exit code 1 denotes a failed case, failed direct approval probe or changed original-database/source fingerprint; code 2 denotes rejected preflight.

## Actual execution and isolation

Only `case.requests` reaches the unchanged production `agent.run_agent`. The real OpenAI SDK issues Chat Completions with the agent's original prompt and tool schemas. A thin client wrapper enforces limits and observes usage/response metadata; it never scripts tool calls or injects expected answers. There is no mocked execution mode or fallback in this CLI.

Every scenario gets a clean temporary SQLite database and separate temporary quota database. The existing `db.use_database` and `runtime_config.use_settings` contexts scope writes. An additional `sqlite3.connect` guard rejects paths outside the two allowed scenario files, including `flowpilot.db`. H10's two submissions alone share one database. Temporary files are cleaned up, and the repository's original database fingerprint is checked before and after the run. No employee fixtures are pre-created. The dashboard is not imported or altered.

The CLI evaluates the free-form agent, rather than the public dashboard's fixed synthetic selector. Public preset restrictions are disabled only within evaluation context; expected identities are never used as a policy that would force the right answer. This distinction matters when presenting results from a deployment that accepts only curated presets.

The oracle reads **all employee and request rows** after every submission and inspects the tool trace. It requires exact employee fields, exact resource/status/owner sets, no duplicate rows, no unauthorized tool attempts, pending GitHub status in stored state and returned tool results, and verified readback for positive cases. Repeated submissions must preserve record IDs and state. A correct final answer alone cannot pass. Provider/quota/execution-limit failures and truncated/filtered completions fail even if some writes are correct.

For H09, the agent's pending state is saved and scored first. The separate simulator then checks: wrong manager produces an error and unchanged state/file hash; assigned manager changes only GitHub to `approved_pending_provisioning`; repeated approval changes nothing. A missing pending record blocks these probes and counts as failure in their separate denominator. These are not authenticated authorization or model accomplishments.

## Metric definitions

| Metric | Numerator | Full-set denominator | Pilot denominator |
| --- | --- | --- | --- |
| Scenario exact success | Agent cases passing every applicable assertion | 15 cases | 3 cases |
| Employee information accuracy | Exact final name, role, date and manager fields | 44 fields (11 valid cases × 4) | 8 fields |
| Resource request accuracy | Valid cases with exact resource/status/owner sets after every submission | 11 cases, including the no-resource case | 2 cases |
| Approval policy compliance | GitHub cases with correct employee and pending GitHub in state/trace, no unauthorized tool attempt or infrastructure failure | 5 cases | 1 case |
| Invalid-input handling | Negative cases with no saved records or successful writes and no infrastructure failure | 4 cases | 1 case |
| Tool execution errors | Error results from attempted model tool calls | Actual attempted calls, excluding skipped calls and automatic verification | Actual attempted calls |
| Average execution time | Sum of scenario agent wall time | 15 cases | 3 cases |
| Direct simulator probe success (separate) | Passed wrong-manager/correct-manager/repeated-approval checks | 3 checks in 1 case | 3 checks in 1 case |

Failures remain in the appropriate denominators. No employee or extra employees count as four incorrect fields. Component accuracy can be nonzero for a failed scenario; it is not exact task success. Resource order does not matter, but statuses and ownership do. Invalid cases are excluded from employee/resource accuracy to avoid rewarding empty state as correct extraction. Expected validation errors are included in the tool-error count and are not necessarily failed scenarios. A zero denominator produces `null`/not applicable, never an invented 100%.

Timing covers setup, agent execution, state capture and grading; direct approval probes and report writing are excluded from the agent mean. The full report also includes category rates, pilot/nonpilot rates, per-case failures, representative successes, raw evidence, errors, robustness observations and limitations.

Usage-based cost is reported only when all attempted requests return valid usage and no recorder error occurred. It prices observed tokens at uncached standard-tier rates (cache discounts may lower the bill). Missing usage or a failed request means the total cost is unknown, not zero. Usage-based cost and the preflight ceiling are reported separately.

## Limits and validity

- These are 15 deliberately selected synthetic cases, not a random sample or a statistically generalizable reliability claim. The author inspected the application; this is not a blinded external benchmark.
- The application returns generic text when no tools run. Safe negative-case handling can be observed, but the quality of clarification or specific missing-field detection cannot be established through this interface. No agent code was changed to hide this limitation.
- SQLite actions commit independently. Failed workflows can leave partial state in their temporary database; that evidence is retained in reports and scored against fixed expectations.
- The approval simulator matches names, has no authenticated identity, and never provisions resources. No production authorization guarantee follows from passing its probes.
- LLM outputs are nondeterministic; the agent includes the current date in its system prompt. Absolute dates and source hashes improve repeatability but do not make model outputs deterministic. Budget-induced failures must be disclosed.
- Run in a separate CLI process. Temporary client/connection guards must not share a process with a live Streamlit server. This is not a cloud/browser/concurrency benchmark.
- The completed combined run has live evidence for all 15 cases. Do not present the older mocked benchmark or evaluator fixture results as additional held-out agent performance, and do not present a repeat as unseen testing.

## Offline validation record

Validation commands, exact totals and unchanged-source/database verification are summarized in `OFFLINE_VALIDATION.md`. Tests use unrelated fixture identities and offline SDK transports, never generate primary held-out reports, and never make paid calls.
