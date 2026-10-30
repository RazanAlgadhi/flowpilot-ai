import copy
import csv
import json
from collections import Counter
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from openai.types.chat import ChatCompletionMessage

import agent
import db
from evaluation import run_benchmark as benchmark


@pytest.fixture
def scenarios():
    return benchmark.load_scenarios()


@pytest.fixture
def protected_demo(tmp_path, monkeypatch):
    # A sentinel file, never the user's real demo database.
    path = tmp_path / 'untouched-demo.db'
    path.write_bytes(b'fictional production database sentinel')
    monkeypatch.setattr(benchmark, 'PRODUCTION_DB', path)
    return path


def test_all_25_mocked_scenarios_are_isolated_and_reports_match(scenarios, protected_demo, tmp_path, monkeypatch):
    assert Counter(item['category'] for item in scenarios) == benchmark.CATEGORY_COUNTS
    assert len({item['id'] for item in scenarios}) == 25
    assert Counter(item['interface'] for item in scenarios) == {'agent': 21, 'approval_api': 4}
    original_path, original_factory, original_tools = db.DB_PATH, agent.OpenAI, dict(agent.FUNCTIONS)
    before = protected_demo.read_bytes()
    original_connect = db.connect
    connected_paths = []

    def connect_only_to_benchmark_database():
        assert db.DB_PATH != protected_demo
        assert db.DB_PATH != original_path
        assert db.DB_PATH.name == 'scenario.db'
        connected_paths.append(db.DB_PATH)
        return original_connect()

    monkeypatch.setattr(db, 'connect', connect_only_to_benchmark_database)
    monkeypatch.setenv('OPENAI_API_KEY', 'DO_NOT_EXPOSE_SYNTHETIC_CREDENTIAL')
    summary = benchmark.run_benchmark(scenarios, command='python evaluation/run_benchmark.py')
    assert summary['metrics']['overall_pass_rate'] == {'numerator': 25, 'denominator': 25, 'value': 1.0}
    assert summary['production_database_unchanged'] is True
    assert protected_demo.read_bytes() == before
    assert db.DB_PATH == original_path
    assert agent.OpenAI is original_factory
    assert agent.FUNCTIONS == original_tools
    assert len(set(connected_paths)) == 25
    assert all(not path.exists() for path in connected_paths)
    assert summary['api_usage']['live_sdk_calls'] == 0
    assert summary['api_usage']['mock_model_calls'] > 0
    assert summary['api_usage']['observed_tokens'] is None
    assert summary['api_usage']['cost_estimate_usd'] is None
    for metric in summary['metrics']['category_pass_rates'].values():
        assert metric['numerator'] == metric['denominator']

    output = tmp_path / 'reports'
    benchmark.write_reports(summary, output)
    saved = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
    assert saved == summary
    with (output / 'results.csv').open(encoding='utf-8', newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 25
    assert all(row['status'] == 'passed' for row in rows)
    assert Counter(row['execution_mode'] for row in rows) == {'mocked': 21, 'direct_approval_api': 4}
    report = (output / 'EVALUATION_REPORT.md').read_text(encoding='utf-8')
    assert '25/25 (100.0%)' in report
    assert 'not live LLM performance' in report
    assert summary['command'] in report
    assert 'DO_NOT_EXPOSE_SYNTHETIC_CREDENTIAL' not in json.dumps(summary) + report


@pytest.mark.parametrize('defect', ['wrong_role', 'missing_resource'])
def test_assertions_fail_when_mock_plan_produces_wrong_state(scenarios, protected_demo, defect):
    scenario = copy.deepcopy(scenarios[0])
    if defect == 'wrong_role':
        scenario['actions'][0]['mock_tool_batches'][0][0]['arguments']['role'] = 'Wrong synthetic role'
    else:
        scenario['actions'][0]['mock_tool_batches'][1].pop()
    result = benchmark.run_scenario(scenario)
    assert result['status'] == 'failed'
    expected_failure = 'employee_details' if defect == 'wrong_role' else 'request_statuses'
    assert any(item['type'] == expected_failure for item in result['failed_assertions'])


def test_unexpected_scenario_exception_does_not_stop_remaining_scenarios(scenarios, protected_demo, tmp_path, monkeypatch):
    approval = next(s for s in scenarios if s['id'] == 'A01')
    monkeypatch.setattr(db, 'approve_github', Mock(side_effect=RuntimeError('PRIVATE_ERROR_SENTINEL')))
    summary = benchmark.run_benchmark([approval, scenarios[0]])
    assert [row['status'] for row in summary['scenarios']] == ['failed', 'passed']
    assert summary['metrics']['overall_pass_rate'] == {'numerator': 1, 'denominator': 2, 'value': 0.5}
    assert summary['production_database_unchanged']
    benchmark.write_reports(summary, tmp_path / 'failed-report')
    report = (tmp_path / 'failed-report' / 'EVALUATION_REPORT.md').read_text(encoding='utf-8')
    assert 'A01: Wrong manager' in report
    assert 'scenario_completed' in report
    assert 'PRIVATE_ERROR_SENTINEL' not in json.dumps(summary) + report


@pytest.mark.parametrize('scenario_id', ['M01', 'I03'])
def test_safe_abstention_is_not_invented_detection_success(scenarios, protected_demo, monkeypatch, scenario_id):
    monkeypatch.setattr(agent, 'run_agent', lambda request: ('No actions were performed.', []))
    result = benchmark.run_scenario(next(s for s in scenarios if s['id'] == scenario_id))
    assert result['status'] == 'failed'
    assert result['final_state'] == []
    failed = next(item for item in result['failed_assertions'] if item['type'] == 'validation_error')
    assert 'insufficient evidence' in failed['note']


@pytest.mark.parametrize('scenario_id', ['S01', 'M01'])
def test_live_call_failure_never_falls_back_to_mock(scenarios, protected_demo, monkeypatch, scenario_id):
    create = Mock(side_effect=RuntimeError('PRIVATE_PROVIDER_SENTINEL'))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=Mock())
    monkeypatch.setattr(agent, 'OpenAI', Mock(return_value=client))
    row = benchmark.run_scenario(next(s for s in scenarios if s['id'] == scenario_id), live=True)
    assert row['execution_mode'] == 'live'
    assert row['status'] == 'failed'
    assert row['api_usage']['live_sdk_calls'] == 1
    assert row['api_usage']['mock_model_calls'] == 0
    assert row['api_usage']['observed_tokens'] is None
    assert row['final_state'] == []
    assert any(item['type'] == 'no_provider_or_execution_limit_failure' for item in row['failed_assertions'])
    assert 'PRIVATE_PROVIDER_SENTINEL' not in json.dumps(row)
    client.close.assert_called_once()


def test_live_initialization_failure_is_recorded_without_mock_fallback(scenarios, protected_demo, monkeypatch):
    monkeypatch.setattr(agent, 'OpenAI', Mock(side_effect=RuntimeError('PRIVATE_SETUP_SENTINEL')))
    row = benchmark.run_scenario(scenarios[0], live=True)
    assert row['status'] == 'failed'
    assert row['api_usage']['mock_model_calls'] == row['api_usage']['live_sdk_calls'] == 0
    assert row['api_usage']['errors'][0]['stage'] == 'client_initialization'
    assert 'PRIVATE_SETUP_SENTINEL' not in json.dumps(row)


@pytest.mark.parametrize('complete_usage', [True, False])
def test_live_observer_records_only_actual_usage_metadata(scenarios, protected_demo, monkeypatch, complete_usage):
    scenario = next(s for s in scenarios if s['id'] == 'S05')
    arguments = scenario['actions'][0]['mock_tool_batches'][0][0]['arguments']
    tool_message = ChatCompletionMessage(role='assistant', tool_calls=[{
        'id': 'usage_test_call', 'type': 'function',
        'function': {'name': 'create_employee', 'arguments': json.dumps(arguments)},
    }])
    final_message = ChatCompletionMessage(role='assistant', content='Complete')
    usage = SimpleNamespace(prompt_tokens=7, completion_tokens=3, total_tokens=10)
    responses = [SimpleNamespace(choices=[SimpleNamespace(message=tool_message)], usage=usage),
                 SimpleNamespace(choices=[SimpleNamespace(message=final_message)], usage=usage if complete_usage else None)]
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(side_effect=responses))), close=Mock())
    monkeypatch.setattr(agent, 'OpenAI', Mock(return_value=client))
    summary = benchmark.run_benchmark([scenario], live=True)
    assert summary['scenarios'][0]['status'] == 'passed'
    totals = summary['api_usage']
    assert totals['live_sdk_calls'] == 2
    assert totals['mock_model_calls'] == 0
    assert totals['usage_coverage'] == {'numerator': 2 if complete_usage else 1, 'denominator': 2}
    assert totals['observed_tokens']['total_tokens'] == (20 if complete_usage else 10)
    assert totals['usage_complete'] == complete_usage
    assert totals['cost_estimate_usd'] is None


def test_direct_approval_tests_do_not_use_a_model_even_in_live_mode(scenarios, protected_demo):
    approvals = [s for s in scenarios if s['interface'] == 'approval_api']
    summary = benchmark.run_benchmark(approvals, live=True)
    assert summary['metrics']['overall_pass_rate']['numerator'] == 4
    assert all(row['execution_mode'] == 'direct_approval_api' for row in summary['scenarios'])
    assert summary['api_usage']['live_sdk_calls'] == summary['api_usage']['mock_model_calls'] == 0


def test_unexercised_fault_injection_cannot_pass(scenarios, protected_demo, monkeypatch):
    scenario = next(s for s in scenarios if s['id'] == 'R04')

    def skip_resource_tool(request):
        db.create_employee(**scenario['actions'][0]['mock_tool_batches'][0][0]['arguments'])
        return 'Workflow stopped: synthetic error', [{'tool': 'create_request', 'result': {'error': 'Tool execution failed'}}]

    monkeypatch.setattr(agent, 'run_agent', skip_resource_tool)
    row = benchmark.run_scenario(scenario)
    assert row['injected_failure_calls'] == 0
    assert row['status'] == 'failed'
    assert any(item['type'] == 'injected_failure_observed' for item in row['failed_assertions'])


@pytest.mark.parametrize(('durations', 'median_numerator', 'median_denominator'), [
    ([1, 3, 5, 7], 8, 2), ([1, 3, 9], 3, 1),
])
def test_metric_numerators_and_denominators_include_failures(durations, median_numerator, median_denominator):
    rows = [{'category': 'duplicate', 'interface': 'agent', 'status': 'passed' if index == 0 else 'failed',
             'duration_seconds': duration, 'api_usage': benchmark.ModelRecorder().as_dict()}
            for index, duration in enumerate(durations)]
    summary = benchmark.summarize(rows, False, 'test command', True)
    metrics = summary['metrics']
    assert metrics['overall_pass_rate'] == {'numerator': 1, 'denominator': len(durations), 'value': 1 / len(durations)}
    assert metrics['duplicate_prevention_success_rate'] == metrics['overall_pass_rate']
    assert metrics['average_execution_seconds']['numerator'] == sum(durations)
    assert metrics['average_execution_seconds']['denominator'] == len(durations)
    assert metrics['median_execution_seconds'] == {
        'numerator': median_numerator, 'denominator': median_denominator,
        'value': median_numerator / median_denominator, 'sample_count': len(durations),
    }


@pytest.mark.parametrize('defect', ['duplicate_id', 'wrong_category_count', 'unknown_assertion'])
def test_invalid_scenario_catalog_is_rejected(scenarios, tmp_path, defect):
    if defect == 'duplicate_id':
        scenarios[1]['id'] = scenarios[0]['id']
    elif defect == 'wrong_category_count':
        scenarios.pop()
    else:
        scenarios[0]['assertions'][0]['type'] = 'unsupported_assertion'
    path = tmp_path / 'invalid.json'
    path.write_text(json.dumps({'schema_version': 1, 'scenarios': scenarios}), encoding='utf-8')
    with pytest.raises(ValueError):
        benchmark.load_scenarios(path)


def test_live_cli_requires_credentials_after_environment_loading(monkeypatch):
    monkeypatch.setattr(benchmark, 'load_environment', lambda: None)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.setattr('sys.argv', ['evaluation/run_benchmark.py', '--live'])
    with pytest.raises(SystemExit) as exc:
        benchmark.main()
    assert exc.value.code == 2


def test_production_file_change_is_reported_without_restoring_it(scenarios, protected_demo, monkeypatch):
    original = benchmark.run_scenario

    def simulated_external_writer(scenario, live=False, **kwargs):
        row = original(scenario, live, **kwargs)
        protected_demo.write_bytes(b'simulated external process change')
        return row

    monkeypatch.setattr(benchmark, 'run_scenario', simulated_external_writer)
    summary = benchmark.run_benchmark([scenarios[0]])
    assert summary['production_database_unchanged'] is False
    assert protected_demo.read_bytes() == b'simulated external process change'
