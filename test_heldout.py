"""Offline evaluator tests with unrelated fixtures; NOT held-out LLM performance."""
import copy
import json
import sqlite3
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from openai import OpenAI
from openai.types.chat import ChatCompletionMessage

import agent
import db
import runtime_config as config
from evaluation.heldout import run_heldout as heldout


@pytest.fixture
def fixture_case():
    return {'id': 'fixture-only', 'category': 'straightforward', 'title': 'Unrelated evaluator fixture',
            'requests': ['Process the synthetic evaluator fixture request.'], 'rationale': 'ORACLE_ONLY_NOT_FOR_MODEL',
            'expected': {'employee': {'name': 'Evaluator Fixture Omega', 'role': 'Fixture Engineer',
                                     'start_date': '2032-02-29', 'manager': 'Evaluator Manager Sigma'},
                         'resources': {'email': 'requested', 'github': 'pending_manager_approval'}}}


def stored(case):
    employee = dict(case['expected']['employee'], id=1)
    return {'employees': [employee], 'requests': [dict(id=i, employee_id=1, kind=k, status=v)
                                                for i, (k, v) in enumerate(case['expected']['resources'].items(), 1)]}


def evidence(case):
    result = stored(case)
    return [{'request': case['requests'][0], 'before': {'employees': [], 'requests': []}, 'after': result,
             'answer': 'Arbitrary model prose is never the oracle.',
             'trace': [{'tool': 'get_onboarding', 'source': 'verification',
                        'result': {'employee': result['employees'][0], 'requests': result['requests']}}]}]


def reply(calls=(), content=None, finish='tool_calls'):
    message = ChatCompletionMessage(role='assistant', content=content, tool_calls=[
        {'id': f'fixture_{i}', 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}
        for i, (name, args) in enumerate(calls)] or None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish)],
                           model='gpt-4.1-mini', system_fingerprint='offline-fixture',
                           usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150))


def script(case):
    return [reply([('create_employee', case['expected']['employee'])]),
            reply([('create_request', {'employee_id': 1, 'kind': k}) for k in case['expected']['resources']]),
            reply(content='Done', finish='stop')]


def fake_sdk(monkeypatch, responses):
    create = Mock(side_effect=responses)
    close = Mock()
    factory = Mock(return_value=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=close))
    monkeypatch.setattr(agent, 'OpenAI', factory)
    return factory, create, close


def test_frozen_catalog_structure_novelty_and_no_scripts():
    data = heldout.load_cases()
    checked = heldout.validate_separation(data)
    assert len(data['scenarios']) == 15
    assert len(data['pilot_ids']) == 3
    assert checked['identity_count'] == 30
    assert 'mock_tool_batches' not in json.dumps(data)
    assert len(heldout.verify_freeze()['sha256']) == len(heldout.FROZEN_FILES)


def test_overlap_and_protocol_drift_are_rejected(tmp_path, monkeypatch):
    data = heldout.load_cases()
    data['fictional_identities'][0] = 'Mira Fenwick'
    with pytest.raises(ValueError):
        heldout.validate_separation(data)
    protocol = json.loads(heldout.PROTOCOL.read_text())
    protocol['sha256']['agent.py'] = 'incorrect-hash'
    path = tmp_path / 'protocol.json'
    path.write_text(json.dumps(protocol))
    monkeypatch.setattr(heldout, 'PROTOCOL', path)
    with pytest.raises(ValueError):
        heldout.verify_freeze()


@pytest.mark.parametrize('flags', [[], ['--dry-run'], ['--live', '--dry-run', '--pilot']])
def test_default_and_dry_runs_do_not_execute_or_create_reports(monkeypatch, capsys, flags):
    forbidden = Mock(side_effect=AssertionError('Offline preflight must not execute'))
    monkeypatch.setattr(heldout, 'run_case', forbidden)
    monkeypatch.setattr(heldout, 'write_reports', forbidden)
    monkeypatch.setattr(sqlite3, 'connect', forbidden)
    monkeypatch.setattr(agent, 'OpenAI', forbidden)
    assert heldout.main(flags) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['live_calls'] == 0 and result['performance_results'] is None
    assert result['scenario_count'] == (3 if '--pilot' in flags else 15)
    assert result['enforced_api_call_limit'] == (12 if '--pilot' in flags else 64)
    forbidden.assert_not_called()


def test_cost_plan_and_subset_denominators_are_predeclared():
    data = heldout.load_cases()
    plan = heldout.preflight(data, data['scenarios'], config.get_settings(), heldout.common.ApiBudget(64), 'full')
    assert plan['agent_invocations'] == 16
    assert (plan['estimated_model_calls']['low'], plan['estimated_model_calls']['high']) == (40, 56)
    assert plan['cost_ceiling']['estimated_upper_bound_usd'] == pytest.approx(26.9228032)
    assert len(plan['approval_probe_ids']) == 1
    assert sum(s['expected']['employee'] is not None for s in data['scenarios']) == 11
    assert sum('github' in s['expected']['resources'] for s in data['scenarios']) == 5


def test_exact_oracle_accepts_state_not_final_text(fixture_case):
    actions = evidence(fixture_case)
    actions[0]['answer'] = 'Nothing happened. This contradictory prose is ignored.'
    judgment = heldout.judge(fixture_case, actions)
    assert judgment['passed']
    assert all(judgment['employee_fields'].values())
    assert judgment['approval_compliant']


@pytest.mark.parametrize('mutation', ['name', 'role', 'start_date', 'manager', 'extra_employee', 'missing_resource',
                                    'duplicate_resource', 'approved_github', 'wrong_owner', 'no_readback',
                                    'unauthorized_tool', 'provider_failure'])
def test_oracle_rejects_incorrect_state_and_trace(fixture_case, mutation):
    actions = copy.deepcopy(evidence(fixture_case))
    final = actions[0]['after']
    if mutation in heldout.FIELDS:
        final['employees'][0][mutation] = 'incorrect fixture value'
    elif mutation == 'extra_employee':
        final['employees'].append(dict(final['employees'][0], id=2))
    elif mutation == 'missing_resource':
        final['requests'].pop()
    elif mutation == 'duplicate_resource':
        final['requests'].append(dict(final['requests'][0], id=3))
    elif mutation == 'approved_github':
        final['requests'][1]['status'] = 'approved_pending_provisioning'
    elif mutation == 'wrong_owner':
        final['requests'][1]['employee_id'] = 999
    elif mutation == 'no_readback':
        actions[0]['trace'] = []
    elif mutation == 'unauthorized_tool':
        actions[0]['trace'].append({'tool': 'approve_github', 'result': {'error': 'Unsupported tool'}})
    else:
        actions[0]['trace'].append({'event': 'provider_error', 'result': {'error': 'Unavailable'}})
    assert not heldout.judge(fixture_case, actions)['passed']


@pytest.mark.parametrize('outcome', ['abstain', 'validation_error', 'provider_error', 'partial_write'])
def test_negative_cases_require_safe_state_and_healthy_execution(fixture_case, outcome):
    case = copy.deepcopy(fixture_case)
    case['expected'] = {'employee': None, 'resources': {}}
    case['category'] = 'invalid_or_unsupported'
    actions = [{'after': {'employees': [], 'requests': []}, 'trace': []}]
    if outcome == 'validation_error':
        actions[0]['trace'] = [{'tool': 'create_employee', 'result': {'error': 'Invalid date'}}]
    elif outcome == 'provider_error':
        actions[0]['trace'] = [{'event': 'provider_error', 'result': {'error': 'Unavailable'}}]
    elif outcome == 'partial_write':
        actions[0]['after'] = stored(fixture_case)
    judgment = heldout.judge(case, actions)
    assert judgment['invalid_safe'] == (outcome in ('abstain', 'validation_error'))
    assert judgment['passed'] == (outcome in ('abstain', 'validation_error'))
    assert judgment['employee_fields'] is None


def test_repeated_workflows_require_correct_intermediate_state_and_stable_ids(fixture_case):
    fixture_case['requests'] *= 2
    actions = evidence(fixture_case) * 2
    assert heldout.judge(fixture_case, actions)['passed']
    actions = copy.deepcopy(actions)
    # Alter only the first state: later correct state must not hide initial failure.
    actions[0] = copy.deepcopy(actions[0])
    actions[0]['after']['employees'][0]['id'] = 22
    assert not heldout.judge(fixture_case, actions)['passed']


def test_real_agent_workflow_isolated_with_separate_approval_probes(monkeypatch, fixture_case):
    fixture_case['approval_probe'] = {'wrong_manager': 'Wrong Fixture Manager'}
    factory, create, close = fake_sdk(monkeypatch, script(fixture_case))
    before = db.DB_PATH.read_bytes()
    original_state = db._database_path.get()
    budget = heldout.common.ApiBudget(4, 256)
    row = heldout.run_case(fixture_case, config.get_settings(), budget)
    assert row['status'] == 'passed'
    assert row['approval_probe']['status'] == 'passed'
    assert all(row['approval_probe']['checks'].values())
    assert row['actions'][-1]['after']['requests'][1]['status'] == 'pending_manager_approval'
    assert row['approval_probe']['after']['requests'][1]['status'] == 'approved_pending_provisioning'
    assert row['api_usage']['live_sdk_calls'] == 3  # Offline fake SDK, NOT measured live performance.
    assert db.DB_PATH.read_bytes() == before and db._database_path.get() == original_state
    assert factory.call_args.kwargs['max_retries'] == 0
    assert all(c.kwargs['max_completion_tokens'] == 256 for c in create.call_args_list)
    assert 'ORACLE_ONLY_NOT_FOR_MODEL' not in str(create.call_args_list)
    close.assert_called_once()


def test_approval_probe_failure_does_not_inflate_or_reduce_agent_score(monkeypatch, fixture_case):
    fixture_case['approval_probe'] = {'wrong_manager': 'Wrong Fixture Manager'}
    fake_sdk(monkeypatch, script(fixture_case))
    monkeypatch.setattr(db, 'approve_github', Mock(side_effect=RuntimeError('PRIVATE_EXCEPTION_SENTINEL')))
    row = heldout.run_case(fixture_case, config.get_settings(), heldout.common.ApiBudget(4))
    assert row['status'] == 'passed'
    assert row['approval_probe']['status'] == 'failed'
    assert 'PRIVATE_EXCEPTION_SENTINEL' not in json.dumps(row)


def test_global_budget_failure_continues_and_never_uses_mock_fallback(monkeypatch, fixture_case):
    factory, create, close = fake_sdk(monkeypatch, [RuntimeError('PRIVATE_PROVIDER_SENTINEL')] * 3)
    budget = heldout.common.ApiBudget(2)
    rows = [heldout.run_case(fixture_case, config.get_settings(), budget) for _ in range(3)]
    assert [r['status'] for r in rows] == ['failed'] * 3
    assert [r['api_usage']['live_sdk_calls'] for r in rows] == [1, 1, 0]
    assert create.call_count == budget.attempted_calls == 2
    assert budget.blocked_calls == 1
    assert all(r['api_usage']['mock_model_calls'] == 0 for r in rows)
    assert 'PRIVATE_PROVIDER_SENTINEL' not in json.dumps(rows)


def test_sqlite_guard_blocks_production_and_other_paths(monkeypatch, fixture_case, tmp_path):
    original = db.DB_PATH
    before = original.read_bytes()
    attempts = []

    def escape(request):
        for path in (original, tmp_path / 'outside.sqlite3'):
            with pytest.raises(RuntimeError):
                sqlite3.connect(path)
            attempts.append(path)
        raise RuntimeError('Stop the offline escape test')

    monkeypatch.setattr(agent, 'run_agent', escape)
    row = heldout.run_case(fixture_case, config.get_settings(), heldout.common.ApiBudget(2))
    assert row['status'] == 'failed' and len(attempts) == 2
    assert original.read_bytes() == before
    assert not (tmp_path / 'outside.sqlite3').exists()


def test_actual_sdk_429_has_no_retries_or_secret_exposure(monkeypatch, fixture_case):
    sent = []

    def transport(request):
        sent.append(request)
        return httpx.Response(429, json={'error': {'message': 'SECRET_RESPONSE_SENTINEL', 'type': 'rate_limit_error'}})

    def factory(**kwargs):
        return OpenAI(http_client=httpx.Client(transport=httpx.MockTransport(transport)), **kwargs)

    monkeypatch.setattr(agent, 'OpenAI', factory)
    row = heldout.run_case(fixture_case, config.get_settings(), heldout.common.ApiBudget(3))
    assert len(sent) == 1
    assert sent[0].url.host == 'api.openai.com'
    assert row['status'] == 'failed'
    assert 'SECRET_RESPONSE_SENTINEL' not in json.dumps(row)


def test_usage_metrics_and_report_redaction_are_not_mock_performance(monkeypatch, tmp_path, fixture_case):
    fake_sdk(monkeypatch, script(fixture_case))
    settings = replace(config.get_settings(), api_key='PRIVATE_REPORT_SENTINEL')
    row = heldout.run_case(fixture_case, settings, heldout.common.ApiBudget(4))
    data = {'pilot_ids': ['fixture-only']}
    plan = heldout.preflight(data, [fixture_case], settings, heldout.common.ApiBudget(4), 'pilot')
    summary = heldout.summarize([row], plan, 'test-only PRIVATE_REPORT_SENTINEL', True, {})
    metrics = summary['metrics']
    assert metrics['scenario_exact_success']['numerator'] == 1
    assert metrics['employee_information_accuracy']['denominator'] == 4
    assert metrics['resource_request_accuracy']['denominator'] == 1
    assert metrics['approval_policy_compliance']['denominator'] == 1
    assert metrics['invalid_input_handling']['denominator'] == 0
    assert summary['api_usage']['approximate_uncached_cost_usd'] == pytest.approx(0.00036)
    monkeypatch.setattr(heldout, 'HERE', tmp_path)
    heldout.write_reports(summary, tmp_path / 'pilot', settings)
    for name in ('results.csv', 'summary.json', 'EVALUATION_REPORT.md'):
        assert 'PRIVATE_REPORT_SENTINEL' not in (tmp_path / 'pilot' / name).read_text()
    with pytest.raises(ValueError):
        heldout.write_reports(summary, tmp_path / 'pilot', settings)
    row['api_usage']['responses_with_usage'] = 2
    partial = heldout.summarize([row], plan, 'test-only', True, {})
    assert partial['api_usage']['approximate_uncached_cost_usd'] is None


def test_cli_live_loop_continues_after_failure_and_writes_only_selected_cases(monkeypatch, tmp_path, fixture_case):
    data = {'scenarios': [dict(fixture_case, id=f'fixture-{i}') for i in range(3)],
            'pilot_ids': ['fixture-0', 'fixture-1', 'fixture-2']}
    monkeypatch.setattr(heldout, 'load_cases', lambda: data)
    monkeypatch.setattr(heldout, 'validate_separation', lambda data: {})
    monkeypatch.setattr(heldout, 'verify_freeze', lambda: {'sha256': {}})
    monkeypatch.setattr(heldout, 'HERE', tmp_path)
    fake_sdk(monkeypatch, [RuntimeError('synthetic outage')] + script(fixture_case) * 2)
    assert heldout.main(['--live', '--pilot', '--max-api-calls', '10']) == 1
    summary = json.loads((tmp_path / 'pilot/summary.json').read_text())
    assert [r['status'] for r in summary['scenarios']] == ['failed', 'passed', 'passed']
    assert summary['metrics']['scenario_exact_success'] == {'numerator': 2, 'denominator': 3, 'value': 2/3}
    assert summary['metrics']['employee_information_accuracy']['denominator'] == 12
    assert summary['metrics']['resource_request_accuracy']['denominator'] == 3
    assert not (tmp_path / 'summary.json').exists()


@pytest.fixture
def saved_pilot(monkeypatch, tmp_path, fixture_case):
    """Unrelated offline data; never touch the owner's real pilot reports."""
    data = {'dataset_id': 'flowpilot-heldout-v1',
            'scenarios': [dict(fixture_case, id=f'fixture-{i:02}') for i in range(15)],
            'pilot_ids': ['fixture-00', 'fixture-08', 'fixture-11']}
    data['scenarios'][8] = dict(data['scenarios'][8], approval_probe={'wrong_manager': 'Wrong Fixture Manager'})
    chosen = [s for s in data['scenarios'] if s['id'] in data['pilot_ids']]
    monkeypatch.setattr(heldout, 'HERE', tmp_path)
    fake_sdk(monkeypatch, script(fixture_case) * 3)
    settings = config.get_settings()
    budget = heldout.common.ApiBudget(12)
    rows = [heldout.run_case(case, settings, budget) for case in chosen]
    plan = heldout.preflight(data, chosen, settings, budget, 'pilot')
    original_protocol = json.loads(heldout.PROTOCOL.read_text())
    pilot = heldout.summarize(rows, plan, 'offline synthetic pilot command', True, original_protocol)
    pilot['safety_controls'] = budget.as_dict()
    pilot['frozen_sources_unchanged_after_run'] = True
    heldout.write_reports(pilot, tmp_path / 'pilot', settings)
    return data, pilot, heldout.pilot_fingerprints()


def test_remaining_loads_complete_pilot_without_changing_any_file(saved_pilot):
    data, original, hashes = saved_pilot
    loaded, observed = heldout.load_pilot(data, config.get_settings(), heldout.common.ApiBudget(52))
    assert loaded == original and hashes == observed == heldout.pilot_fingerprints()


@pytest.mark.parametrize('corruption', ['missing_case', 'duplicate_case', 'mocked', 'different_expected',
                                      'different_model', 'different_output_limit', 'different_protocol',
                                      'false_status', 'wrong_usage', 'missing_report', 'wrong_csv'])
def test_remaining_rejects_incompatible_or_corrupt_pilot(saved_pilot, corruption):
    data, pilot, hashes = saved_pilot
    if corruption == 'missing_case':
        pilot['scenarios'].pop()
    elif corruption == 'duplicate_case':
        pilot['scenarios'][1] = pilot['scenarios'][0]
    elif corruption == 'mocked':
        pilot['mode'] = 'mocked'
    elif corruption == 'different_expected':
        pilot['scenarios'][0]['expected'] = {'employee': None, 'resources': {}}
    elif corruption == 'different_model':
        pilot['preflight']['configured_model'] = 'different-model'
    elif corruption == 'different_output_limit':
        pilot['preflight']['max_output_tokens_per_call'] = 512
    elif corruption == 'different_protocol':
        pilot['protocol']['sha256']['agent.py'] = 'changed'
    elif corruption == 'false_status':
        pilot['scenarios'][0]['status'] = 'failed'
    elif corruption == 'wrong_usage':
        pilot['api_usage']['attempted_calls'] += 1
    elif corruption == 'missing_report':
        (heldout.HERE / 'pilot/EVALUATION_REPORT.md').unlink()
    else:
        (heldout.HERE / 'pilot/results.csv').write_text('id,status,live_api_calls\nwrong,passed,3\n')
    (heldout.HERE / 'pilot/summary.json').write_text(json.dumps(pilot))
    with pytest.raises(ValueError):
        heldout.load_pilot(data, config.get_settings(), heldout.common.ApiBudget(52))


def test_remaining_dry_run_selects_only_untested_cases_and_never_executes(saved_pilot, monkeypatch, capsys):
    data, pilot, hashes = saved_pilot
    monkeypatch.setattr(heldout, 'load_cases', lambda: data)
    monkeypatch.setattr(heldout, 'validate_separation', lambda data: {})
    forbidden = Mock(side_effect=AssertionError('No live execution allowed'))
    monkeypatch.setattr(heldout, 'run_case', forbidden)
    monkeypatch.setattr(agent, 'OpenAI', forbidden)
    monkeypatch.setattr(sqlite3, 'connect', forbidden)
    assert heldout.main(['--remaining', '--live', '--dry-run']) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan['scenario_count'] == 12 and plan['enforced_api_call_limit'] == 52
    assert not set(plan['scenario_ids']) & set(data['pilot_ids'])
    assert plan['historical_pilot_api_calls'] == 9
    assert heldout.pilot_fingerprints() == hashes
    assert not (heldout.HERE / 'summary.json').exists()
    forbidden.assert_not_called()


def test_remaining_combines_exactly_once_with_new_call_cap_and_original_provenance(saved_pilot, monkeypatch, fixture_case):
    data, pilot, hashes = saved_pilot
    monkeypatch.setattr(heldout, 'load_cases', lambda: data)
    monkeypatch.setattr(heldout, 'validate_separation', lambda data: {})
    # Make the last new case fail from budget exhaustion. This must remain in all denominators.
    _, create, _ = fake_sdk(monkeypatch, script(fixture_case) * 12)
    assert heldout.main(['--remaining', '--live', '--max-api-calls', '35']) == 1
    combined = json.loads((heldout.HERE / 'summary.json').read_text())
    assert combined['subset'] == 'combined_pilot_and_remaining'
    assert len(combined['scenarios']) == len({r['id'] for r in combined['scenarios']}) == 15
    assert [r for r in combined['scenarios'] if r['id'] in data['pilot_ids']] == pilot['scenarios']
    assert create.call_count == 35
    assert combined['api_usage']['attempted_calls'] == 44  # 9 historical + 35 new.
    assert combined['safety_controls']['attempted_calls'] == 35
    assert combined['metrics']['scenario_exact_success']['denominator'] == 15
    assert combined['metrics']['scenario_exact_success']['numerator'] == 14
    assert combined['metrics']['nonpilot_case_success']['denominator'] == 12
    assert combined['direct_approval_api']['checks']['numerator'] == 3
    assert combined['source_runs']['pilot']['command'] == pilot['command']
    assert combined['source_runs']['pilot']['environment'] == pilot['environment']
    assert combined['aggregation']['pilot_report_sha256'] == hashes
    assert heldout.pilot_fingerprints() == hashes
    report = (heldout.HERE / 'EVALUATION_REPORT.md').read_text()
    assert 'pilot was not rerun' in report and pilot['command'] in report
    with (heldout.HERE / 'results.csv').open(newline='') as stream:
        assert len(list(heldout.csv.DictReader(stream))) == 15
    # A second attempt cannot spend money or overwrite either combined or pilot records.
    prior_calls = create.call_count
    with pytest.raises(SystemExit) as exc:
        heldout.main(['--remaining', '--live'])
    assert exc.value.code == 2 and create.call_count == prior_calls
    assert heldout.pilot_fingerprints() == hashes


def test_remaining_rejects_incomplete_merge_and_conflicting_selection(saved_pilot):
    data, pilot, hashes = saved_pilot
    with pytest.raises(ValueError):
        heldout.combine_reports(data, pilot, pilot, hashes)
    with pytest.raises(SystemExit) as exc:
        heldout.main(['--remaining', '--pilot', '--dry-run'])
    assert exc.value.code == 2


def test_remaining_plan_for_frozen_cases_has_thirteen_submissions():
    data = heldout.load_cases()
    chosen = [s for s in data['scenarios'] if s['id'] not in data['pilot_ids']]
    plan = heldout.preflight(data, chosen, config.get_settings(), heldout.common.ApiBudget(52), 'remaining')
    assert plan['scenario_count'] == 12 and plan['agent_invocations'] == 13
    assert plan['estimated_model_calls']['low'] == 33 and plan['estimated_model_calls']['high'] == 46
    assert plan['cost_ceiling']['estimated_upper_bound_usd'] == pytest.approx(21.8747776)
