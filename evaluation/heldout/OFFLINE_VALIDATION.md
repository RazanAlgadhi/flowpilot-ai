# Offline validation — 2026-10-30 (Asia/Riyadh)

## Remaining-only continuation amendment

After the owner ran the live pilot, its saved report was inspected: H01 passed with 4 requests, H09 passed with 4, H12 passed with 1; **3/3 passed, 9 requests**. No live calls were made while adding `--remaining`.

| New check | Actual result |
| --- | --- |
| Evaluator tests: `python -m pytest test_heldout.py -q` | 47 passed in 7.48 seconds; 0 failed |
| Full regression: `python -m pytest -q` | 209 passed in 21.10 seconds; 0 failed, 0 skipped |
| Remaining dry run | 12 cases, 13 submissions; exactly H02–H08, H10–H11, H13–H15; no executions |
| Estimated new calls / cap | 33–46 / 52 |
| Original three pilot files | All SHA-256 fingerprints unchanged |
| Original protocol, production sources and scenario hashes | Unchanged; orchestration-only amendment verified separately |
| Original `flowpilot.db` | SHA-256 unchanged |
| Combined report files | Absent; will be created only after the remaining execution |

Sixteen additional offline cases verify loading without modifying pilot files; rejection of missing/duplicate cases, mocked mode, changed expectations/model/output limits/protocol, false judgments, incorrect usage and inconsistent/missing report artifacts; remaining-only dry-run selection; and end-to-end aggregation with a budget-induced failure. The end-to-end test confirms 15 unique rows, unchanged imported pilot rows, separate approval-probe counts, separate run provenance, exactly-once API accounting, preservation of failure denominators and rejection of a second paid run when combined outputs exist. It uses unrelated synthetic fixtures and fake clients only.

Exact remaining preflight executed:

```powershell
.\.venv\Scripts\python.exe evaluation\heldout\run_heldout.py --remaining --dry-run --model gpt-4.1-mini --max-api-calls 52 --max-output-tokens 1024
```

Modified `run_heldout.py`, `README.md`, this validation record and `test_heldout.py`; added `protocol_remaining.json`. No original pilot artifact, production agent, scenario or expected outcome was changed. The historical initial-implementation record follows.

## Initial implementation record (before the owner's pilot)

**No paid OpenAI calls were made. No held-out LLM performance results exist.**

| Check | Actual result |
| --- | --- |
| New evaluator tests: `.\.venv\Scripts\python.exe -m pytest test_heldout.py -q` | 31 passed in 2.72 seconds; 0 failed, 0 skipped |
| Full regression: `.\.venv\Scripts\python.exe -m pytest -q` | 193 passed in 23.78 seconds; 0 failed, 0 skipped |
| Existing regression coverage within full run | All 162 existing tests passed |
| Pilot CLI preflight | Passed; 3 cases, 3 submissions, planned 7–10 calls, cap 12 |
| Full CLI preflight | Passed; 15 cases, 16 submissions, planned 40–56 calls, cap 64 |
| Dataset structure and separation | 15 unique case IDs; prescribed category counts; 3 pilot IDs; 30 fictional person names checked against prior datasets/fixtures; no scripted model responses |
| Frozen source/dataset/evaluator hashes | All matched `protocol.json` |
| Original `flowpilot.db` SHA-256 | Unchanged before/after implementation and tests |
| Held-out result files | None in the full or pilot output locations |
| Tracked application changes | None; only new held-out files and `test_heldout.py` were added |

The exact preflight commands executed (stdout was reduced to planning fields for review) were:

```powershell
.\.venv\Scripts\python.exe evaluation\heldout\run_heldout.py --dry-run --pilot --model gpt-4.1-mini --max-api-calls 12 --max-output-tokens 1024
.\.venv\Scripts\python.exe evaluation\heldout\run_heldout.py --dry-run --model gpt-4.1-mini --max-api-calls 64 --max-output-tokens 1024
```

The new automated tests verify:

- Schema, separation from older identities, pilot selection and frozen-source drift rejection.
- Default/preflight behavior cannot call the client, connect to SQLite or write reports, including `--live --dry-run`.
- Predeclared metric subsets, invocation counts and conservative cost arithmetic.
- Correct stored state passes independently of final response prose; wrong fields, extra employees, missing/duplicate resources, incorrect GitHub status/ownership, absent readback, unauthorized tool attempts and provider failures fail.
- Safe abstention and validation errors can pass negative cases; partial writes and provider errors cannot.
- Repeated workflows require correct intermediate state and stable IDs.
- An unrelated synthetic fixture runs through real production tool dispatch and SQLite with fake SDK responses. Separate wrong/correct/repeated approval probes are verified, and a probe failure does not change the primary agent score.
- The run-wide budget includes failed attempts, blocks excess calls, and never substitutes mocked results after failure.
- SQLite connection guards reject the original database and other outside paths without changing those files.
- A real SDK with an offline HTTP transport sends one request on HTTP 429, does not retry, and does not expose the synthetic error sentinel.
- Metric denominators include failed cases; complete usage can produce a token-price approximation, while incomplete usage cannot.
- Reports redact a synthetic credential sentinel, refuse overwrites, and keep pilot output separate.
- The CLI records later successes after an earlier failure rather than abandoning the remaining cases.

These are tests of evaluator correctness, not proof that GPT-4.1 mini solves any held-out scenario. Fake-client result objects exist only inside isolated test fixtures and temporary output directories; they were not saved as primary evaluation results. Live model availability, actual latency, token usage, task success and robustness scores remain unmeasured.

No production prompts, tools, business logic, dashboard, dependencies, `.env`, Streamlit secrets or original database records were changed. Nothing was pushed or deployed. Live evaluation awaits explicit approval; see `README.md` for costs, limits and commands.
