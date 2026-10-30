# FlowPilot robustness test report

Run date: 2026-10-30 (Asia/Riyadh).

Command: `.\.venv\Scripts\python.exe -m pytest -q`

Latest result after deployment preparation: **162 passed in 14.63s; 0 failed, 0 skipped.** All 143 existing cases passed, together with 19 new deployment cases. No real OpenAI API calls were made. Earlier runs passed 143 cases in 11.50s, 122 cases in 7.72s, and 102 cases in 5.60s.

| Suite | Passed | Failed |
| --- | ---: | ---: |
| `test_db.py` | 66 | 0 |
| `test_agent.py` | 32 | 0 |
| `test_app.py` | 4 | 0 |
| `test_benchmark.py` | 20 | 0 |
| `test_benchmark_safety.py` | 21 | 0 |
| `test_deployment.py` | 19 | 0 |
| Total | 162 | 0 |

Every test uses a temporary SQLite database. No production database or real employee data is used. The shared fixture disables dotenv loading and fails a test that attempts to initialize an unmocked OpenAI client. The existing dashboard examples in tests are synthetic fixtures.

The standalone mocked benchmark also passed **25/25 scenarios** before the regression run. The original `flowpilot.db` fingerprint remained unchanged throughout deployment preparation. Application modules were intentionally updated for session isolation and server-side safeguards; current hashes are in the benchmark report. See [evaluation/mocked/EVALUATION_REPORT.md](evaluation/mocked/EVALUATION_REPORT.md) for metrics and [evaluation/README.md](evaluation/README.md) for commands. Historical root reports are preserved. These scripted results are not live model performance.

`tools/smoke_streamlit.py` started Streamlit, received a healthy response, submitted zero workflows with the quota disabled, stopped the process, and verified that the demo database was unchanged. `pip check` found no broken requirements on Python 3.11.0. `tools/audit_repository.py` found no credential patterns in publishable source and all required ignore rules passed. No project Git history exists locally; remote/prior history was not inspected.

## Deployment assertions actually exercised

All records and credentials in these tests are synthetic; no paid calls are made. The history test creates two disposable local Git commits to prove that a removed credential-shaped fixture is still detected without displaying its value.

| Test in `test_deployment.py` | Cases | Verified behavior |
| --- | ---: | --- |
| `test_cloud_secrets_environment_precedence_and_local_fallback` | 1 | Environment / Streamlit secrets / local file precedence; safe settings repr |
| `test_invalid_server_limits_fail_without_value_disclosure` | 4 | Invalid limits rejected without echoing sensitive values |
| `test_daily_quota_is_atomic_across_independent_threads` | 1 | Exactly five of twelve concurrent reservations succeed at quota five |
| `test_quota_is_shared_by_separate_python_processes` | 1 | A second process observes and respects the first reservation |
| `test_quota_uses_utc_days_and_zero_is_an_off_switch` | 1 | Day reset and zero-quota rejection |
| `test_quota_storage_failure_blocks_provider_call` | 1 | Storage failure fails closed before model request |
| `test_failed_provider_attempt_consumes_quota_and_exhaustion_is_safe` | 1 | Failed calls consume quota; later call blocked; safe errors and request caps |
| `test_configurable_execution_limit_and_oversized_input` | 1 | Changed round limit enforced; oversized input never initializes the client |
| `test_workflow_lock_rejects_overlap_and_rapid_repeated_requests` | 1 | Session concurrency lock and 30-second duplicate cooldown |
| `test_workflow_exception_releases_active_lease` | 1 | Failure releases the lease so a different workflow can start |
| `test_database_context_isolates_concurrent_session_records` | 1 | Concurrent contexts with overlapping employee IDs remain isolated; base database unchanged |
| `test_public_tool_policy_rejects_unlisted_people_resources_and_file_tools` | 1 | Synthetic-only fields/resources and fixed tool allowlist |
| `test_public_dashboard_presets_sessions_and_repeat_clicks` | 1 | Synthetic UI, separate AppTest sessions, duplicate click suppression, prior result retained |
| `test_credential_redaction_in_dashboard_and_model_logging` | 1 | Dashboard redaction and nested logging suppression |
| `test_gitignore_and_current_source_audit` | 1 | Required exclusions and publishable placeholder template |
| `test_history_audit_detects_deleted_secret_without_disclosure` | 1 | Deleted synthetic credential in temporary history detected without value output |

The actual CLI dry run also completed with no scenario execution or paid API calls. It loaded configuration without displaying credentials and previewed the 100-call / 1,024-output-token limit and conditional $42.06688 ceiling for GPT-4.1 mini. No live benchmark was run.

## Live-evaluation safety assertions actually exercised

All live-path tests below are offline. Synthetic SDK responses or an HTTP mock transport are used, never the real service or real API credentials. Environment-loading tests read temporary synthetic `.env` files.

| Test in `test_benchmark_safety.py` | Cases | Verified behavior |
| --- | ---: | --- |
| `test_dry_run_executes_nothing_and_requires_no_key` | 2 | Dry run with/without `--live` makes no client, scenario, database, or report calls |
| `test_dry_run_call_and_cost_math` | 1 | 24 agent invocations, 192 pre-cap rounds, zero approval API calls, global cap, pinned cost formula |
| `test_invalid_budgets_are_rejected` | 5 | Non-positive and boolean limits rejected |
| `test_unpriced_models_and_excessive_output_caps_reject_cost_claims` | 2 | Unsupported pricing model and invalid output cap rejected |
| `test_global_limit_counts_failed_calls_across_scenarios` | 1 | Shared limit, failed requests count, blocked later calls, approval tests continue, retries/output/n/tier settings |
| `test_real_sdk_has_no_hidden_retries_using_offline_transport` | 2 | Real SDK with HTTP mock transport sends once for success and rate-limit failure; a second request is blocked |
| `test_all_scenarios_in_live_wrapper_keep_temporary_database_isolation` | 1 | All 25 scenario scripts through the live wrapper, 25 temporary paths, cleanup, unchanged demo sentinel |
| `test_isolation_guard_blocks_an_attempt_to_restore_production_path` | 2 | Path escape blocked before connection in mocked and simulated-live modes |
| `test_dotenv_loading_is_allowlisted_noninterpolating_and_read_only` | 1 | Shell precedence, file key loading, no interpolation, allowlist, no secret output or file edits |
| `test_cli_loads_dotenv_for_dry_run_without_disclosing_key` | 1 | Synthetic file configuration used in CLI preview without key output |
| `test_provider_logging_is_suppressed_and_restored` | 1 | Noisy SDK constructor logs suppressed, log configuration restored, exception text not recorded |
| `test_mode_output_directories_and_overwrite_guards` | 1 | Distinct defaults, wrong-mode directories and existing opposite-mode reports rejected |
| `test_reports_redact_credentials_even_if_a_result_echoes_them` | 1 | Credential sentinel removed from CSV, JSON, and Markdown |

## Benchmark integrity assertions actually exercised

Tests in `test_benchmark.py` validate the evaluation infrastructure itself. Tests of the live-call wrapper use fake SDK clients and never contact OpenAI.

| Test | Cases | Verified behavior |
| --- | ---: | --- |
| `test_all_25_mocked_scenarios_are_isolated_and_reports_match` | 1 | All scenario categories and interfaces; 25 distinct temporary databases; file cleanup; patch restoration; unchanged protected sentinel; CSV/JSON/Markdown consistency; no credential output |
| `test_assertions_fail_when_mock_plan_produces_wrong_state` | 2 | Wrong role and missing resource fail independently specified assertions |
| `test_unexpected_scenario_exception_does_not_stop_remaining_scenarios` | 1 | Runner exception fails one scenario, later scenario passes, report contains sanitized failure details |
| `test_safe_abstention_is_not_invented_detection_success` | 2 | Generic no-actions responses do not pass missing-field or malformed-input detection assertions |
| `test_live_call_failure_never_falls_back_to_mock` | 2 | Simulated provider failure fails positive and missing-field scenarios with zero mock calls |
| `test_live_initialization_failure_is_recorded_without_mock_fallback` | 1 | Initialization error is recorded safely with no mock substitution |
| `test_live_observer_records_only_actual_usage_metadata` | 2 | Complete and incomplete supplied usage metadata produce correct token totals and coverage; no cost invented |
| `test_direct_approval_tests_do_not_use_a_model_even_in_live_mode` | 1 | All four direct approval scenarios avoid model initialization |
| `test_unexercised_fault_injection_cannot_pass` | 1 | An uninvoked fault cannot be reported as successfully tested |
| `test_metric_numerators_and_denominators_include_failures` | 2 | Failed cases stay in denominators; odd/even median and mean formulas |
| `test_invalid_scenario_catalog_is_rejected` | 3 | Duplicate IDs, incorrect category counts, and unknown assertion types are rejected |
| `test_live_cli_requires_credentials_after_environment_loading` | 1 | Explicit live command without credentials after the mocked configuration load exits with a configuration error |
| `test_production_file_change_is_reported_without_restoring_it` | 1 | A simulated external change to a temporary protected sentinel is detected and not overwritten |

## Database assertions actually exercised

Names below are pytest test functions in `test_db.py`. Counts include parameterized cases.

| Test | Cases | Verified behavior |
| --- | ---: | --- |
| `test_idempotent_workflow` | 1 | Existing employee/request retry and approval regression |
| `test_database_rejects_direct_duplicate_employee` | 1 | Direct SQL duplicate employee raises UNIQUE integrity error |
| `test_database_rejects_direct_duplicate_request` | 1 | Direct SQL duplicate resource raises UNIQUE integrity error |
| `test_database_enforces_foreign_key` | 1 | Direct SQL request for absent employee fails |
| `test_employee_retry_trims_whitespace_and_preserves_existing_profile` | 1 | Trimmed identity retrieves original role and manager |
| `test_same_name_with_different_start_date_is_distinct` | 1 | Different start dates retain separate identities |
| `test_missing_or_non_text_details_do_not_write` | 16 | Each field rejects null, empty, whitespace-only, and integer values; database bytes unchanged |
| `test_omitted_employee_details` | 4 | Each omitted field returns an error and creates no employee |
| `test_invalid_start_dates_do_not_write` | 9 | Invalid leap day, day, month, year, padding, slash format, compact format, ISO week date, and timestamp; database bytes unchanged |
| `test_valid_dates_including_leap_day_and_past_dates` | 2 | Valid leap day and past date accepted; outer whitespace trimmed |
| `test_each_resource_request_is_idempotent` | 3 | Laptop, email, and GitHub retries return one record and correct initial status |
| `test_unsupported_resource_does_not_write` | 4 | Unsupported, empty, null, and list kinds leave database bytes unchanged |
| `test_invalid_or_unknown_employee_cannot_be_used` | 7 | Zero, negative, boolean, string, null, float, and absent IDs rejected by request/read/approval; database bytes unchanged |
| `test_incorrect_approval_leaves_entire_database_unchanged` | 10 | Wrong, empty, whitespace, null, and numeric approvers cannot change pending or already-approved records; entire SQLite file compared byte-for-byte |
| `test_approval_without_github_does_not_write` | 1 | Correct manager cannot approve a missing GitHub request; database bytes unchanged |
| `test_approval_only_changes_target_and_retries_preserve_status` | 1 | Case/whitespace handling, repeated approval, approved request retry, unrelated resource and other employee preservation |
| `test_concurrent_duplicate_workflows_use_one_employee_and_request` | 1 | Twelve workflows on four threads return the same employee and request |
| `test_unrelated_integrity_failure_is_not_silently_ignored` | 1 | Synthetic trigger failure surfaces and creates no employee |
| `test_database_helpers_close_connections` | 1 | Initialization, create, read, list, rejected approval, and accepted approval close their connections |

## Agent assertions actually exercised

Tests in `test_agent.py` use scripted OpenAI responses with real database helpers, except where a tool is deliberately replaced to inject a failure or invalid return value.

| Test | Cases | Verified behavior |
| --- | ---: | --- |
| `test_success_uses_real_records_instead_of_false_model_claims` | 1 | Full synthetic onboarding, tool results sent back to model, verified pending statuses replace false provisioning claim |
| `test_automatic_verification_when_model_omits_readback` | 1 | Final read happens even when model omits it; profile-only summary |
| `test_repeated_agent_workflow_preserves_approved_resource` | 1 | Existing approved GitHub request is not duplicated or reset |
| `test_invalid_calls_stop_without_writes_or_false_success` | 11 | Unknown tool, malformed JSON, array/null arguments, missing/extra arguments, boolean/string IDs, non-text name, unsupported kind, absent employee; no writes or subsequent model call |
| `test_employee_validation_errors_skip_later_batch_calls` | 2 | Blank manager and invalid date stop later employee/resource creation in the same batch |
| `test_partial_writes_are_preserved_and_failure_is_explicit` | 1 | Earlier employee commit retained, later calls skipped, partial-outcome warning returned |
| `test_tool_exception_is_sanitized` | 1 | Tool exception sentinel absent from answer and trace |
| `test_invalid_tool_result_cannot_be_success` | 5 | Null, list, empty, incomplete, and empty-error results rejected |
| `test_failed_final_verification_is_not_success` | 1 | Failed readback prevents completion summary while preserving prior employee |
| `test_provider_failure_after_write_preserves_trace` | 1 | Prior write and trace retained; API exception sentinel hidden |
| `test_client_initialization_failure_is_safe` | 1 | Client setup failure reported without exception sentinel or writes |
| `test_malformed_provider_response_is_safe` | 1 | Empty choices reported as provider failure |
| `test_model_claims_without_tools_are_not_shown` | 1 | No-tool false success is replaced with no-actions response |
| `test_empty_input_does_not_initialize_client` | 3 | Empty, whitespace-only, and null input do not initialize client or create records |
| `test_execution_limit_is_explicit_and_retries_are_idempotent` | 1 | Eight-call limit returns failure, retaining one employee after repeated creation |

## Dashboard assertions actually exercised

| Test in `test_app.py` | Cases | Verified behavior |
| --- | ---: | --- |
| `test_workflow_approval_and_trace_survive_reruns` | 1 | Empty and populated metrics, wrong and correct approval, 50% to 75% milestones, collapsed trace persists, approval control disappears afterward |
| `test_directory_filters_and_employee_selection` | 1 | Approval/no-resource filters, selected employee updates, empty search results |
| `test_blank_request_and_safe_provider_error` | 1 | Blank submission warning and safe unexpected workflow exception display |
| `test_failed_tool_report_is_visible_and_trace_remains_collapsed` | 1 | Failed result displays as error, no success alert, collapsed trace and failure persist after refresh |

## Limits of this evidence and remaining behavior

- No live OpenAI requests were made. Extraction accuracy, remote authentication, outages, and rate limits were not tested against the real service. Provider failures above are injected exceptions.
- Dashboard checks use Streamlit AppTest with a mocked `run_agent`; browser rendering, responsive layout, and real browser sessions were not tested.
- Individual database operations commit independently. Workflow-wide rollback is not implemented; partial commits are explicitly tested and reported.
- Manager approval remains a name-based, unauthenticated simulator. No real provisioning occurs.
- Existing identity rules remain case-sensitive name plus start date. Historical schemas/data are not migrated or cleaned up. Arbitrary legacy schema compatibility is not tested.
- Validation applies to helper/tool inputs; direct SQL can bypass field/date validation. SQL uniqueness and foreign keys are tested separately.
- Concurrency evidence is limited to twelve workflows on four threads. Cross-process contention, crash recovery, disk failures, and production load were not tested.
- No schema changes, dependency additions, or `.env` edits were made.
