from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import agent
import db
import dotenv


@pytest.fixture
def dashboard(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'dashboard.db')
    monkeypatch.setattr(dotenv, 'load_dotenv', lambda: None)
    return AppTest.from_file(str(Path(__file__).with_name('app.py')), default_timeout=15)


def button(app, label):
    return next(item for item in app.button if item.label == label)


def test_workflow_approval_and_trace_survive_reruns(dashboard, monkeypatch):
    def simulated_agent(request):
        assert request == 'Create Sarah with laptop, email, and GitHub.'
        employee = db.create_employee('Sarah', 'Scientist', '2026-11-09', 'Omar')
        for kind in ('laptop', 'email', 'github'):
            db.create_request(employee['id'], kind)
        return 'Requests recorded; GitHub requires manager approval.', [
            {'tool': 'get_onboarding', 'result': db.get_onboarding(employee['id'])}
        ]

    monkeypatch.setattr(agent, 'run_agent', simulated_agent)
    app = dashboard.run()
    assert not app.exception
    assert [metric.value for metric in app.metric] == ['0', '0', '0', '0']
    app.text_area[0].input('Create Sarah with laptop, email, and GitHub.')
    button(app, 'Execute onboarding').click().run()
    assert not app.exception
    assert [metric.value for metric in app.metric] == ['1', '3', '1', '2']
    assert len(app.json) == 1  # Raw data is only present in the debug expander.
    trace = next(item for item in app.expander if item.label == 'Inspect tool execution trace')
    assert trace.proto.expanded is False
    assert app.get('progress')[0].proto.value == 50

    app.text_input(key='manager_1').input('Wrong manager')
    button(app, 'Simulate manager approval').click().run()
    assert 'assigned manager' in app.error[0].value
    assert db.get_onboarding(1)['requests'][2]['status'] == 'pending_manager_approval'

    app.text_input(key='manager_1').input(' Omar ')
    button(app, 'Simulate manager approval').click().run()
    assert not app.exception
    assert [metric.value for metric in app.metric] == ['1', '3', '0', '3']
    assert db.get_onboarding(1)['requests'][2]['status'] == 'approved_pending_provisioning'
    assert app.get('progress')[0].proto.value == 75
    assert any('provisioning is still pending' in item.value for item in app.success)
    assert len(app.json) == 1
    assert not any(item.label == 'Simulate manager approval' for item in app.button)


def test_directory_filters_and_employee_selection(dashboard):
    db.init_db()
    sarah = db.create_employee('Sarah', 'Scientist', '2026-11-09', 'Omar')
    db.create_request(sarah['id'], 'github')
    alex = db.create_employee('Alex', 'Engineer', '2026-11-10', 'Dana')
    app = dashboard.run()
    assert not app.exception
    assert app.selectbox(key='selected_employee').value == alex['id']
    app.selectbox[0].select('Awaiting approval').run()
    assert not app.exception
    assert app.selectbox(key='selected_employee').value == sarah['id']
    assert len(app.dataframe[0].value) == 1
    app.text_input[0].input('no match').run()
    assert not app.exception
    assert not app.dataframe
    assert any('No employees match' in item.value for item in app.info)
    app.text_input[0].input('').run()
    app.selectbox[0].select('No resource requests').run()
    assert not app.exception
    assert app.selectbox(key='selected_employee').value == alex['id']
    assert any('No resources requested' in item.value for item in app.info)


def test_blank_request_and_safe_provider_error(dashboard, monkeypatch):
    def failing_agent(request):
        raise RuntimeError('Sensitive provider detail: test-secret-value')

    monkeypatch.setattr(agent, 'run_agent', failing_agent)
    app = dashboard.run()
    button(app, 'Execute onboarding').click().run()
    assert app.warning[0].value == 'Enter a request first.'
    app.text_area[0].input('Create an employee')
    button(app, 'Execute onboarding').click().run()
    assert not app.exception
    assert 'Workflow could not finish' in app.error[0].value
    assert 'test-secret-value' not in app.error[0].value


def test_failed_tool_report_is_visible_and_trace_remains_collapsed(dashboard, monkeypatch):
    answer = 'Workflow stopped: Start date must be a valid calendar date in YYYY-MM-DD format'
    trace = [{'tool': 'create_employee', 'result': {'error': 'Invalid start date'}}]
    monkeypatch.setattr(agent, 'run_agent', lambda request: (answer, trace))
    app = dashboard.run()
    app.text_area[0].input('Synthetic invalid onboarding')
    button(app, 'Execute onboarding').click().run()
    assert not app.exception
    assert app.error[0].value == answer
    assert not app.success
    assert [metric.value for metric in app.metric] == ['0', '0', '0', '0']
    expander = next(item for item in app.expander if item.label == 'Inspect tool execution trace')
    assert expander.proto.expanded is False
    assert len(app.json) == 1
    button(app, 'Refresh records').click().run()
    assert not app.exception
    assert app.error[0].value == answer
    assert len(app.json) == 1
