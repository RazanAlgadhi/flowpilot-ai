import hashlib
import json
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

import agent
import db
import runtime_config as config
import safeguards
from demo_scenarios import SCENARIOS, request_for
from test_agent import response, tool_call
from tools.audit_repository import audit, ignored_paths, scan_text

REAL_LOAD_SETTINGS = config.load_settings


def test_cloud_secrets_environment_precedence_and_local_fallback(monkeypatch, tmp_path):
    for key in ('OPENAI_API_KEY', 'OPENAI_MODEL', 'FLOWPILOT_PUBLIC_DEMO', 'FLOWPILOT_DATA_DIR',
                'FLOWPILOT_MAX_MODEL_CALLS', 'FLOWPILOT_MAX_OUTPUT_TOKENS', 'FLOWPILOT_DAILY_API_QUOTA', 'FLOWPILOT_DB_PATH'):
        monkeypatch.delenv(key, raising=False)
    loader = Mock(return_value={'OPENAI_API_KEY': 'LOCAL_TEST_CREDENTIAL'})
    monkeypatch.setattr(config.dotenv, 'dotenv_values', loader)
    local = REAL_LOAD_SETTINGS()
    assert local.api_key == 'LOCAL_TEST_CREDENTIAL'
    cloud = REAL_LOAD_SETTINGS({'OPENAI_API_KEY': 'CLOUD_TEST_CREDENTIAL', 'FLOWPILOT_MAX_MODEL_CALLS': 3})
    assert cloud.api_key == 'CLOUD_TEST_CREDENTIAL'
    assert cloud.max_model_calls == 3
    assert cloud.public_demo is True
    assert 'CLOUD_TEST_CREDENTIAL' not in repr(cloud)
    monkeypatch.setenv('OPENAI_API_KEY', 'ENV_TEST_CREDENTIAL')
    assert REAL_LOAD_SETTINGS({'OPENAI_API_KEY': 'CLOUD_TEST_CREDENTIAL'}).api_key == 'ENV_TEST_CREDENTIAL'
    assert loader.call_args.kwargs == {'interpolate': False, 'verbose': False}


@pytest.mark.parametrize(('name', 'value'), [
    ('FLOWPILOT_MAX_MODEL_CALLS', '0'), ('FLOWPILOT_MAX_OUTPUT_TOKENS', '4097'),
    ('FLOWPILOT_DAILY_API_QUOTA', '-1'), ('FLOWPILOT_MAX_MODEL_CALLS', 'PRIVATE_CONFIG_SENTINEL'),
])
def test_invalid_server_limits_fail_without_value_disclosure(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError) as exc:
        REAL_LOAD_SETTINGS(local_env=False)
    assert 'PRIVATE_CONFIG_SENTINEL' not in str(exc.value)


def test_daily_quota_is_atomic_across_independent_threads():
    settings = replace(config.get_settings(), daily_api_quota=5)
    barrier = Barrier(12)

    def reserve(_):
        barrier.wait()
        try:
            safeguards.reserve_api_request(settings)
            return True
        except safeguards.QuotaExceeded:
            return False

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(reserve, range(12)))
    assert sum(results) == 5
    with closing(safeguards.connect_control(settings)) as con:
        assert con.execute('SELECT SUM(count) FROM daily_requests').fetchone()[0] == 5


def test_quota_is_shared_by_separate_python_processes(tmp_path):
    script = """from pathlib import Path
import sys
from runtime_config import Settings
from safeguards import reserve_api_request, QuotaExceeded
try:
    reserve_api_request(Settings(data_dir=Path(sys.argv[1]), daily_api_quota=1))
    print('reserved')
except QuotaExceeded:
    print('blocked')
"""
    command = [__import__('sys').executable, '-c', script, str(tmp_path / 'shared')]
    first = subprocess.run(command, capture_output=True, text=True, check=True)
    second = subprocess.run(command, capture_output=True, text=True, check=True)
    assert first.stdout.strip() == 'reserved'
    assert second.stdout.strip() == 'blocked'


def test_quota_uses_utc_days_and_zero_is_an_off_switch():
    settings = replace(config.get_settings(), daily_api_quota=1)
    day = datetime(2029, 1, 1, 23, 59, tzinfo=timezone.utc)
    safeguards.reserve_api_request(settings, now=day)
    with pytest.raises(safeguards.QuotaExceeded):
        safeguards.reserve_api_request(settings, now=day)
    assert safeguards.reserve_api_request(settings, now=datetime(2029, 1, 2, tzinfo=timezone.utc)) == 1
    with pytest.raises(safeguards.QuotaExceeded):
        safeguards.reserve_api_request(replace(settings, daily_api_quota=0), now=datetime(2029, 1, 3, tzinfo=timezone.utc))


def test_quota_storage_failure_blocks_provider_call(monkeypatch, tmp_path):
    blocked_dir = tmp_path / 'not-a-directory'
    blocked_dir.write_text('synthetic', encoding='utf-8')
    create = Mock()
    monkeypatch.setattr(agent, 'OpenAI', Mock(return_value=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))))
    with config.use_settings(replace(config.get_settings(), data_dir=blocked_dir)):
        answer, trace = agent.run_agent('Synthetic request')
    assert 'quota storage is unavailable' in answer
    assert trace[-1]['event'] == 'quota_error'
    create.assert_not_called()


def test_failed_provider_attempt_consumes_quota_and_exhaustion_is_safe(monkeypatch):
    create = Mock(side_effect=RuntimeError('PRIVATE_PROVIDER_CREDENTIAL'))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=Mock())
    factory = Mock(return_value=client)
    monkeypatch.setattr(agent, 'OpenAI', factory)
    settings = replace(config.get_settings(), daily_api_quota=1, max_output_tokens=128)
    with config.use_settings(settings):
        first, _ = agent.run_agent('First synthetic request')
        second, trace = agent.run_agent('Second synthetic request')
    assert create.call_count == 1
    assert 'PRIVATE_PROVIDER_CREDENTIAL' not in first + second + json.dumps(trace)
    assert 'Daily demo API quota reached' in second
    assert trace[-1]['event'] == 'quota_error'
    assert factory.call_args.kwargs['max_retries'] == 0
    assert create.call_args.kwargs['max_completion_tokens'] == 128
    assert create.call_args.kwargs['n'] == 1
    assert client.close.call_count == 2


def test_configurable_execution_limit_and_oversized_input(monkeypatch, employee_details):
    create = Mock(return_value=response(tool_call('create_employee', employee_details)))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=Mock())
    factory = Mock(return_value=client)
    monkeypatch.setattr(agent, 'OpenAI', factory)
    with config.use_settings(replace(config.get_settings(), max_model_calls=2)):
        answer, trace = agent.run_agent('Synthetic looping request')
    assert create.call_count == 2
    assert 'Execution limit' in answer and trace[-1]['event'] == 'execution_limit'
    factory.reset_mock()
    answer, trace = agent.run_agent('x' * 4001)
    assert trace[0]['event'] == 'input_error'
    factory.assert_not_called()


def test_workflow_lock_rejects_overlap_and_rapid_repeated_requests():
    settings = config.get_settings()
    with safeguards.workflow_lease(settings, 'session-a', 'synthetic request', now=100):
        with pytest.raises(safeguards.WorkflowBusy):
            with safeguards.workflow_lease(settings, 'session-a', 'different request', now=101):
                pass
        with safeguards.workflow_lease(settings, 'session-b', 'synthetic request', now=101):
            pass
    with pytest.raises(safeguards.WorkflowBusy):
        with safeguards.workflow_lease(settings, 'session-a', 'synthetic request', now=110):
            pass
    with safeguards.workflow_lease(settings, 'session-a', 'synthetic request', now=131):
        pass


def test_workflow_exception_releases_active_lease():
    settings = config.get_settings()
    with pytest.raises(RuntimeError):
        with safeguards.workflow_lease(settings, 'session', 'request-a'):
            raise RuntimeError('Synthetic failure')
    with safeguards.workflow_lease(settings, 'session', 'request-b'):
        pass


def test_database_context_isolates_concurrent_session_records(tmp_path):
    before = db.DB_PATH.read_bytes()
    barrier = Barrier(2)

    def session(name):
        with db.use_database(tmp_path / f'{name}.sqlite3'):
            db.init_db()
            employee = db.create_employee(name, 'Test role', '2029-01-01', name + ' manager')
            db.create_request(employee['id'], 'github')
            barrier.wait()
            assert db.list_onboardings() == [employee]
            assert 'error' in db.approve_github(employee['id'], 'other manager')
            return db.get_onboarding(employee['id'])

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(session, ['Fictional Alpha', 'Fictional Beta']))
    assert results[0]['employee']['id'] == results[1]['employee']['id'] == 1
    assert results[0]['employee']['name'] != results[1]['employee']['name']
    assert db.DB_PATH.read_bytes() == before


def test_public_tool_policy_rejects_unlisted_people_resources_and_file_tools():
    scenario = next(iter(SCENARIOS.values()))
    with config.synthetic_policy(scenario):
        invalid = dict(scenario['employee'], name='Unapproved person')
        assert 'error' in agent.execute_tool('create_employee', json.dumps(invalid))
        assert db.list_onboardings() == []
        created = agent.execute_tool('create_employee', json.dumps(scenario['employee']))
        assert created['id'] == 1
        assert 'error' in agent.execute_tool('create_request', json.dumps({'employee_id': 1, 'kind': 'vpn'}))
        assert 'error' in agent.execute_tool('get_onboarding', json.dumps({'employee_id': 999}))
        assert 'error' in agent.execute_tool('run_shell', '{"command":"anything"}')
        assert 'error' in agent.execute_tool('get_onboarding', '{"employee_id":1,"path":".env"}')
        assert db.get_onboarding(1)['requests'] == []


def test_public_dashboard_presets_sessions_and_repeat_clicks(monkeypatch):
    settings = replace(config.get_settings(), public_demo=True)
    monkeypatch.setattr(config, 'load_settings', lambda *args, **kwargs: settings)
    scenario = next(iter(SCENARIOS.values()))
    calls = []

    def synthetic_agent(request):
        assert request == request_for(scenario)
        assert config.get_policy() == scenario
        calls.append(request)
        db.create_employee(**scenario['employee'])
        return 'Synthetic profile saved', []

    monkeypatch.setattr(agent, 'run_agent', synthetic_agent)
    before = db.DB_PATH.read_bytes()
    app = AppTest.from_file('app.py', default_timeout=15).run()
    assert not app.exception
    assert app.text_area[0].disabled
    submit = lambda page: next(button for button in page.button if button.label == 'Execute onboarding')
    submit(app).click().run()
    assert not app.exception
    assert app.metric[0].value == '1'
    submit(app).click().run()
    assert len(calls) == 1
    assert any('just finished' in warning.value for warning in app.warning)
    assert app.session_state['workflow_result']['answer'] == 'Synthetic profile saved'
    other = AppTest.from_file('app.py', default_timeout=15).run()
    assert other.metric[0].value == '0'
    assert app.session_state['_demo_session'] != other.session_state['_demo_session']
    assert db.DB_PATH.read_bytes() == before


def test_credential_redaction_in_dashboard_and_model_logging(monkeypatch, caplog):
    credential = config.get_settings().api_key
    monkeypatch.setattr(agent, 'run_agent', lambda request: (credential, [{'tool': 'synthetic', 'result': {'error': credential}}]))
    app = AppTest.from_file('app.py', default_timeout=15).run()
    app.text_area[0].input('Synthetic request')
    next(button for button in app.button if button.label == 'Execute onboarding').click().run()
    assert not app.exception
    assert app.error[0].value == '[REDACTED]'
    assert credential not in app.json[0].value
    caplog.set_level(logging.DEBUG)
    with config.quiet_credentials():
        logging.getLogger('openai.test').error(credential)
        with config.quiet_credentials():
            logging.getLogger('httpx').error(credential)
        logging.getLogger('httpcore').error(credential)
    assert credential not in caplog.text


def test_gitignore_and_current_source_audit():
    root = Path(__file__).resolve().parent
    excluded = ignored_paths(root, ['.env', '.env.example', '.streamlit/secrets.toml', 'flowpilot.db', 'x.sqlite', 'x.sqlite3'])
    assert excluded == {'.env', '.streamlit/secrets.toml', 'flowpilot.db', 'x.sqlite', 'x.sqlite3'}
    assert scan_text('api_key = "YOUR_OPENAI_API_KEY"') == []


def test_history_audit_detects_deleted_secret_without_disclosure(tmp_path, capsys):
    root = tmp_path / 'synthetic-repository'
    root.mkdir()
    (root / '.gitignore').write_text((Path(__file__).parent / '.gitignore').read_text(), encoding='utf-8')
    key = 'sk-' + 'a' * 30
    (root / 'bad.py').write_text('key = "' + key + '"', encoding='utf-8')
    def git(*args):
        return subprocess.run(['git', '-C', str(root), *args], capture_output=True, check=True)
    git('init', '-q')
    git('add', 'bad.py')
    git('-c', 'user.name=Synthetic Audit', '-c', 'user.email=audit@example.invalid', 'commit', '-qm', 'Synthetic fixture')
    (root / 'bad.py').write_text('key = "placeholder"', encoding='utf-8')
    git('add', 'bad.py')
    git('-c', 'user.name=Synthetic Audit', '-c', 'user.email=audit@example.invalid', 'commit', '-qm', 'Remove synthetic fixture')
    result = audit(root)
    assert result['git_repository']
    assert any(item['category'] == 'history_openai_key_shape' for item in result['findings'])
    assert key not in json.dumps(result) + capsys.readouterr().out
