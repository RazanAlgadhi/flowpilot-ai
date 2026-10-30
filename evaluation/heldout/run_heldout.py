"""Frozen held-out agent evaluation. Default: offline preflight; --live spends credits."""
import argparse
import ast
import csv
import hashlib
import json
import platform
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from contextlib import ExitStack
from dataclasses import replace
from datetime import date, datetime, timezone
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import agent
import db
import runtime_config as config
from evaluation import run_benchmark as common

HERE = Path(__file__).resolve().parent
SCENARIOS = HERE / 'scenarios.json'
PROTOCOL = HERE / 'protocol.json'
AMENDMENT = HERE / 'protocol_remaining.json'
REPORT_FILES = ('results.csv', 'summary.json', 'EVALUATION_REPORT.md')
CATEGORIES = {'straightforward': 4, 'language_variation': 4, 'challenging': 3, 'invalid_or_unsupported': 4}
FIELDS = ('name', 'role', 'start_date', 'manager')
STATUSES = {'laptop': 'requested', 'email': 'requested', 'github': 'pending_manager_approval'}
FROZEN_FILES = ('app.py', 'agent.py', 'db.py', 'runtime_config.py', 'safeguards.py',
                'demo_scenarios.py', 'evaluation/run_benchmark.py', 'evaluation/pricing.json',
                'evaluation/heldout/scenarios.json', 'evaluation/heldout/run_heldout.py')
LIMITATIONS = [
    'A small, purposively constructed synthetic set is not a statistical estimate of real enterprise performance.',
    'Held out from this project\'s demos, fixtures and earlier benchmark, not guaranteed absent from model pretraining. The case author inspected the implementation; this is not an independently blinded external study.',
    'Expectations and production-source hashes were frozen before live execution. No prompts, tools or business rules are tuned against these cases. Changes require a new protocol and fresh cases, not relabeling failures.',
    'The default full run repeats the pilot; --remaining instead imports its original rows and executes only the other 12. Combined reports describe two runs, with separate provenance and rates. No pilot score is remeasured or counted twice.',
    'Primary results use real OpenAI calls only. Offline fixture tests validate the evaluator, never measure LLM performance. No mock fallback exists in this CLI.',
    'This tests the free-form production agent, not the curated public Streamlit selector. Synthetic-preset restrictions are disabled only inside the isolated evaluation context. Prompts, tools and business logic are unchanged.',
    'Invalid-input handling means no successful write and no persisted records, without infrastructure failure. It does not measure clarification quality or specific missing-field recognition: the application hides no-tool model prose.',
    'Approval probes are direct calls to an unauthenticated simulator after agent scoring. They are separately reported and never credited as model task successes. No actual provisioning or identity authentication occurs.',
    'Individual tool writes commit independently. Partial writes are recorded as failures, not repaired or rolled back to improve scores. Repeated actions share one scenario database; different scenarios do not.',
    'Call-budget, provider, quota and execution-limit failures remain in scenario denominators. A safe empty database after a provider failure is not an invalid-input success.',
    'Pricing estimates exclude taxes and use pinned standard-tier prices. The maximum uses a full model context on every permitted request, not a typical forecast or account-wide billing limit. Failed requests consume call budget; partial usage cannot establish total cost.',
    'Live output and timing are nondeterministic. The application supplies the current date; absolute scenario dates, source hashes, returned model IDs and system fingerprints are recorded. Alias availability and pricing may change.',
    'Run as a separate local CLI process, never inside a serving Streamlit process. This evaluator temporarily guards sqlite3.connect and the agent client factory. It does not evaluate browser, multi-user, concurrency or cloud deployment behavior.',
]


def digest(path):
    return common.fingerprint(Path(path))


def load_cases():
    data = json.loads(SCENARIOS.read_text(encoding='utf-8'))
    cases = data['scenarios']
    if data.get('schema_version') != 1 or Counter(s['category'] for s in cases) != CATEGORIES:
        raise ValueError('Unexpected held-out schema or category counts')
    if len({s['id'] for s in cases}) != 15 or len(set(data['pilot_ids'])) != 3:
        raise ValueError('Scenario and pilot IDs must be unique')
    if not set(data['pilot_ids']) <= {s['id'] for s in cases}:
        raise ValueError('Unknown pilot scenario')
    for s in cases:
        if not s['title'] or not s['rationale'] or not s['requests']:
            raise ValueError('Cases require title, independent rationale and requests')
        if any(not isinstance(r, str) or not r.strip() or len(r) > 4000 for r in s['requests']):
            raise ValueError('Invalid input request')
        employee, resources = s['expected']['employee'], s['expected']['resources']
        if employee is not None:
            if set(employee) != set(FIELDS) or any(not isinstance(v, str) or not v.strip() for v in employee.values()):
                raise ValueError('Expected employee must contain four nonempty fields')
            if date.fromisoformat(employee['start_date']).isoformat() != employee['start_date']:
                raise ValueError('Expected employee date must be valid ISO')
        if any(STATUSES.get(kind) != status for kind, status in resources.items()):
            raise ValueError('Expected resources violate the application policy')
        if employee is None and (resources or s['category'] != 'invalid_or_unsupported'):
            raise ValueError('Invalid cases require empty expected state')
        if 'approval_probe' in s and 'github' not in resources:
            raise ValueError('Approval probes require an expected GitHub request')
    if 'mock_tool_batches' in json.dumps(data):
        raise ValueError('Held-out cases must not contain model scripts')
    return data


def validate_separation(data):
    # Explicit allowlist: never scan .env, secrets, databases or report contents.
    files = [ROOT / 'demo_scenarios.py', ROOT / 'conftest.py', ROOT / 'evaluation/scenarios.json']
    files += sorted(ROOT.glob('test_*.py'))
    # New evaluator fixtures use unrelated generic identities; they must not import held-out answers.
    corpus = '\n'.join(p.read_text(encoding='utf-8') for p in files if p.name != 'test_heldout.py')
    identities = data['fictional_identities']
    if len(identities) != len(set(identities)) or any(name.casefold() in corpus.casefold() for name in identities):
        raise ValueError('Held-out identities overlap an earlier dataset or fixture')
    dataset_text = json.dumps(data['scenarios'])
    if any(name not in dataset_text for name in identities):
        raise ValueError('Identity manifest contains an unused identity')
    if any(s['expected']['employee'][key] not in identities for s in data['scenarios']
           if s['expected']['employee'] for key in ('name', 'manager')):
        raise ValueError('Expected employee identities are absent from novelty manifest')
    prior = common.load_scenarios()
    old_requests = {' '.join(a['request'].casefold().split()) for s in prior if s['interface'] == 'agent' for a in s['actions']}
    if any(' '.join(r.casefold().split()) in old_requests for s in data['scenarios'] for r in s['requests']):
        raise ValueError('Held-out wording repeats the original benchmark')
    return {'identity_count': len(identities), 'prior_files_checked': [str(p.relative_to(ROOT)) for p in files if p.name != 'test_heldout.py']}


def verify_freeze():
    frozen = json.loads(PROTOCOL.read_text(encoding='utf-8'))
    if set(frozen['sha256']) != set(FROZEN_FILES):
        raise ValueError('Protocol manifest does not cover required sources')
    changed = [name for name, expected in frozen['sha256'].items() if digest(ROOT / name) != expected]
    if changed:
        runner = 'evaluation/heldout/run_heldout.py'
        amendment = json.loads(AMENDMENT.read_text(encoding='utf-8'))
        if (changed != [runner] or amendment['parent_protocol_sha256'] != digest(PROTOCOL) or
                amendment['parent_runner_sha256'] != frozen['sha256'][runner] or
                set(amendment['sha256']) != set(FROZEN_FILES) or
                any(amendment['sha256'][name] != frozen['sha256'][name] for name in FROZEN_FILES if name != runner) or
                any(digest(ROOT / name) != value for name, value in amendment['sha256'].items())):
            raise ValueError('Frozen sources do not match the authorized orchestration-only amendment')
        tree = ast.parse((ROOT / runner).read_text(encoding='utf-8'))
        protected = {node.name: hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
                     for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))
                     and node.name in amendment['protected_ast_sha256']}
        if protected != amendment['protected_ast_sha256']:
            raise ValueError('Agent execution or grading changed after the pilot')
        return amendment
    return frozen


def pilot_fingerprints():
    folder = HERE / 'pilot'
    if folder.is_symlink() or any((folder / name).is_symlink() or not (folder / name).is_file() for name in REPORT_FILES):
        raise ValueError('Remaining mode requires all three original, unlinked pilot reports')
    return {name: digest(folder / name) for name in REPORT_FILES}


def load_pilot(data, settings, budget):
    """Read-only validation of prior live evidence; never select only passing rows."""
    hashes = pilot_fingerprints()
    pilot = json.loads((HERE / 'pilot/summary.json').read_text(encoding='utf-8'))
    original = json.loads(PROTOCOL.read_text(encoding='utf-8'))
    if (pilot['mode'] != 'live' or pilot['subset'] != 'pilot' or pilot['dataset_id'] != data['dataset_id'] or
            pilot['protocol'] != original or not pilot['production_database_unchanged'] or
            not pilot['frozen_sources_unchanged_after_run']):
        raise ValueError('Pilot provenance is incompatible with this dataset/protocol')
    rows = pilot['scenarios']
    ids = [row['id'] for row in rows]
    if len(ids) != len(set(ids)) or set(ids) != set(data['pilot_ids']):
        raise ValueError('Pilot must contain exactly the three declared unique IDs')
    plan = pilot['preflight']
    if (plan['configured_model'] != budget.model or plan['max_output_tokens_per_call'] != budget.max_completion_tokens or
            plan['max_model_calls_per_execution'] != settings.max_model_calls or plan['sdk_retries'] != 0):
        raise ValueError('Model and per-execution limits must match the pilot')
    catalog = {case['id']: case for case in data['scenarios']}
    for row in rows:
        case = catalog[row['id']]
        if (row['mode'] != 'live' or row['interface'] != 'agent' or row['category'] != case['category'] or
                row['expected'] != case['expected'] or row['rationale'] != case['rationale'] or
                [a['request'] for a in row['actions']] != case['requests'] or
                row['api_usage']['mock_model_calls'] != 0 or row['api_usage']['live_sdk_calls'] <= 0):
            raise ValueError('Pilot row does not match the frozen live case')
        # Recompute from stored evidence, without executing agent/tools or changing rows.
        checked = judge(case, row['actions'], row['api_usage']['errors'], row['response_metadata'])
        if row['errors'] or row['api_usage']['errors']:
            checked['checks']['execution_completed_without_exception'] = False
            checked['passed'] = False
            if checked['invalid_safe'] is not None:
                checked['invalid_safe'] = False
        if row['judgment'] != checked or row['status'] != ('passed' if checked['passed'] else 'failed'):
            raise ValueError('Pilot judgment does not agree with captured evidence')
        if 'approval_probe' in case and row.get('approval_probe', {}).get('interface') != 'direct_approval_api':
            raise ValueError('Pilot is missing separate approval evidence')
    recalculated = summarize(rows, plan, pilot['command'], True, original)
    if any(pilot[key] != recalculated[key] for key in ('metrics', 'api_usage', 'direct_approval_api')):
        raise ValueError('Pilot aggregate metrics disagree with its rows')
    if pilot['safety_controls']['attempted_calls'] != recalculated['api_usage']['attempted_calls']:
        raise ValueError('Pilot API request accounting is inconsistent')
    with (HERE / 'pilot/results.csv').open(encoding='utf-8', newline='') as stream:
        csv_rows = list(csv.DictReader(stream))
    if (len(csv_rows) != len(rows) or {r['id'] for r in csv_rows} != set(ids) or
            any(r['status'] != next(x['status'] for x in rows if x['id'] == r['id']) or
                int(r['live_api_calls']) != next(x['api_usage']['live_sdk_calls'] for x in rows if x['id'] == r['id'])
                for r in csv_rows)):
        raise ValueError('Pilot CSV does not agree with its summary')
    if hashes != pilot_fingerprints():
        raise ValueError('Pilot reports changed while being read')
    return pilot, hashes


def combine_reports(data, pilot, remaining, hashes):
    """Aggregate each original row once, retaining separate run provenance/costs."""
    by_id = {row['id']: row for row in pilot['scenarios'] + remaining['scenarios']}
    expected_ids = {case['id'] for case in data['scenarios']}
    if len(pilot['scenarios']) + len(remaining['scenarios']) != len(expected_ids) or set(by_id) != expected_ids:
        raise ValueError('Combined report requires exactly one row for every case')
    rows = [by_id[case['id']] for case in data['scenarios']]
    plan = dict(remaining['preflight'], subset='combined_pilot_and_remaining',
                approval_probe_ids=[case['id'] for case in data['scenarios'] if 'approval_probe' in case])
    result = summarize(rows, plan, remaining['command'],
                       pilot['production_database_unchanged'] and remaining['production_database_unchanged'], remaining['protocol'])
    result['preflight'] = remaining['preflight']  # All cost/call caps here apply to NEW requests only.
    result['safety_controls'] = dict(remaining['safety_controls'], applies_to='remaining execution only; excludes historical pilot calls')
    result['frozen_sources_unchanged_after_run'] = remaining['frozen_sources_unchanged_after_run']
    result['aggregation'] = {'scenario_count': len(rows), 'reused_pilot_ids': [r['id'] for r in pilot['scenarios']],
                             'new_scenario_ids': [r['id'] for r in remaining['scenarios']],
                             'pilot_report_sha256': hashes, 'pilot_results_unchanged': True,
                             'new_run_metrics': remaining['metrics']}
    provenance_keys = ('generated_at_utc', 'command', 'working_directory', 'environment', 'protocol', 'preflight',
                       'safety_controls', 'api_usage', 'production_database_unchanged', 'frozen_sources_unchanged_after_run')
    result['source_runs'] = {label: {key: source[key] for key in provenance_keys}
                             for label, source in (('pilot', pilot), ('remaining', remaining))}
    return result


class Recorder(common.ModelRecorder):
    """Observe real SDK output without passing expected answers to the client."""
    def __init__(self, budget):
        super().__init__(budget)
        self.response_metadata = []

    def live_factory(self, original_factory):
        base = super().live_factory(original_factory)

        def factory(**options):
            wrapped = base(**options)

            def create(**kwargs):
                response = wrapped.chat.completions.create(**kwargs)
                self.response_metadata.append({
                    'model': getattr(response, 'model', None),
                    'system_fingerprint': getattr(response, 'system_fingerprint', None),
                    'finish_reasons': [getattr(c, 'finish_reason', None) for c in response.choices],
                })
                return response
            return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        return factory


def state():
    con = db.connect()
    try:
        return {table: [dict(row) for row in con.execute(f'SELECT * FROM {table} ORDER BY id')]
                for table in ('employees', 'requests')}
    finally:
        con.close()


def judge(case, actions, api_errors=(), response_metadata=()):
    """Pure, independent oracle; consumes captured state and trace, never agent prose."""
    expected = case['expected']
    employee = expected['employee']
    trace = [entry for action in actions for entry in action['trace']]
    infrastructure = [entry for entry in trace if entry.get('event') in
                      ('provider_error', 'quota_error', 'execution_limit', 'input_error')]
    healthy = not infrastructure and not api_errors and not any(
        reason in ('length', 'content_filter') for response in response_metadata for reason in response['finish_reasons'])
    complete = len(actions) == len(case['requests'])
    final = actions[-1]['after'] if actions else {'employees': [], 'requests': []}
    states = [action['after'] for action in actions]
    errors = [e for e in trace if 'error' in e.get('result', {})]
    tool_calls = [e for e in trace if 'tool' in e and e.get('source') != 'verification']
    tool_errors = [e for e in tool_calls if 'error' in e.get('result', {}) and
                   e['result']['error'] != 'Skipped because an earlier tool call failed']
    checks = {'completed_all_actions': complete, 'no_infrastructure_failure': healthy}
    allowed = {'create_employee', 'create_request', 'get_onboarding'}
    checks['no_unauthorized_tool_attempts'] = all(e['tool'] in allowed for e in tool_calls)
    checks['no_duplicate_records'] = all(
        len(s['employees']) == len({(e['name'], e['start_date']) for e in s['employees']}) and
        len(s['requests']) == len({(r['employee_id'], r['kind']) for r in s['requests']}) for s in states)
    checks['no_unapproved_github_transition'] = all(
        r['status'] == 'pending_manager_approval' for s in states for r in s['requests'] if r['kind'] == 'github')
    checks['trace_github_policy'] = all(
        r.get('status') == 'pending_manager_approval'
        for e in trace for r in ([e.get('result', {})] + e.get('result', {}).get('requests', []))
        if r.get('kind') == 'github')
    field_checks = None
    if employee is None:
        successful_writes = [e for e in tool_calls if e['tool'] in ('create_employee', 'create_request') and 'error' not in e.get('result', {})]
        checks['invalid_request_safe'] = (complete and healthy and not successful_writes and bool(states)
                                          and all(not s['employees'] and not s['requests'] for s in states))
    else:
        field_checks = {key: len(final['employees']) == 1 and final['employees'][0][key] == employee[key] for key in FIELDS}
        checks['exact_employee_after_every_action'] = bool(states) and all(
            len(s['employees']) == 1 and {key: s['employees'][0][key] for key in FIELDS} == employee for s in states)
        checks['exact_resources_after_every_action'] = bool(states) and all(
            len(s['employees']) == 1 and sorted((r['employee_id'], r['kind'], r['status']) for r in s['requests']) ==
            sorted((s['employees'][0]['id'], kind, status) for kind, status in expected['resources'].items()) for s in states)
        checks['no_tool_errors'] = not errors
        checks['verified_readback_each_action'] = bool(actions) and all(
            any(e.get('tool') == 'get_onboarding' and 'error' not in e.get('result', {}) and
                e['result'].get('employee') in a['after']['employees'] and
                sorted(e['result'].get('requests', []), key=lambda r: r['id']) == a['after']['requests'] for e in a['trace'])
            for a in actions)
        if len(case['requests']) > 1:
            checks['repeat_preserves_records_and_ids'] = complete and all(s == states[0] for s in states)
    github = 'github' in expected['resources']
    approval_pass = (complete and healthy and checks['no_unauthorized_tool_attempts'] and
                     checks['no_unapproved_github_transition'] and checks['trace_github_policy'] and bool(states) and
                     all(len(s['employees']) == 1 and {key: s['employees'][0][key] for key in FIELDS} == employee and
                         len([r for r in s['requests'] if r['kind'] == 'github' and r['employee_id'] == s['employees'][0]['id']]) == 1
                         for s in states)) if github else None
    return {'checks': checks, 'passed': all(checks.values()), 'employee_fields': field_checks,
            'resource_exact': checks.get('exact_resources_after_every_action'), 'approval_compliant': approval_pass,
            'invalid_safe': checks.get('invalid_request_safe'), 'tool_errors': tool_errors,
            'tool_call_count': len(tool_calls), 'skipped_tool_calls': sum(e.get('result', {}).get('error') ==
            'Skipped because an earlier tool call failed' for e in tool_calls)}


def approval_probes(case, database):
    """Direct simulator evidence, outside the primary agent score."""
    before = state()
    matching = [e for e in before['employees'] if {k: e[k] for k in FIELDS} == case['expected']['employee']]
    pending = [r for r in before['requests'] if r['kind'] == 'github' and r['status'] == 'pending_manager_approval']
    if len(matching) != 1 or len(pending) != 1 or pending[0]['employee_id'] != matching[0]['id']:
        return {'interface': 'direct_approval_api', 'status': 'blocked', 'checks': {}, 'reason': 'Agent did not establish the required pending record'}
    employee = matching[0]
    before_hash = digest(database)
    wrong = db.approve_github(employee['id'], case['approval_probe']['wrong_manager'])
    checks = {'wrong_manager_no_change': 'error' in wrong and state() == before and digest(database) == before_hash}
    correct = db.approve_github(employee['id'], employee['manager'])
    approved = state()
    desired = json.loads(json.dumps(before))
    for r in desired['requests']:
        if r['id'] == pending[0]['id']:
            r['status'] = 'approved_pending_provisioning'
    checks['correct_manager_only_updates_github'] = (correct.get('status') == 'approved_pending_provisioning' and approved == desired)
    approved_hash = digest(database)
    again = db.approve_github(employee['id'], employee['manager'])
    checks['repeated_approval_no_change'] = again == correct and state() == approved and digest(database) == approved_hash
    return {'interface': 'direct_approval_api', 'status': 'passed' if all(checks.values()) else 'failed',
            'checks': checks, 'results': [wrong, correct, again], 'after': state()}


def run_case(case, settings, budget):
    started = time.perf_counter()
    recorder = Recorder(budget)
    row = {'id': case['id'], 'category': case['category'], 'title': case['title'], 'interface': 'agent',
           'mode': 'live', 'expected': case['expected'], 'rationale': case['rationale'], 'actions': [], 'errors': []}
    original_factory = agent.OpenAI
    original_connect = sqlite3.connect
    try:
        with tempfile.TemporaryDirectory(prefix='flowpilot-heldout-') as directory, ExitStack() as stack:
            root = Path(directory).resolve()
            database = root / 'scenario.sqlite3'
            scoped = replace(settings, public_demo=False, data_dir=root / 'runtime', private_db_path='',
                             daily_api_quota=budget.max_api_calls)
            allowed_paths = {database, root / 'runtime/control.sqlite3'}

            def isolated_connect(path, *args, **kwargs):
                if kwargs.get('uri') or Path(path).resolve() not in allowed_paths:
                    raise RuntimeError('Held-out SQLite isolation rejected a path outside this scenario')
                return original_connect(path, *args, **kwargs)

            stack.enter_context(patch.object(sqlite3, 'connect', isolated_connect))
            stack.enter_context(db.use_database(database))
            stack.enter_context(config.use_settings(scoped))
            stack.enter_context(config.synthetic_policy(None))  # Never feed expected answers to the agent.
            factory = recorder.live_factory(lambda **kw: original_factory(api_key=scoped.api_key, **kw))
            stack.enter_context(patch.object(agent, 'OpenAI', factory))
            db.init_db()
            for request in case['requests']:
                before = state()
                answer, trace = agent.run_agent(request)
                row['actions'].append({'request': request, 'answer': answer, 'trace': trace, 'before': before, 'after': state()})
            row['judgment'] = judge(case, row['actions'], recorder.errors, recorder.response_metadata)
            row['agent_duration_seconds'] = time.perf_counter() - started
            if 'approval_probe' in case:
                try:
                    row['approval_probe'] = approval_probes(case, database)
                except Exception as exc:
                    row['approval_probe'] = {'interface': 'direct_approval_api', 'status': 'failed', 'checks': {},
                                             'exception_type': type(exc).__name__}
    except Exception as exc:
        row['errors'].append({'stage': 'scenario', 'exception_type': type(exc).__name__, 'message': 'Details suppressed to protect credentials'})
    finally:
        recorder.close()
    row.setdefault('agent_duration_seconds', time.perf_counter() - started)
    row.setdefault('judgment', judge(case, row['actions'], recorder.errors, recorder.response_metadata))
    if row['errors'] or recorder.errors:
        row['judgment']['checks']['execution_completed_without_exception'] = False
        row['judgment']['passed'] = False
        if row['judgment']['invalid_safe'] is not None:
            row['judgment']['invalid_safe'] = False
    row['status'] = 'passed' if row['judgment']['passed'] else 'failed'
    row['api_usage'] = recorder.as_dict()
    row['response_metadata'] = recorder.response_metadata
    row['duration_seconds'] = time.perf_counter() - started
    row['errors'] += recorder.errors
    # Also redact keys loaded from .env without placing them into os.environ.
    with config.use_settings(settings):
        return config.redact(row)


def fraction(values):
    values = list(values)
    return {'numerator': sum(bool(v) for v in values), 'denominator': len(values),
            'value': sum(bool(v) for v in values) / len(values) if values else None}


def summarize(rows, plan, command, unchanged, manifest):
    usage = [row['api_usage'] for row in rows]
    calls = sum(u['live_sdk_calls'] for u in usage)
    coverage = sum(u['responses_with_usage'] for u in usage)
    tokens = {k: sum((u['observed_tokens'] or {}).get(k, 0) for u in usage)
              for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')}
    profile = plan['cost_ceiling']['profile']
    complete_usage = bool(calls) and calls == coverage and not any(u['errors'] for u in usage)
    cost = (tokens['prompt_tokens'] * profile['input_per_million'] + tokens['completion_tokens'] * profile['output_per_million']) / 1e6
    seconds = sum(row['agent_duration_seconds'] for row in rows)
    tool_errors = sum(len(r['judgment']['tool_errors']) for r in rows)
    tool_calls = sum(r['judgment']['tool_call_count'] - r['judgment']['skipped_tool_calls'] for r in rows)
    probes = [r.get('approval_probe', {'status': 'blocked', 'checks': {}}) for r in rows if r['id'] in plan['approval_probe_ids']]
    summary = {
        'mode': 'live', 'dataset_id': 'flowpilot-heldout-v1', 'subset': plan['subset'],
        'generated_at_utc': datetime.now(timezone.utc).isoformat(), 'command': command,
        'working_directory': str(Path.cwd()), 'production_database_unchanged': unchanged,
        'pilot_artifacts_present_before_run': plan['pilot_artifacts_present'],
        'protocol': manifest, 'preflight': plan,
        'environment': {'python': platform.python_version(), 'openai': version('openai'),
                        'sqlite': sqlite3.sqlite_version, 'platform': platform.platform(),
                        'agent_system_prompt_date': date.today().isoformat()},
        'metrics': {
            'scenario_exact_success': fraction(r['status'] == 'passed' for r in rows),
            'by_category': {c: fraction(r['status'] == 'passed' for r in rows if r['category'] == c) for c in CATEGORIES},
            'pilot_case_success': fraction(r['status'] == 'passed' for r in rows if r['id'] in plan['pilot_ids']),
            'nonpilot_case_success': fraction(r['status'] == 'passed' for r in rows if r['id'] not in plan['pilot_ids']),
            'employee_information_accuracy': fraction(v for r in rows for v in (r['judgment']['employee_fields'] or {}).values()),
            'resource_request_accuracy': fraction(r['judgment']['resource_exact'] for r in rows if r['expected']['employee'] is not None),
            'approval_policy_compliance': fraction(r['judgment']['approval_compliant'] for r in rows if 'github' in r['expected']['resources']),
            'invalid_input_handling': fraction(r['judgment']['invalid_safe'] for r in rows if r['expected']['employee'] is None),
            'tool_execution_error_rate': {'numerator': tool_errors, 'denominator': tool_calls, 'value': tool_errors / tool_calls if tool_calls else None},
            'average_execution_seconds': {'numerator': seconds, 'denominator': len(rows), 'value': seconds / len(rows) if rows else None},
        },
        'direct_approval_api': {'scenario_success': fraction(p['status'] == 'passed' for p in probes),
                                'checks': fraction(p['checks'].get(key, False) for p in probes for key in
                                                   ('wrong_manager_no_change', 'correct_manager_only_updates_github', 'repeated_approval_no_change'))},
        'api_usage': {'attempted_calls': calls, 'usage_coverage': {'numerator': coverage, 'denominator': calls},
                      'observed_tokens': tokens if coverage else None, 'complete': complete_usage,
                      'approximate_uncached_cost_usd': cost if complete_usage else None,
                      'note': 'Uncached standard-tier approximation only when every attempted request has usage. Cache discounts can lower the bill. Missing usage means unknown total cost, not zero.'},
        'limitations': LIMITATIONS, 'scenarios': rows,
    }
    return summary


def preflight(data, cases, settings, budget, subset):
    ceiling = common.cost_ceiling(budget)
    invocations = sum(len(s['requests']) for s in cases)
    # Planning assumption, not a measured live call count: 3-4 rounds for writes,
    # 1-2 rounds for safe rejection. Splitting tool batches can require more.
    low = sum(len(s['requests']) * (1 if s['expected']['employee'] is None else 3) for s in cases)
    high = sum(len(s['requests']) * (2 if s['expected']['employee'] is None else 4) for s in cases)
    typical_per_call = (2000 * ceiling['profile']['input_per_million'] + 400 * ceiling['profile']['output_per_million']) / 1e6
    return {'subset': subset, 'scenario_count': len(cases), 'scenario_ids': [s['id'] for s in cases],
            'pilot_ids': data['pilot_ids'], 'approval_probe_ids': [s['id'] for s in cases if 'approval_probe' in s],
            'agent_invocations': invocations, 'configured_model': budget.model,
            'max_model_calls_per_execution': settings.max_model_calls,
            'estimated_model_calls': {'low': low, 'high': high, 'assumption': '3-4 calls per valid submission; 1-2 per invalid submission, not measured'},
            'enforced_api_call_limit': budget.max_api_calls,
            'possible_calls_under_agent_and_global_caps': min(budget.max_api_calls, invocations * settings.max_model_calls),
            'max_output_tokens_per_call': budget.max_completion_tokens, 'sdk_retries': 0,
            'illustrative_cost_usd': {'low': low * typical_per_call, 'high': high * typical_per_call,
                                      'assumption': '2,000 input and 400 output tokens per call; not a maximum or measured usage'},
            'cost_ceiling': ceiling, 'pilot_artifacts_present': (HERE / 'pilot/summary.json').exists(),
            'scenario_previews': [{'id': s['id'], 'title': s['title'], 'category': s['category'], 'requests': s['requests'],
                                    'expected': s['expected'], 'direct_approval_probe': 'approval_probe' in s} for s in cases]}


def markdown(summary):
    lines = ['# FlowPilot AI held-out evaluation', '', '**Live OpenAI agent evaluation; no mocked primary results.**', '',
             f"Subset: {summary['subset']}. Generated UTC: {summary['generated_at_utc']}", '',
             '## Reproduce', '', 'Run from the repository root:', '', '```powershell', summary['command'], '```', '',
             '## Metrics', '', '| Metric | Numerator | Denominator | Value |', '| --- | ---: | ---: | ---: |']
    if 'aggregation' in summary:
        details = summary['aggregation']
        lines[4:4] = ['**Combined report: original pilot evidence plus a separate remaining-only execution.** '
                      'The pilot was not rerun. Each of the 15 cases is counted once. The command below runs only '
                      'the remaining cases and requires the original pilot reports. Preflight limits apply only '
                      'to new calls; aggregate usage includes both runs.', '',
                      '## Pilot command (already executed)', '', '```powershell',
                      summary['source_runs']['pilot']['command'], '```', '',
                      '## Aggregation and per-run provenance', '', '```json',
                      json.dumps({'aggregation': details, 'source_runs': summary['source_runs']}, indent=2), '```', '']
    for key, metric in summary['metrics'].items():
        if 'denominator' in metric:
            lines.append(f"| {key} | {metric['numerator']} | {metric['denominator']} | {metric['value']} |")
    lines += ['', 'Employee accuracy counts the four exact fields for each valid case (missing/extra employee = four failures). '
              'Resource accuracy counts exact resource/status/employee-ID sets after every submission of valid cases, including the empty set. '
              'Approval compliance applies only to cases explicitly requesting GitHub, including failures with no GitHub record. '
              'Invalid handling applies only to negative cases. Tool errors exclude skipped calls and automatic readback, include expected validation errors, and have attempted model tool calls as denominator. '
              'Mean timing includes scenario setup and grading, excludes subsequent direct approval probes and report writing. '
              'Scenario success requires every assertion, including infrastructure health. Direct probes never affect the primary agent score.', '',
              '## Case results', '', '| ID | Category | Result | Failed checks | Seconds |', '| --- | --- | --- | --- | ---: |']
    for r in summary['scenarios']:
        failed = ', '.join(k for k, v in r['judgment']['checks'].items() if not v) or 'None'
        lines.append(f"| {r['id']} | {r['category']} | {r['status']} | {failed} | {r['agent_duration_seconds']:.3f} |")
    lines += ['', '## Representative evidence and failures', '']
    successes = [r for r in summary['scenarios'] if r['status'] == 'passed'][:2]
    failures = [r for r in summary['scenarios'] if r['status'] != 'passed']
    for r in successes + failures:
        lines += [f"### {r['id']} — {r['status']}", '', r['rationale'], '', '```json',
                  json.dumps({'expected': r['expected'], 'checks': r['judgment']['checks'],
                              'final_agent_state': r['actions'][-1]['after'] if r['actions'] else None,
                              'execution_errors': r['errors'], 'tool_errors': r['judgment']['tool_errors']}, indent=2), '```', '']
    lines += ['Full per-submission state, error messages and tool traces are in summary.json.', '',
              '## Methodology and construction', '',
              'Fifteen fictional cases were authored before live execution: four straightforward, four linguistic variations, three challenging and four invalid/unsupported requests. '
              'Identities and exact request strings are checked against the earlier demos, benchmark and test fixtures. '
              'A frozen SHA-256 manifest binds the cases, evaluator, pricing, agent and relevant application sources. '
              'Only request text is passed to agent.run_agent. Expected answers are never injected into model prompts, tools or synthetic-demo policy. '
              'Each scenario uses a fresh temporary SQLite file and isolated quota storage. Real production tool dispatch and validation write those records. '
              'Every submission is graded from all stored rows and the tool trace. Source and original-database fingerprints are reported. '
              'A repeated request shares only its own scenario database. Failed scenarios remain in the denominator and execution continues. '
              'Offline tests exercise evaluator logic with unrelated fixtures and fake transports; they are not live results.', '',
              '## Robustness observations', '',
              'The category and invalid-handling metrics below are observations of this run, not generalized reliability claims. '
              'Expected validation errors may accompany a passing negative case. Partial writes, unsupported tool attempts, wrong statuses and provider failures are retained in the evidence.', '',
              '```json', json.dumps(summary['metrics']['by_category'], indent=2), '```', '',
              '## Separate direct approval API probes', '', '```json', json.dumps(summary['direct_approval_api'], indent=2), '```', '',
              '## API usage and cost', '', '```json', json.dumps(summary['api_usage'], indent=2), '```', '',
              '## Environment, controls and provenance', '', '```json',
              json.dumps({k: summary[k] for k in ('environment', 'protocol', 'preflight', 'production_database_unchanged', 'pilot_artifacts_present_before_run')}, indent=2), '```', '',
              '## Limitations and threats to validity', '']
    lines += ['- ' + item for item in LIMITATIONS]
    return '\n'.join(lines) + '\n'


def validate_destination(destination):
    destination = Path(destination)
    if destination.is_symlink() or destination.resolve() not in {HERE.resolve(), (HERE / 'pilot').resolve()}:
        raise ValueError('Reports must stay in the held-out directory or pilot subdirectory')
    for name in ('results.csv', 'summary.json', 'EVALUATION_REPORT.md'):
        path = destination / name
        if path.exists() or path.is_symlink():
            raise ValueError('Existing held-out reports must be archived manually; refusing to overwrite')


def write_reports(summary, destination, settings):
    validate_destination(destination)
    with config.use_settings(settings):
        summary = config.redact(summary)
    destination.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents replacing existing files, including links.
    with (destination / 'summary.json').open('x', encoding='utf-8') as stream:
        json.dump(summary, stream, indent=2, ensure_ascii=True)
    with (destination / 'results.csv').open('x', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['id', 'category', 'mode', 'status', 'agent_duration_seconds', 'failed_checks', 'errors', 'live_api_calls'])
        writer.writeheader()
        for r in summary['scenarios']:
            writer.writerow({**{k: r[k] for k in ('id', 'category', 'mode', 'status', 'agent_duration_seconds')},
                             'failed_checks': json.dumps([k for k, v in r['judgment']['checks'].items() if not v]),
                             'errors': json.dumps(r['errors'] + r['judgment']['tool_errors']), 'live_api_calls': r['api_usage']['live_sdk_calls']})
    with (destination / 'EVALUATION_REPORT.md').open('x', encoding='utf-8') as stream:
        stream.write(markdown(summary))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Explicit paid API opt-in; never use without approval')
    parser.add_argument('--dry-run', action='store_true', help='Offline preflight only, even when --live is also supplied')
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--pilot', action='store_true', help='Select the three predeclared pilot cases')
    selection.add_argument('--remaining', action='store_true', help='Reuse validated pilot results; execute only the other 12 and write a combined report')
    parser.add_argument('--max-api-calls', type=int, help='NEW attempted-request cap; defaults: pilot 12, remaining 52, full 64')
    parser.add_argument('--max-output-tokens', type=int, help='Output limit per request; otherwise preserve application configuration')
    parser.add_argument('--model', help='Model override; otherwise use application configuration')
    args = parser.parse_args(argv)
    try:
        data = load_cases()
        separation = validate_separation(data)
        frozen = verify_freeze()
        settings = config.load_settings()  # .env read-only, no mutation or logging.
        settings = replace(settings, model=args.model or settings.model,
                           max_output_tokens=args.max_output_tokens if args.max_output_tokens is not None else settings.max_output_tokens)
        budget = common.ApiBudget(args.max_api_calls if args.max_api_calls is not None else
                                  (12 if args.pilot else 52 if args.remaining else 64), settings.max_output_tokens, settings.model)
        pilot, pilot_hashes = load_pilot(data, settings, budget) if args.remaining else (None, None)
        cases = [s for s in data['scenarios'] if
                 (s['id'] not in data['pilot_ids'] if args.remaining else not args.pilot or s['id'] in data['pilot_ids'])]
        plan = preflight(data, cases, settings, budget, 'remaining' if args.remaining else 'pilot' if args.pilot else 'full')
        if args.remaining:
            plan['reused_pilot_ids'] = data['pilot_ids']
            plan['historical_pilot_api_calls'] = pilot['api_usage']['attempted_calls']
            plan['pilot_report_sha256'] = pilot_hashes
            plan['combined_report_scenario_count'] = len(data['scenarios'])
            validate_destination(HERE)
        destination = HERE / 'pilot' if args.pilot else HERE
        if args.live and not args.dry_run:
            validate_destination(destination)
            if not settings.api_key:
                raise ValueError('Live evaluation requires OPENAI_API_KEY in environment or local .env')
    except Exception as exc:
        # Do not print raw configuration/provider exception values.
        parser.error(f'Preflight rejected ({type(exc).__name__}). Check frozen protocol, scenario schema, pricing, limits, credentials and existing report files.')
    if not args.live or args.dry_run:
        with config.use_settings(settings):
            print(json.dumps(config.redact({'mode': 'offline_preflight', 'live_calls': 0, 'performance_results': None,
                                           'separation': separation, **plan}), indent=2))
        return 0
    before = digest(ROOT / 'flowpilot.db')
    rows = []
    with config.use_settings(settings):
        for case in cases:
            row = run_case(case, settings, budget)
            rows.append(row)
            print(f"{row['id']}: {row['status']} ({row['api_usage']['live_sdk_calls']} API requests)", flush=True)
        summary = summarize(rows, plan, common.reproduction_command(), before == digest(ROOT / 'flowpilot.db'), frozen)
        summary['safety_controls'] = budget.as_dict()
        summary['frozen_sources_unchanged_after_run'] = all(digest(ROOT / name) == value for name, value in frozen['sha256'].items())
        if args.remaining:
            if pilot_fingerprints() != pilot_hashes:
                raise ValueError('Pilot reports changed during execution; refusing an inconsistent combined report')
            summary = combine_reports(data, pilot, summary, pilot_hashes)
        write_reports(summary, destination, settings)
    success = summary['metrics']['scenario_exact_success']
    print(f"Live held-out results: {success['numerator']}/{success['denominator']}. Reports: {destination}")
    return 0 if (success['numerator'] == success['denominator'] and summary['production_database_unchanged'] and
                 summary['frozen_sources_unchanged_after_run'] and all(p.get('approval_probe', {}).get('status', 'passed') == 'passed' for p in summary['scenarios'])) else 1


if __name__ == '__main__':
    raise SystemExit(main())
