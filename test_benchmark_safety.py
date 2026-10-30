import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import httpx  # Already required by the installed OpenAI SDK.
import pytest
from openai import OpenAI

import agent
import db
from evaluation import run_benchmark as benchmark


@pytest.fixture
def catalog():
    return benchmark.load_scenarios()


@pytest.fixture
def protected_demo(tmp_path, monkeypatch):
    path = tmp_path / 'demo.db'
    path.write_bytes(b'untouched synthetic demo sentinel')
    monkeypatch.setattr(benchmark, 'PRODUCTION_DB', path)
    return path


@pytest.mark.parametrize('live_flag', [False, True])
def test_dry_run_executes_nothing_and_requires_no_key(tmp_path, monkeypatch, capsys, live_flag):
    monkeypatch.setattr(benchmark, 'load_environment', lambda: None)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('OPENAI_MODEL', raising=False)
    forbidden = Mock(side_effect=AssertionError('Dry run must not execute'))
    monkeypatch.setattr(benchmark, 'run_benchmark', forbidden)
    monkeypatch.setattr(benchmark, 'write_reports', forbidden)
    monkeypatch.setattr(db, 'connect', forbidden)
    monkeypatch.setattr(benchmark.tempfile, 'TemporaryDirectory', forbidden)
    monkeypatch.setattr(agent, 'OpenAI', forbidden)
    out = tmp_path / 'no-reports'
    argv = ['evaluation/run_benchmark.py', '--dry-run', '--max-api-calls', '40', '--output-dir', str(out)]
    if live_flag:
        argv.append('--live')
    monkeypatch.setattr('sys.argv', argv)
    assert benchmark.main() == 0
    output = capsys.readouterr().out
    assert 'S01' in output and 'R04' in output and 'approval_api' in output
    assert 'estimated_upper_bound_usd' in output
    assert '"live_api_calls_upper_bound": 40' in output
    forbidden.assert_not_called()
    assert not out.exists()


def test_dry_run_call_and_cost_math(catalog):
    budget = benchmark.ApiBudget(100, 1024, 'gpt-4.1-mini')
    plan = benchmark.dry_run_plan(catalog, budget)
    assert sum(row['agent_invocations'] for row in plan['scenarios']) == 24
    assert sum(row['live_api_calls_upper_bound_before_global_cap'] for row in plan['scenarios']) == 192
    assert all(row['live_api_calls_upper_bound_before_global_cap'] == 0
               for row in plan['scenarios'] if row['interface'] == 'approval_api')
    assert plan['live_api_calls_upper_bound'] == 100
    assert plan['cost_ceiling']['estimated_upper_bound_usd'] == pytest.approx(42.06688)
    assert budget.attempted_calls == 0


@pytest.mark.parametrize(('calls', 'tokens'), [(0, 1024), (-1, 1024), (True, 1024), (10, 0), (10, -5)])
def test_invalid_budgets_are_rejected(calls, tokens):
    with pytest.raises(ValueError):
        benchmark.ApiBudget(calls, tokens)


@pytest.mark.parametrize(('model', 'tokens'), [('unpriced-synthetic-model', 1024), ('gpt-4.1-mini', 40000)])
def test_unpriced_models_and_excessive_output_caps_reject_cost_claims(model, tokens):
    with pytest.raises(ValueError):
        benchmark.cost_ceiling(benchmark.ApiBudget(10, tokens, model))


def test_global_limit_counts_failed_calls_across_scenarios(catalog, protected_demo, monkeypatch):
    create = Mock(side_effect=RuntimeError('Synthetic provider failure'))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=Mock())
    factory = Mock(return_value=client)
    monkeypatch.setattr(agent, 'OpenAI', factory)
    budget = benchmark.ApiBudget(2, 256, 'gpt-4.1-mini')
    chosen = catalog[:3] + [s for s in catalog if s['interface'] == 'approval_api']
    summary = benchmark.run_benchmark(chosen, live=True, budget=budget)
    assert create.call_count == budget.attempted_calls == 2
    assert budget.blocked_calls == 1
    assert summary['api_usage']['live_sdk_calls'] == 2
    assert summary['api_usage']['mock_model_calls'] == 0
    assert [row['status'] for row in summary['scenarios']] == ['failed'] * 3 + ['passed'] * 4
    assert any('limit reached' in error for error in summary['scenarios'][2]['errors'])
    for call in factory.call_args_list:
        assert call.kwargs == {'max_retries': 0, 'timeout': 60.0, 'base_url': 'https://api.openai.com/v1'}
    for call in create.call_args_list:
        assert call.kwargs['max_completion_tokens'] == 256
        assert call.kwargs['n'] == 1
        assert call.kwargs['service_tier'] == 'default'
        assert call.kwargs['stream'] is False
    assert summary['production_database_unchanged']


@pytest.mark.parametrize('http_status', [200, 429])
def test_real_sdk_has_no_hidden_retries_using_offline_transport(http_status):
    sent = []

    def transport(request):
        sent.append(request)
        if http_status == 429:
            return httpx.Response(429, json={'error': {'message': 'Synthetic rate limit', 'type': 'rate_limit_error'}})
        return httpx.Response(200, json={
            'id': 'offline-test', 'object': 'chat.completion', 'created': 0, 'model': 'gpt-4.1-mini',
            'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'No actions'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 7, 'completion_tokens': 3, 'total_tokens': 10},
        })

    def factory(**kwargs):
        return OpenAI(api_key='synthetic-key-only', http_client=httpx.Client(transport=httpx.MockTransport(transport)), **kwargs)

    recorder = benchmark.ModelRecorder(benchmark.ApiBudget(1, 64, 'gpt-4.1-mini'))
    client = recorder.live_factory(factory)()
    try:
        if http_status == 429:
            with pytest.raises(Exception):
                client.chat.completions.create(messages=[{'role': 'user', 'content': 'Synthetic input'}])
        else:
            client.chat.completions.create(messages=[{'role': 'user', 'content': 'Synthetic input'}])
        with pytest.raises(benchmark.ApiCallLimitError):
            client.chat.completions.create(messages=[])
    finally:
        recorder.close()
    assert len(sent) == recorder.live_calls == 1
    assert sent[0].url.host == 'api.openai.com'
    body = json.loads(sent[0].content)
    assert body['max_completion_tokens'] == 64
    assert body['n'] == 1 and body['service_tier'] == 'default'


def test_all_scenarios_in_live_wrapper_keep_temporary_database_isolation(catalog, protected_demo, monkeypatch):
    before = protected_demo.read_bytes()
    original_path = db.DB_PATH
    original_connect = db.connect
    connected = []

    def spy_connect():
        connected.append(db.DB_PATH)
        assert db.DB_PATH != protected_demo and db.DB_PATH != original_path
        return original_connect()

    monkeypatch.setattr(db, 'connect', spy_connect)
    for scenario in catalog:
        fake_clients = []
        for action in scenario['actions'] if scenario['interface'] == 'agent' else []:
            # Fake server responses exercise the live wrapper offline, never live performance.
            client = benchmark.ModelRecorder().mock_factory(action)()
            client.close = Mock()
            fake_clients.append(client)
        monkeypatch.setattr(agent, 'OpenAI', Mock(side_effect=fake_clients))
        result = benchmark.run_scenario(scenario, live=True)
        assert result['status'] == 'passed'
    assert len(set(connected)) == 25
    assert all(not path.exists() for path in connected)
    assert protected_demo.read_bytes() == before
    assert db.DB_PATH == original_path


@pytest.mark.parametrize('live', [False, True])
def test_isolation_guard_blocks_an_attempt_to_restore_production_path(catalog, protected_demo, monkeypatch, live):
    before = protected_demo.read_bytes()
    original_path = db.DB_PATH

    def attempt_escape(request):
        db.DB_PATH = protected_demo
        db.create_employee('Synthetic', 'Synthetic role', '2029-01-01', 'Synthetic manager')
        pytest.fail('Path escape should have been rejected')

    monkeypatch.setattr(agent, 'run_agent', attempt_escape)
    result = benchmark.run_scenario(catalog[0], live=live)
    assert result['status'] == 'failed'
    assert protected_demo.read_bytes() == before
    assert db.DB_PATH == original_path


def test_dotenv_loading_is_allowlisted_noninterpolating_and_read_only(tmp_path, monkeypatch, capsys, caplog):
    path = tmp_path / '.env'
    path.write_text('OPENAI_API_KEY=FILE_SECRET_SENTINEL\nOPENAI_MODEL=${OPENAI_API_KEY}\n'
                    'OPENAI_LOG=debug\nUNRELATED_SETTING=should-not-load\n', encoding='utf-8')
    before = path.read_bytes()
    monkeypatch.setenv('OPENAI_API_KEY', 'SHELL_SECRET_SENTINEL')
    monkeypatch.setenv('OPENAI_MODEL', 'track-original-value-for-restoration')
    monkeypatch.delenv('OPENAI_MODEL', raising=False)
    monkeypatch.delenv('OPENAI_LOG', raising=False)
    monkeypatch.delenv('UNRELATED_SETTING', raising=False)
    benchmark.load_environment(path)
    assert benchmark.os.environ['OPENAI_API_KEY'] == 'SHELL_SECRET_SENTINEL'
    assert benchmark.os.environ['OPENAI_MODEL'] == '${OPENAI_API_KEY}'
    assert 'UNRELATED_SETTING' not in benchmark.os.environ and 'OPENAI_LOG' not in benchmark.os.environ
    monkeypatch.delenv('OPENAI_API_KEY')
    benchmark.load_environment(path)
    assert benchmark.os.environ['OPENAI_API_KEY'] == 'FILE_SECRET_SENTINEL'
    assert path.read_bytes() == before
    captured = capsys.readouterr()
    assert 'SECRET_SENTINEL' not in captured.out + captured.err + caplog.text


def test_cli_loads_dotenv_for_dry_run_without_disclosing_key(tmp_path, monkeypatch, capsys):
    path = tmp_path / '.env'
    path.write_text('OPENAI_API_KEY=DRY_SECRET_SENTINEL\nOPENAI_MODEL=gpt-4.1-mini\n', encoding='utf-8')
    monkeypatch.setenv('OPENAI_API_KEY', 'track-original-value-for-restoration')
    monkeypatch.setenv('OPENAI_MODEL', 'track-original-value-for-restoration')
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('OPENAI_MODEL', raising=False)
    load = benchmark.load_environment
    monkeypatch.setattr(benchmark, 'load_environment', lambda: load(path))
    monkeypatch.setattr('sys.argv', ['evaluation/run_benchmark.py', '--dry-run'])
    assert benchmark.main() == 0
    captured = capsys.readouterr()
    assert 'gpt-4.1-mini' in captured.out
    assert 'DRY_SECRET_SENTINEL' not in captured.out + captured.err


def test_provider_logging_is_suppressed_and_restored(caplog):
    caplog.set_level(logging.DEBUG)
    recorder = benchmark.ModelRecorder()

    def noisy_factory(**kwargs):
        logging.getLogger('openai.http').error('SECRET_LOG_SENTINEL')
        raise RuntimeError('SECRET_ERROR_SENTINEL')

    previous = logging.root.manager.disable
    with pytest.raises(RuntimeError):
        recorder.live_factory(noisy_factory)()
    assert logging.root.manager.disable == previous
    assert 'SECRET_LOG_SENTINEL' not in caplog.text
    assert 'SECRET_ERROR_SENTINEL' not in json.dumps(recorder.as_dict())


def test_mode_output_directories_and_overwrite_guards(tmp_path):
    assert benchmark.resolve_output_dir(tmp_path, False) == tmp_path / 'mocked'
    assert benchmark.resolve_output_dir(tmp_path, True) == tmp_path / 'live'
    assert benchmark.resolve_output_dir(tmp_path / 'live', True) == tmp_path / 'live'
    with pytest.raises(ValueError):
        benchmark.resolve_output_dir(tmp_path / 'mocked', True)
    summary = benchmark.summarize([], False, 'synthetic command', True)
    benchmark.write_reports(summary, tmp_path / 'mocked')
    before = (tmp_path / 'mocked' / 'summary.json').read_bytes()
    with pytest.raises(ValueError):
        benchmark.write_reports(dict(summary, mode='live'), tmp_path / 'mocked')
    assert (tmp_path / 'mocked' / 'summary.json').read_bytes() == before
    benchmark.write_reports(summary, tmp_path / 'custom')
    with pytest.raises(ValueError):
        benchmark.write_reports(dict(summary, mode='live'), tmp_path / 'custom')


def test_reports_redact_credentials_even_if_a_result_echoes_them(catalog, protected_demo, tmp_path, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'REPORT_SECRET_SENTINEL')
    summary = benchmark.run_benchmark([catalog[0]], command='synthetic REPORT_SECRET_SENTINEL')
    summary['scenarios'][0]['errors'].append('REPORT_SECRET_SENTINEL')
    benchmark.write_reports(summary, tmp_path / 'mocked')
    for name in ('summary.json', 'results.csv', 'EVALUATION_REPORT.md'):
        text = (tmp_path / 'mocked' / name).read_text(encoding='utf-8')
        assert 'REPORT_SECRET_SENTINEL' not in text
        assert '[REDACTED]' in text
