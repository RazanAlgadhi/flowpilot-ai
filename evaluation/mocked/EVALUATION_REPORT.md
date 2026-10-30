# FlowPilot AI evaluation benchmark

Mode: **mocked**. These results are scripted workflow tests, not live LLM performance.

Generated: 2026-10-30T00:07:53.266064+00:00

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
| average execution seconds | 1.269699s / 25 = 0.050788s |
| median execution seconds | 0.046157s / 1 = 0.046157s |

Rate denominators include all scenarios in the named group, including failures. Specialized rates require every assertion in that category to pass.
Average time is total scenario wall time / scenario count. Median is the middle value (or sum of two middle values) / middle-value count; its sample size is 25. Timings include temporary database setup, actions, checks, client closure, and cleanup; imports and report writing are excluded.

## Scenario results

| ID | Category | Interface / mode | Result | Seconds | Failed assertions |
| --- | --- | --- | --- | ---: | --- |
| S01 | successful | agent / mocked | passed | 0.074924 | None |
| S02 | successful | agent / mocked | passed | 0.053125 | None |
| S03 | successful | agent / mocked | passed | 0.061302 | None |
| S04 | successful | agent / mocked | passed | 0.058168 | None |
| S05 | successful | agent / mocked | passed | 0.046157 | None |
| D01 | duplicate | agent / mocked | passed | 0.125354 | None |
| D02 | duplicate | agent / mocked | passed | 0.102631 | None |
| D03 | duplicate | agent / mocked | passed | 0.078537 | None |
| D04 | duplicate | agent / mocked | passed | 0.075305 | None |
| M01 | missing_information | agent / mocked | passed | 0.025601 | None |
| M02 | missing_information | agent / mocked | passed | 0.027119 | None |
| M03 | missing_information | agent / mocked | passed | 0.025780 | None |
| M04 | missing_information | agent / mocked | passed | 0.025087 | None |
| I01 | invalid_input | agent / mocked | passed | 0.027522 | None |
| I02 | invalid_input | agent / mocked | passed | 0.025961 | None |
| I03 | invalid_input | agent / mocked | passed | 0.027879 | None |
| I04 | invalid_input | agent / mocked | passed | 0.041072 | None |
| A01 | approval_authorization | approval_api / direct_approval_api | passed | 0.036057 | None |
| A02 | approval_authorization | approval_api / direct_approval_api | passed | 0.042768 | None |
| A03 | approval_authorization | approval_api / direct_approval_api | passed | 0.051664 | None |
| A04 | approval_authorization | approval_api / direct_approval_api | passed | 0.015291 | None |
| R01 | robustness | agent / mocked | passed | 0.059914 | None |
| R02 | robustness | agent / mocked | passed | 0.067756 | None |
| R03 | robustness | agent / mocked | passed | 0.055603 | None |
| R04 | robustness | agent / mocked | passed | 0.039125 | None |

## Failed scenario details

None. Expected negative-case errors were observed and asserted; they are not benchmark failures.

## Methodology

Each scenario runs actual agent.run_agent or db.approve_github against a fresh temporary SQLite file. The dashboard is not imported. Setup uses existing database helpers. All names and data are fictional.
Mock mode replaces only the OpenAI client with explicit tool-call scripts stored separately from assertions in scenarios.json. Tool dispatch, validation, writes, readback, and approval all use application logic. Live mode ignores those scripts and wraps the real OpenAI client to observe usage and enforce request/output budgets; errors never fall back to mocks.
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
  "cost_note": "Actual billed cost is not inferred from partial usage. Mocked calls have no provider usage. Live cost ceilings and pinned pricing assumptions are reported separately under safety_controls."
}
```

## Live safety controls

```json
{
  "enforced_for_live_calls": false,
  "max_api_calls": 100,
  "attempted_calls": 0,
  "blocked_calls": 0,
  "max_completion_tokens": 1024,
  "model": "gpt-4.1-mini",
  "max_retries": 0,
  "n": 1,
  "service_tier": "default",
  "base_url": "https://api.openai.com/v1",
  "cost_ceiling": null
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
    "agent.py": "9ff642eaba741cf0e050f121fba1e0bc95db705fe33cea30d199db1072670c75",
    "db.py": "0a3f18d832bc51fb23aa3941242a00f9662367544678b0577a4493f49e309462",
    "app.py": "372b97956711a0d2c9d684cb05b53d7754aa34a0d097de83af7d2e7b310527d2",
    "runtime_config.py": "20eed640dd24eb252d454443cecdd4a7617c96e0ba20e2a69946d97a8de8b278",
    "safeguards.py": "589c07e2e05973b88a41b0aa2a2621a8952e8223b0301b32e5a1e1ae70df80f7",
    "demo_scenarios.py": "fc4da3356f8eb842e0ec6a950052874dc1864abab3b585f347065295761a03b3"
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
- Live SDK retries are disabled. A shared run-wide request budget counts failed attempts too. Output tokens and completion count are capped, and the standard service tier is requested. Exhaustion fails affected agent scenarios; direct approval tests still run.
- The cost ceiling uses the pinned pricing catalog and the full model context window as uncached input on every allowed call, plus capped output. It is deliberately pessimistic, excludes tax, and is conditional on the published model limits/prices. It is not an account-wide billing limit.
- CLI live/dry runs securely read allowlisted settings from the repository .env without interpolation or overriding existing environment variables. The file is never changed. Never run this in the same Python process as a serving dashboard because isolation temporarily patches module state.
- The production database fingerprint is checked before and after the run. An external dashboard write during evaluation can change that fingerprint; the runner reports this and never restores or overwrites the production file.
