# FlowPilot AI evaluation benchmark

Mode: **mocked**. These results are scripted workflow tests, not live LLM performance.

Generated: 2026-10-29T22:22:07.154191+00:00

Production database fingerprint unchanged: **True**.

## Reproduce this run

Run from: `.`

```powershell
& '.\.venv\Scripts\python.exe' 'evaluation/run_benchmark.py'
```

## Metrics

| Metric | Numerator / denominator |
| --- | --- |
| overall pass rate | 25/25 (100.0%) |
| duplicate prevention success rate | 4/4 (100.0%) |
| missing field detection success rate | 4/4 (100.0%) |
| invalid input rejection rate | 4/4 (100.0%) |
| approval safety success rate | 4/4 (100.0%) |
| Category: successful | 5/5 (100.0%) |
| Category: duplicate | 4/4 (100.0%) |
| Category: missing_information | 4/4 (100.0%) |
| Category: invalid_input | 4/4 (100.0%) |
| Category: approval_authorization | 4/4 (100.0%) |
| Category: robustness | 4/4 (100.0%) |
| Interface: agent | 21/21 (100.0%) |
| Interface: approval_api | 4/4 (100.0%) |
| average execution seconds | 0.858873s / 25 = 0.034355s |
| median execution seconds | 0.027676s / 1 = 0.027676s |

Rate denominators include all scenarios in the named group, including failures. Specialized rates require every assertion in that category to pass.
Average time is total scenario wall time / scenario count. Median is the middle value (or sum of two middle values) / middle-value count; its sample size is 25. Timings include temporary database setup, actions, checks, client closure, and cleanup; imports and report writing are excluded.

## Scenario results

| ID | Category | Interface / mode | Result | Seconds | Failed assertions |
| --- | --- | --- | --- | ---: | --- |
| S01 | successful | agent / mocked | passed | 0.056030 | None |
| S02 | successful | agent / mocked | passed | 0.047749 | None |
| S03 | successful | agent / mocked | passed | 0.058185 | None |
| S04 | successful | agent / mocked | passed | 0.027604 | None |
| S05 | successful | agent / mocked | passed | 0.027676 | None |
| D01 | duplicate | agent / mocked | passed | 0.128822 | None |
| D02 | duplicate | agent / mocked | passed | 0.093293 | None |
| D03 | duplicate | agent / mocked | passed | 0.049222 | None |
| D04 | duplicate | agent / mocked | passed | 0.030372 | None |
| M01 | missing_information | agent / mocked | passed | 0.014188 | None |
| M02 | missing_information | agent / mocked | passed | 0.012025 | None |
| M03 | missing_information | agent / mocked | passed | 0.013908 | None |
| M04 | missing_information | agent / mocked | passed | 0.012771 | None |
| I01 | invalid_input | agent / mocked | passed | 0.012988 | None |
| I02 | invalid_input | agent / mocked | passed | 0.012652 | None |
| I03 | invalid_input | agent / mocked | passed | 0.012519 | None |
| I04 | invalid_input | agent / mocked | passed | 0.017200 | None |
| A01 | approval_authorization | approval_api / direct_approval_api | passed | 0.029510 | None |
| A02 | approval_authorization | approval_api / direct_approval_api | passed | 0.033223 | None |
| A03 | approval_authorization | approval_api / direct_approval_api | passed | 0.043265 | None |
| A04 | approval_authorization | approval_api / direct_approval_api | passed | 0.011826 | None |
| R01 | robustness | agent / mocked | passed | 0.030470 | None |
| R02 | robustness | agent / mocked | passed | 0.035818 | None |
| R03 | robustness | agent / mocked | passed | 0.026896 | None |
| R04 | robustness | agent / mocked | passed | 0.020661 | None |

## Failed scenario details

None. Expected negative-case errors were observed and asserted; they are not benchmark failures.

## Methodology

Each scenario runs actual agent.run_agent or db.approve_github against a fresh temporary SQLite file. The dashboard is not imported. Setup uses existing database helpers. All names and data are fictional.
Mock mode replaces only the OpenAI client with explicit tool-call scripts stored separately from assertions in scenarios.json. Tool dispatch, validation, writes, retries, readback, and approval all use application logic. Live mode ignores those scripts and wraps the actual client solely to observe usage; errors never fall back to mocks.
Pass/fail checks compare employee fields, exact resource/status multisets, IDs and state across retries, approval results, validation errors, and verification traces. Rejected approvals additionally compare database file fingerprints. Provider errors and execution-limit failures always fail the scenario, even when no writes occurred.
Full assertion evidence, per-action states, tool traces, and expected errors are stored in summary.json. results.csv provides a compact machine-readable table.

## API usage and cost

```json
{
  "mock_model_calls": 68,
  "live_sdk_calls": 0,
  "live_responses": 0,
  "usage_coverage": {
    "numerator": 0,
    "denominator": 0
  },
  "observed_tokens": null,
  "usage_complete": false,
  "cost_estimate_usd": null,
  "cost_note": "Not estimated: mocked calls have no provider usage, and no pinned model-specific pricing schedule is configured for live calls."
}
```

## Environment

```json
{
  "python": "3.11.0",
  "platform": "Windows-10-10.0.26200-SP0",
  "sqlite": "3.38.4",
  "openai": "2.54.0",
  "streamlit": "1.66.1",
  "configured_live_model": "gpt-4.1-mini",
  "source_sha256": {
    "agent.py": "95ab2608435a8837b634f5b4009e5a990ed0592a526629ec158b8f885ec28791",
    "db.py": "16cc8f94589a90c46d32e57712365e62701b649ebc9e32f4df58d2619a2f00ce",
    "app.py": "1145e154ab7f0da09c1551bf93878513cccba0a033b617cd48b8f4bb469dd4b2"
  },
  "scenarios_sha256": "267fe3f39c2c8c323d808ced470351b0ae07aa19888842997a108f092f1246a9"
}
```

## Limitations

- Mocked mode scripts model tool calls; it measures workflow/validation behavior, not LLM extraction, reasoning quality, latency, or live success rate.
- The overall rate pools 21 agent scenarios and 4 direct approval API tests. Separate interface rates are included; approval tests never use OpenAI, even in live mode.
- Rejection scenarios require a specific tool-validation error plus the expected database state. The current agent hides model clarification text behind a generic no-actions response. Safe abstention without a specific error is unobservable for detection and is not counted as a pass.
- I03 scripts malformed tool arguments in mocked mode. Live mode sends the malformed user request, which need not produce malformed tool arguments. These exercise different layers and are explicitly labeled.
- The injected create_request failure applies in both modes; its invocation is asserted. It does not simulate every possible network, storage, or provisioning failure.
- Each scenario has its own temporary SQLite database. Multi-step actions within a scenario share that database. Individual application actions commit independently; partial writes can remain after a failure.
- Approval remains an unauthenticated name-matching simulator. No resources are actually provisioned; no production authorization claim is made.
- Only 25 synthetic scenarios are evaluated. There is no statistical generalization to real workloads, and no browser, production load, concurrency, or crash-recovery benchmark.
- All dates in requests are absolute. Mock tool scripts are deterministic; wall times and live model responses are not. The application still supplies its current date to the model.
- SDK call counts do not include internal HTTP retries. Token totals cover only responses carrying valid usage metadata; incomplete usage is identified. Cost is not estimated without a pinned pricing schedule.
- The runner does not read .env. Live mode requires credentials already present in environment variables. Never run this in the same Python process as a serving dashboard because isolation temporarily patches module state.
- The production database fingerprint is checked before and after the run. An external dashboard write during evaluation can change that fingerprint; the runner reports this and never restores or overwrites the production file.
