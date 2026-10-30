"""Run scripted or explicitly opted-in live evaluations without changing the app."""
import argparse
import csv
import hashlib
import json
import logging
import math
import os
import platform
import shlex
import sqlite3
import statistics
import sys
import tempfile
import time
from collections import Counter
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import agent
import db
import dotenv
import runtime_config
from openai.types.chat import ChatCompletionMessage

SCENARIOS_PATH = Path(__file__).with_name('scenarios.json')
PRODUCTION_DB = ROOT / 'flowpilot.db'
PRICING_PATH = Path(__file__).with_name('pricing.json')
DEFAULT_MAX_API_CALLS = 100
DEFAULT_MAX_COMPLETION_TOKENS = 1024
AGENT_MAX_ROUNDS = 8  # Reviewed against agent.run_agent; global budget is enforced separately.
CATEGORY_COUNTS = {
    'successful': 5, 'duplicate': 4, 'missing_information': 4,
    'invalid_input': 4, 'approval_authorization': 4, 'robustness': 4,
}
ASSERTION_TYPES = {
    'employee_count', 'employee_details', 'request_statuses', 'unique_records',
    'no_errors', 'verified_readback', 'unchanged_after_actions', 'validation_error',
    'approval_results', 'injected_failure_observed', 'failure_reported',
    'no_successful_resource_calls',
}
LIMITATIONS = [
    'Mocked mode scripts model tool calls; it measures workflow/validation behavior, not LLM extraction, reasoning quality, latency, or live success rate.',
    'The overall rate pools 21 agent scenarios and 4 direct approval API tests. Separate interface rates are included; approval tests never use OpenAI, even in live mode.',
    'Rejection scenarios require a specific tool-validation error plus the expected database state. The current agent hides model clarification text behind a generic no-actions response. Safe abstention without a specific error is unobservable for detection and is not counted as a pass.',
    'I03 scripts malformed tool arguments in mocked mode. Live mode sends the malformed user request, which need not produce malformed tool arguments. These exercise different layers and are explicitly labeled.',
    'The injected create_request failure applies in both modes; its invocation is asserted. It does not simulate every possible network, storage, or provisioning failure.',
    'Each scenario has its own temporary SQLite database. Multi-step actions within a scenario share that database. Individual application actions commit independently; partial writes can remain after a failure.',
    'Approval remains an unauthenticated name-matching simulator. No resources are actually provisioned; no production authorization claim is made.',
    'Only 25 synthetic scenarios are evaluated. There is no statistical generalization to real workloads, and no browser, production load, concurrency, or crash-recovery benchmark.',
    'All dates in requests are absolute. Mock tool scripts are deterministic; wall times and live model responses are not. The application still supplies its current date to the model.',
    'Live SDK retries are disabled. A shared run-wide request budget counts failed attempts too. Output tokens and completion count are capped, and the standard service tier is requested. Exhaustion fails affected agent scenarios; direct approval tests still run.',
    'The cost ceiling uses the pinned pricing catalog and the full model context window as uncached input on every allowed call, plus capped output. It is deliberately pessimistic, excludes tax, and is conditional on the published model limits/prices. It is not an account-wide billing limit.',
    'CLI live/dry runs securely read allowlisted settings from the repository .env without interpolation or overriding existing environment variables. The file is never changed. Never run this in the same Python process as a serving dashboard because isolation temporarily patches module state.',
    'The production database fingerprint is checked before and after the run. An external dashboard write during evaluation can change that fingerprint; the runner reports this and never restores or overwrites the production file.',
]


@contextmanager
def quiet_sensitive_operations():
    """Prevent SDK/HTTP/dotenv debug configuration from logging credentials."""
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(previous)


def load_environment(path=None):
    """Read existing settings, never mutate the file or expand secrets into values."""
    with quiet_sensitive_operations():
        values = dotenv.dotenv_values(path or ROOT / '.env', interpolate=False, verbose=False)
    for name in ('OPENAI_API_KEY', 'OPENAI_MODEL', 'OPENAI_ORG_ID', 'OPENAI_PROJECT_ID'):
        if values.get(name) is not None:
            os.environ.setdefault(name, values[name])


def redact(value):
    secrets = [os.environ[name] for name in ('OPENAI_API_KEY', 'OPENAI_ADMIN_KEY') if os.environ.get(name)]
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, '[REDACTED]')
        return value
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        return {redact(key): redact(item) for key, item in value.items()}
    return value


class ApiCallLimitError(RuntimeError):
    pass


@dataclass
class ApiBudget:
    max_api_calls: int = DEFAULT_MAX_API_CALLS
    max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS
    model: str = ''
    attempted_calls: int = 0
    blocked_calls: int = 0

    def __post_init__(self):
        if type(self.max_api_calls) is not int or self.max_api_calls <= 0:
            raise ValueError('Maximum API calls must be a positive integer')
        if type(self.max_completion_tokens) is not int or self.max_completion_tokens <= 0:
            raise ValueError('Maximum completion tokens must be a positive integer')
        self.model = self.model or os.getenv('OPENAI_MODEL', 'gpt-4.1-mini')

    def reserve(self):
        if self.attempted_calls >= self.max_api_calls:
            self.blocked_calls += 1
            raise ApiCallLimitError('Global API-call limit reached; no request sent')
        # Reserve before sending; timeouts and provider failures are never refunded.
        self.attempted_calls += 1

    def as_dict(self):
        return {'max_api_calls': self.max_api_calls, 'attempted_calls': self.attempted_calls,
                'blocked_calls': self.blocked_calls, 'max_completion_tokens': self.max_completion_tokens,
                'model': self.model, 'max_retries': 0, 'n': 1, 'service_tier': 'default',
                'base_url': 'https://api.openai.com/v1'}


def cost_ceiling(budget, pricing_path=PRICING_PATH):
    catalog = json.loads(Path(pricing_path).read_text(encoding='utf-8'))
    profile = catalog['models'].get(budget.model)
    if profile is None:
        raise ValueError('Selected model has no pinned pricing/context profile. Supply a reviewed --pricing-file or select a covered --model.')
    if catalog.get('currency') != 'USD' or catalog.get('service_tier') != 'default':
        raise ValueError('Pricing must describe standard-tier USD token prices')
    for key in ('context_window_tokens', 'max_output_tokens'):
        if type(profile.get(key)) is not int or profile[key] <= 0:
            raise ValueError('Pricing requires positive integer model token limits')
    for key in ('input_per_million', 'output_per_million'):
        if type(profile.get(key)) not in (int, float) or not math.isfinite(profile[key]) or profile[key] < 0:
            raise ValueError('Pricing requires finite, non-negative token rates')
    if budget.max_completion_tokens > min(profile['max_output_tokens'], profile['context_window_tokens']):
        raise ValueError('Completion token cap exceeds the selected model limit')
    per_call = (profile['context_window_tokens'] * profile['input_per_million']
                + budget.max_completion_tokens * profile['output_per_million']) / 1_000_000
    return {'estimated_upper_bound_usd': budget.max_api_calls * per_call, 'per_call_upper_bound_usd': per_call,
            'max_api_calls': budget.max_api_calls, 'max_completion_tokens': budget.max_completion_tokens,
            'model': budget.model, 'profile': profile, 'verified_on': catalog['verified_on'], 'source': catalog['source'],
            'assumptions': catalog['assumptions']}


def dry_run_plan(scenarios, budget, pricing_path=PRICING_PATH):
    round_limit = runtime_config.get_settings().max_model_calls
    rows = []
    for scenario in scenarios:
        is_agent = scenario['interface'] == 'agent'
        rows.append({'id': scenario['id'], 'title': scenario['title'], 'interface': scenario['interface'],
                     'agent_invocations': len(scenario['actions']) if is_agent else 0,
                     'script_plan_rounds_upper_bound': sum(min(round_limit, len(a['mock_tool_batches']) + 1)
                                                           for a in scenario['actions']) if is_agent else 0,
                     'live_api_calls_upper_bound_before_global_cap': round_limit * len(scenario['actions']) if is_agent else 0})
    return {'dry_run': True, 'scenarios': rows, 'controls': budget.as_dict(),
            'live_api_calls_upper_bound': min(budget.max_api_calls, sum(row['live_api_calls_upper_bound_before_global_cap'] for row in rows)),
            'cost_ceiling': cost_ceiling(budget, pricing_path),
            'note': 'No scenarios, database operations, or API calls executed. Script-plan counts are reference maxima, not measured or predicted live usage. Live calls can be fewer due to refusals, errors, or the global limit.'}


def resolve_output_dir(base, live):
    mode = 'live' if live else 'mocked'
    base = Path(base).resolve()
    if base.name in ('live', 'mocked'):
        if base.name != mode:
            raise ValueError('Output directory belongs to the other execution mode')
        return base
    return base / mode


def validate_report_destination(path, mode):
    path = Path(path).resolve()
    if path.name in ('live', 'mocked') and path.name != mode:
        raise ValueError('Refusing to write reports into the other execution mode directory')
    summary_path = path / 'summary.json'
    if summary_path.exists():
        old = json.loads(summary_path.read_text(encoding='utf-8'))
        if old.get('mode') != mode:
            raise ValueError('Refusing to overwrite reports from another execution mode')
    # Report file links must not redirect writes into a protected file or other mode.
    for name in ('summary.json', 'results.csv', 'EVALUATION_REPORT.md'):
        target = path / name
        if target.is_symlink() or target.resolve() == PRODUCTION_DB.resolve():
            raise ValueError('Unsafe report destination')
        if target.exists() and (target.stat().st_nlink > 1 or (PRODUCTION_DB.exists() and target.samefile(PRODUCTION_DB))):
            raise ValueError('Linked report files cannot be overwritten')


def fingerprint(path):
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            digest.update(block)
    return digest.hexdigest()


def load_scenarios(path=SCENARIOS_PATH):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    scenarios = data['scenarios']
    if data.get('schema_version') != 1 or Counter(s['category'] for s in scenarios) != CATEGORY_COUNTS:
        raise ValueError('Expected schema version 1 and the documented 25-scenario category distribution')
    if len({s['id'] for s in scenarios}) != len(scenarios):
        raise ValueError('Scenario IDs must be unique')
    for scenario in scenarios:
        for field in ('id', 'title', 'input_request', 'expected_outcome'):
            if not isinstance(scenario.get(field), str) or not scenario[field]:
                raise ValueError('Every scenario needs non-empty descriptive fields')
        interface = scenario['interface']
        if interface not in ('agent', 'approval_api'):
            raise ValueError('Unknown scenario interface')
        if (interface == 'approval_api') != (scenario['category'] == 'approval_authorization'):
            raise ValueError('Approval scenarios must explicitly use the approval API')
        if not scenario['actions'] or not scenario['assertions']:
            raise ValueError('Actions and explicit assertions are required')
        if any(item['type'] not in ASSERTION_TYPES for item in scenario['assertions']):
            raise ValueError('Unknown assertion type')
        if interface == 'agent':
            for action in scenario['actions']:
                if not isinstance(action['request'], str) or not isinstance(action['mock_tool_batches'], list):
                    raise ValueError('Agent actions require a request and explicit mock tool batches')
    return scenarios


class ModelRecorder:
    """Observe the SDK boundary; never replace a failed live call with a mock."""
    def __init__(self, budget=None):
        self.budget = budget or ApiBudget()
        self.mock_calls = 0
        self.live_calls = 0
        self.live_responses = 0
        self.usage = []
        self.errors = []
        self.clients = []

    def mock_factory(self, action):
        batches = iter(action['mock_tool_batches'])

        def create(**kwargs):
            self.mock_calls += 1
            batch = next(batches, None)
            calls = None if batch is None else [
                {'id': f'benchmark_{self.mock_calls}_{index}', 'type': 'function',
                 'function': {'name': call['tool'], 'arguments': (
                     call['arguments'] if isinstance(call['arguments'], str)
                     else json.dumps(call['arguments'])
                 )}}
                for index, call in enumerate(batch)
            ]
            message = ChatCompletionMessage(
                role='assistant', content='Scripted benchmark response; not a live model result.', tool_calls=calls,
            )
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        return lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    def live_factory(self, original_factory):
        def factory(**client_options):
            try:
                with quiet_sensitive_operations():
                    client = original_factory(max_retries=0, timeout=60.0, base_url='https://api.openai.com/v1')
            except Exception as exc:
                self.errors.append({'stage': 'client_initialization', 'exception_type': type(exc).__name__})
                raise
            self.clients.append(client)

            def create(**kwargs):
                try:
                    self.budget.reserve()
                except ApiCallLimitError:
                    self.errors.append({'stage': 'api_call_limit', 'exception_type': 'ApiCallLimitError'})
                    raise
                kwargs.update(model=self.budget.model, max_completion_tokens=self.budget.max_completion_tokens,
                              n=1, service_tier='default', stream=False)
                self.live_calls += 1
                try:
                    with quiet_sensitive_operations():
                        response = client.chat.completions.create(**kwargs)
                except Exception as exc:
                    self.errors.append({'stage': 'model_response', 'exception_type': type(exc).__name__})
                    raise
                self.live_responses += 1
                usage = getattr(response, 'usage', None)
                counts = [getattr(usage, key, None) for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')]
                if all(type(value) is int and value >= 0 for value in counts) and counts[2] == counts[0] + counts[1]:
                    self.usage.append(dict(zip(('prompt_tokens', 'completion_tokens', 'total_tokens'), counts)))
                return response

            return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        return factory

    def close(self):
        for client in self.clients:
            try:
                with quiet_sensitive_operations():
                    client.close()
            except Exception as exc:
                self.errors.append({'stage': 'client_cleanup', 'exception_type': type(exc).__name__})

    def as_dict(self):
        return {
            'mock_model_calls': self.mock_calls, 'live_sdk_calls': self.live_calls,
            'live_responses': self.live_responses, 'responses_with_usage': len(self.usage),
            'observed_tokens': {key: sum(item[key] for item in self.usage)
                                for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')} if self.usage else None,
            'errors': self.errors,
        }


def snapshot():
    return [db.get_onboarding(employee['id']) for employee in sorted(db.list_onboardings(), key=lambda e: e['id'])]


def apply_setup(setup):
    if not setup:
        return
    employee = db.create_employee(**setup['employee'])
    if 'error' in employee:
        raise RuntimeError('Synthetic setup failed')
    for kind in setup.get('resources', []):
        if 'error' in db.create_request(employee['id'], kind):
            raise RuntimeError('Synthetic resource setup failed')
    if setup.get('approve') and 'error' in db.approve_github(employee['id'], employee['manager']):
        raise RuntimeError('Synthetic approval setup failed')


def check_assertion(spec, evidence):
    actions, state = evidence['actions'], evidence['final_state']
    trace = [entry for action in actions for entry in action.get('trace', [])]
    requests = [request for record in state for request in record['requests']]
    kind = spec['type']
    note = ''
    if kind == 'employee_count':
        observed = len(state)
        passed = observed in spec.get('allowed', [spec.get('equals')])
    elif kind == 'employee_details':
        observed = [record['employee'] for record in state]
        passed = (bool(state) or spec.get('allow_absent', False)) and all(
            all(record['employee'].get(key) == value for key, value in spec['equals'].items()) for record in state
        )
    elif kind == 'request_statuses':
        observed = sorted([[request['kind'], request['status']] for request in requests])
        passed = observed == sorted([list(pair) for pair in spec['equals'].items()])
    elif kind == 'unique_records':
        employees = [(record['employee']['name'], record['employee']['start_date']) for record in state]
        identities = [(request['employee_id'], request['kind']) for request in requests]
        observed = {'employees': len(employees), 'unique_employees': len(set(employees)),
                    'requests': len(identities), 'unique_requests': len(set(identities))}
        passed = len(employees) == len(set(employees)) and len(identities) == len(set(identities))
    elif kind == 'no_errors':
        observed = [entry['result']['error'] for entry in trace if 'error' in entry.get('result', {})]
        passed = not observed
    elif kind == 'verified_readback':
        observed = []
        for action in actions:
            verified = [entry['result'] for entry in action.get('trace', []) if entry.get('source') == 'verification']
            observed.append(bool(verified) and verified == action['after'])
        passed = bool(observed) and all(observed)
    elif kind == 'unchanged_after_actions':
        observed = [
            actions[index]['bytes_unchanged'] if spec.get('byte_for_byte')
            else actions[index]['before'] == actions[index]['after']
            for index in spec['indexes']
        ]
        passed = all(observed)
    elif kind == 'validation_error':
        observed = [entry['result']['error'] for entry in trace
                    if 'tool' in entry and 'error' in entry.get('result', {})]
        passed = any(spec['contains'].casefold() in error.casefold() for error in observed)
        if not passed:
            note = 'Required validation signal not observed. Generic no-actions text is insufficient evidence of detection.'
    elif kind == 'approval_results':
        observed = ['error' if 'error' in action['approval_result'] else action['approval_result'].get('status') for action in actions]
        passed = observed == spec['equals']
    elif kind == 'injected_failure_observed':
        observed = evidence['injected_failure_calls']
        passed = observed > 0 and any('Tool execution failed' in entry.get('result', {}).get('error', '') for entry in trace)
    elif kind == 'failure_reported':
        observed = [action.get('answer', '').startswith('Workflow stopped:') for action in actions]
        passed = bool(observed) and all(observed)
    elif kind == 'no_successful_resource_calls':
        observed = sum(entry.get('tool') == 'create_request' and 'error' not in entry['result'] for entry in trace)
        passed = observed == 0
    else:
        raise ValueError('Unknown benchmark assertion')
    return {'type': kind, 'passed': bool(passed), 'expected': spec, 'observed': observed, 'note': note}


def run_scenario(scenario, live=False, budget=None):
    started = time.perf_counter()
    recorder = ModelRecorder(budget)
    row = {
        'id': scenario['id'], 'category': scenario['category'], 'title': scenario['title'],
        'interface': scenario['interface'],
        'execution_mode': ('live' if live else 'mocked') if scenario['interface'] == 'agent' else 'direct_approval_api',
        'expected_outcome': scenario['expected_outcome'], 'actions': [], 'assertions': [],
        'final_state': [], 'injected_failure_calls': 0, 'errors': [],
    }
    original_factory = agent.OpenAI
    try:
        with tempfile.TemporaryDirectory(prefix='flowpilot-eval-') as directory:
            temporary_db = Path(directory) / 'scenario.db'
            if temporary_db.resolve() == PRODUCTION_DB.resolve():
                raise RuntimeError('Unsafe database path')
            with ExitStack() as stack:
                stack.enter_context(patch.object(db, 'DB_PATH', temporary_db))
                # Evaluation never consumes the app's production quota/lease database.
                stack.enter_context(runtime_config.use_settings(replace(
                    runtime_config.get_settings(), data_dir=Path(directory) / 'runtime', public_demo=False,
                )))
                original_connect = db.connect

                def isolated_connect():
                    if Path(db.DB_PATH).resolve() != temporary_db.resolve():
                        raise RuntimeError('Database isolation guard rejected an unexpected path')
                    return original_connect()

                stack.enter_context(patch.object(db, 'connect', isolated_connect))
                db.init_db()
                apply_setup(scenario.get('setup'))
                if scenario.get('fault_injection'):
                    tool = scenario['fault_injection']['tool']
                    if tool != 'create_request':
                        raise ValueError('Unsupported fault injection')

                    def fail_resource(**kwargs):
                        row['injected_failure_calls'] += 1
                        raise RuntimeError('Synthetic benchmark resource failure')

                    stack.enter_context(patch.dict(agent.FUNCTIONS, {tool: fail_resource}))
                for action in scenario['actions']:
                    before = snapshot()
                    before_bytes = fingerprint(temporary_db)
                    if scenario['interface'] == 'agent':
                        factory = recorder.live_factory(original_factory) if live else recorder.mock_factory(action)
                        with patch.object(agent, 'OpenAI', factory):
                            answer, trace = agent.run_agent(action['request'])
                        action_result = {'request': action['request'], 'answer': answer, 'trace': trace}
                        row['errors'].extend(entry['result']['error'] for entry in trace if 'error' in entry.get('result', {}))
                    else:
                        result = db.approve_github(action['employee_id'], action['approver'])
                        action_result = {'approval_input': action, 'approval_result': result}
                        if 'error' in result:
                            row['errors'].append(result['error'])
                    action_result.update(before=before, after=snapshot(), bytes_unchanged=before_bytes == fingerprint(temporary_db))
                    row['actions'].append(action_result)
                row['final_state'] = snapshot()
                row['assertions'] = [check_assertion(spec, row) for spec in scenario['assertions']]
                infrastructure_errors = [entry for action in row['actions'] for entry in action.get('trace', [])
                                         if entry.get('event') in ('provider_error', 'execution_limit')]
                row['assertions'].append({'type': 'no_provider_or_execution_limit_failure', 'passed': not infrastructure_errors,
                                          'observed': infrastructure_errors})
    except Exception as exc:
        # Raw exceptions may contain API credentials or provider response bodies.
        row['errors'].append(f'Benchmark execution raised {type(exc).__name__}; exception details suppressed.')
        row['assertions'].append({'type': 'scenario_completed', 'passed': False, 'observed': type(exc).__name__})
    finally:
        recorder.close()
    row['api_usage'] = recorder.as_dict()
    if recorder.errors:
        row['assertions'].append({'type': 'no_sdk_failure', 'passed': False, 'observed': recorder.errors})
        if any(error['stage'] == 'api_call_limit' for error in recorder.errors):
            row['errors'].append('Global API-call limit reached; further API calls were blocked.')
    row['status'] = 'passed' if row['assertions'] and all(item['passed'] for item in row['assertions']) else 'failed'
    row['failed_assertions'] = [item for item in row['assertions'] if not item['passed']]
    row['duration_seconds'] = time.perf_counter() - started
    return redact(row)


def rate(rows):
    numerator = sum(row['status'] == 'passed' for row in rows)
    return {'numerator': numerator, 'denominator': len(rows), 'value': numerator / len(rows) if rows else None}


def summarize(rows, live, command, production_unchanged):
    durations = sorted(row['duration_seconds'] for row in rows)
    middle = durations[len(durations) // 2:len(durations) // 2 + 1] if len(durations) % 2 else durations[len(durations) // 2 - 1:len(durations) // 2 + 1]
    category_rates = {category: rate([row for row in rows if row['category'] == category]) for category in CATEGORY_COUNTS}
    usage_rows = [row['api_usage'] for row in rows]
    live_calls = sum(item['live_sdk_calls'] for item in usage_rows)
    with_usage = sum(item['responses_with_usage'] for item in usage_rows)
    observed_tokens = {
        key: sum((item['observed_tokens'] or {}).get(key, 0) for item in usage_rows)
        for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')
    } if with_usage else None
    return {
        'benchmark_version': 2, 'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'mode': 'live' if live else 'mocked', 'command': command, 'working_directory': str(Path.cwd()),
        'production_database_unchanged': production_unchanged,
        'environment': {'python': platform.python_version(), 'platform': platform.platform(),
                        'sqlite': sqlite3.sqlite_version, 'openai': version('openai'), 'streamlit': version('streamlit'),
                        'configured_live_model': os.getenv('OPENAI_MODEL', 'gpt-4.1-mini'),
                        'source_sha256': {name: fingerprint(ROOT / name) for name in ('agent.py', 'db.py', 'app.py', 'runtime_config.py', 'safeguards.py', 'demo_scenarios.py')},
                        'scenarios_sha256': fingerprint(SCENARIOS_PATH)},
        'metrics': {
            'overall_pass_rate': rate(rows), 'category_pass_rates': category_rates,
            'interface_pass_rates': {interface: rate([row for row in rows if row['interface'] == interface]) for interface in ('agent', 'approval_api')},
            'duplicate_prevention_success_rate': category_rates['duplicate'],
            'missing_field_detection_success_rate': category_rates['missing_information'],
            'invalid_input_rejection_rate': category_rates['invalid_input'],
            'approval_safety_success_rate': category_rates['approval_authorization'],
            'average_execution_seconds': {'numerator': sum(durations), 'denominator': len(durations),
                                          'value': statistics.mean(durations) if durations else None},
            'median_execution_seconds': {'numerator': sum(middle), 'denominator': len(middle),
                                         'value': statistics.median(durations) if durations else None, 'sample_count': len(durations)},
        },
        'api_usage': {
            'mock_model_calls': sum(item['mock_model_calls'] for item in usage_rows),
            'live_sdk_calls': live_calls, 'live_responses': sum(item['live_responses'] for item in usage_rows),
            'usage_coverage': {'numerator': with_usage, 'denominator': live_calls},
            'observed_tokens': observed_tokens,
            'usage_complete': bool(live_calls) and with_usage == live_calls and not any(item['errors'] for item in usage_rows),
            'cost_estimate_usd': None,
            'cost_note': 'Actual billed cost is not inferred from partial usage. Mocked calls have no provider usage. Live cost ceilings and pinned pricing assumptions are reported separately under safety_controls.',
        },
        'limitations': LIMITATIONS, 'scenarios': rows,
    }


def run_benchmark(scenarios, live=False, command='', progress=False, budget=None, ceiling=None):
    budget = budget or ApiBudget()
    before = fingerprint(PRODUCTION_DB)
    rows = []
    for scenario in scenarios:
        row = run_scenario(scenario, live=live, budget=budget)
        rows.append(row)
        if progress:
            print(f"{row['id']}: {row['status']} ({row['execution_mode']}, {row['duration_seconds']:.3f}s)", flush=True)
    summary = summarize(rows, live, command, fingerprint(PRODUCTION_DB) == before)
    summary['environment']['configured_live_model'] = budget.model
    summary['safety_controls'] = {'enforced_for_live_calls': live, **budget.as_dict(), 'cost_ceiling': ceiling}
    return redact(summary)


def percent(metric):
    if not metric['denominator']:
        return 'N/A (0/0)'
    return f"{metric['numerator']}/{metric['denominator']} ({metric['value']:.1%})"


def markdown_report(summary):
    metrics = summary['metrics']
    lines = [
        '# FlowPilot AI evaluation benchmark', '',
        f"Mode: **{summary['mode']}**. These results are {'scripted workflow tests, not live LLM performance' if summary['mode'] == 'mocked' else 'live agent calls plus separately labeled direct approval tests'}.", '',
        f"Generated: {summary['generated_at_utc']}", '',
        f"Production database fingerprint unchanged: **{summary['production_database_unchanged']}**.", '',
        '## Reproduce this run', '', 'Run from: `' + summary['working_directory'] + '`', '',
        '```powershell' if os.name == 'nt' else '```sh', summary['command'], '```', '',
        '## Metrics', '', '| Metric | Numerator / denominator |', '| --- | --- |',
    ]
    for name in ('overall_pass_rate', 'duplicate_prevention_success_rate', 'missing_field_detection_success_rate', 'invalid_input_rejection_rate', 'approval_safety_success_rate'):
        lines.append(f"| {name.replace('_', ' ')} | {percent(metrics[name])} |")
    for category, metric in metrics['category_pass_rates'].items():
        lines.append(f'| Category: {category} | {percent(metric)} |')
    for interface, metric in metrics['interface_pass_rates'].items():
        lines.append(f'| Interface: {interface} | {percent(metric)} |')
    for name in ('average_execution_seconds', 'median_execution_seconds'):
        metric = metrics[name]
        value = f"{metric['value']:.6f}s" if metric['value'] is not None else 'N/A'
        lines.append(f"| {name.replace('_', ' ')} | {metric['numerator']:.6f}s / {metric['denominator']} = {value} |")
    lines.extend([
        '', 'Rate denominators include all scenarios in the named group, including failures. Specialized rates require every assertion in that category to pass.',
        'Average time is total scenario wall time / scenario count. Median is the middle value (or sum of two middle values) / middle-value count; '
        f"its sample size is {metrics['median_execution_seconds']['sample_count']}. Timings include temporary database setup, actions, checks, client closure, and cleanup; imports and report writing are excluded.", '',
        '## Scenario results', '', '| ID | Category | Interface / mode | Result | Seconds | Failed assertions |', '| --- | --- | --- | --- | ---: | --- |',
    ])
    for row in summary['scenarios']:
        failed = ', '.join(item['type'] for item in row['failed_assertions']) or 'None'
        lines.append(f"| {row['id']} | {row['category']} | {row['interface']} / {row['execution_mode']} | {row['status']} | {row['duration_seconds']:.6f} | {failed} |")
    lines.extend(['', '## Failed scenario details', ''])
    failures = [row for row in summary['scenarios'] if row['status'] == 'failed']
    if not failures:
        lines.append('None. Expected negative-case errors were observed and asserted; they are not benchmark failures.')
    for row in failures:
        lines.extend([f"### {row['id']}: {row['title']}", '', row['expected_outcome'], '', '```json',
                      json.dumps({'failed_assertions': row['failed_assertions'], 'observed_errors': row['errors']}, indent=2, ensure_ascii=True), '```', ''])
    lines.extend(['', '## Methodology', '',
        'Each scenario runs actual agent.run_agent or db.approve_github against a fresh temporary SQLite file. The dashboard is not imported. Setup uses existing database helpers. All names and data are fictional.',
        'Mock mode replaces only the OpenAI client with explicit tool-call scripts stored separately from assertions in scenarios.json. Tool dispatch, validation, writes, readback, and approval all use application logic. Live mode ignores those scripts and wraps the real OpenAI client to observe usage and enforce request/output budgets; errors never fall back to mocks.',
        'Pass/fail checks compare employee fields, exact resource/status multisets, IDs and state across retries, approval results, validation errors, and verification traces. Rejected approvals additionally compare database file fingerprints. Provider errors and execution-limit failures always fail the scenario, even when no writes occurred.',
        'Full assertion evidence, per-action states, tool traces, and expected errors are stored in summary.json. results.csv provides a compact machine-readable table.', '',
        '## API usage and cost', '', '```json', json.dumps(summary['api_usage'], indent=2), '```', '',
        '## Live safety controls', '', '```json', json.dumps(summary.get('safety_controls', {}), indent=2), '```', '',
        '## Environment', '', '```json', json.dumps(summary['environment'], indent=2), '```', '',
        '## Limitations', '',
    ])
    lines.extend('- ' + limitation for limitation in summary['limitations'])
    return '\n'.join(lines) + '\n'


def write_reports(summary, output_dir):
    summary = redact(summary)
    output_dir = Path(output_dir)
    validate_report_destination(output_dir, summary['mode'])
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=True) + '\n', encoding='utf-8')
    fields = ['id', 'category', 'interface', 'execution_mode', 'status', 'duration_seconds',
              'assertions_passed', 'assertions_total', 'failed_assertions', 'errors', 'mock_model_calls', 'live_sdk_calls']
    with (output_dir / 'results.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in summary['scenarios']:
            writer.writerow({**{key: row[key] for key in fields[:6]},
                             'assertions_passed': sum(item['passed'] for item in row['assertions']),
                             'assertions_total': len(row['assertions']),
                             'failed_assertions': json.dumps(row['failed_assertions']), 'errors': json.dumps(row['errors']),
                             'mock_model_calls': row['api_usage']['mock_model_calls'], 'live_sdk_calls': row['api_usage']['live_sdk_calls']})
    (output_dir / 'EVALUATION_REPORT.md').write_text(markdown_report(summary), encoding='utf-8')


def reproduction_command():
    parts = [sys.executable, *sys.argv]
    if os.name == 'nt':
        return '& ' + ' '.join("'" + part.replace("'", "''") + "'" for part in parts)
    return shlex.join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Explicitly enable paid OpenAI calls; no mock fallback')
    parser.add_argument('--dry-run', action='store_true', help='Preview scenarios, call limits, and conservative live cost ceiling; execute nothing')
    parser.add_argument('--max-api-calls', type=int, default=DEFAULT_MAX_API_CALLS, help='Run-wide live request limit, including failed attempts (default: 100)')
    parser.add_argument('--max-completion-tokens', type=int, default=DEFAULT_MAX_COMPLETION_TOKENS, help='Maximum output tokens per live call (default: 1024)')
    parser.add_argument('--model', help='Explicit model override; otherwise use OPENAI_MODEL or the application default')
    parser.add_argument('--pricing-file', type=Path, default=PRICING_PATH, help='Reviewed USD pricing and context-limit catalog for the cost ceiling')
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).parent,
                        help='Report base directory; a separate mocked/ or live/ subdirectory is enforced')
    args = parser.parse_args()
    scenarios = load_scenarios()
    try:
        if args.live or args.dry_run:
            load_environment()
        budget = ApiBudget(args.max_api_calls, args.max_completion_tokens, args.model or '')
        ceiling = cost_ceiling(budget, args.pricing_file) if args.live or args.dry_run else None
        output_dir = resolve_output_dir(args.output_dir, args.live)
        validate_report_destination(output_dir, 'live' if args.live else 'mocked')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(redact('Configuration rejected: ' + type(exc).__name__ + '. Check model pricing, positive limits, and output mode.'))
    if args.dry_run:
        plan = dry_run_plan(scenarios, budget, args.pricing_file)
        print('DRY RUN: no API calls, scenarios, database writes, or report writes. Previewing LIVE costs.')
        print('ID   Interface       Script reference max   Live max before global cap   Scenario')
        for row in plan['scenarios']:
            print(f"{row['id']:4} {row['interface']:15} {row['script_plan_rounds_upper_bound']:20} {row['live_api_calls_upper_bound_before_global_cap']:28}   {row['title']}")
        print(json.dumps(redact({key: value for key, value in plan.items() if key != 'scenarios'}), indent=2))
        return 0
    if args.live and not os.getenv('OPENAI_API_KEY'):
        parser.error('Live mode requires OPENAI_API_KEY in the environment or repository .env.')
    summary = run_benchmark(scenarios, live=args.live, command=reproduction_command(), progress=True, budget=budget, ceiling=ceiling)
    write_reports(summary, output_dir)
    overall = summary['metrics']['overall_pass_rate']
    print(redact(f"{summary['mode']} benchmark: {percent(overall)}. Reports: {output_dir}"))
    return 0 if overall['numerator'] == overall['denominator'] and summary['production_database_unchanged'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
