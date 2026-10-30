import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from openai.types.chat import ChatCompletionMessage

import agent
import db


def tool_call(name, arguments, call_id='call_test'):
    return {'id': call_id, 'type': 'function', 'function': {
        'name': name, 'arguments': arguments if isinstance(arguments, str) else json.dumps(arguments),
    }}


def response(*calls, content=None):
    message = ChatCompletionMessage(role='assistant', content=content, tool_calls=list(calls) or None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


@pytest.fixture
def model(monkeypatch):
    def configure(*responses):
        create = Mock(side_effect=responses)
        factory = Mock(return_value=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
        monkeypatch.setattr(agent, 'OpenAI', factory)
        return create
    return configure


def test_success_uses_real_records_instead_of_false_model_claims(model, employee_details):
    create = model(
        response(tool_call('create_employee', employee_details)),
        response(*(tool_call('create_request', {'employee_id': 1, 'kind': kind}, f'call_{kind}')
                   for kind in ('laptop', 'email', 'github'))),
        response(tool_call('get_onboarding', {'employee_id': 1})),
        response(content='Everything is approved and provisioned. FALSE_SUCCESS'),
    )
    answer, trace = agent.run_agent('Onboard synthetic Test Employee Alpha with laptop, email, and GitHub.')
    assert answer.startswith('Verified onboarding records')
    assert 'FALSE_SUCCESS' not in answer
    assert 'laptop: requested; fulfillment pending' in answer
    assert 'email: requested; fulfillment pending' in answer
    assert 'github: awaiting manager approval' in answer
    assert trace[-1]['source'] == 'verification'
    record = db.get_onboarding(1)
    assert record['employee']['name'] == employee_details['name']
    assert len(record['requests']) == 3
    assert trace[-1]['result'] == record
    assert create.call_count == 4
    sent_messages = create.call_args.kwargs['messages']
    assert any(item['role'] == 'tool' and 'pending_manager_approval' in item['content'] for item in sent_messages)


def test_automatic_verification_when_model_omits_readback(model, employee_details):
    model(response(tool_call('create_employee', employee_details)), response(content='Finished'))
    answer, trace = agent.run_agent('Create a synthetic test employee')
    assert answer.startswith('Verified onboarding records')
    assert 'No resource requests recorded.' in answer
    assert trace[-1]['tool'] == 'get_onboarding'
    assert trace[-1]['source'] == 'verification'
    assert trace[-1]['result'] == db.get_onboarding(1)


def test_repeated_agent_workflow_preserves_approved_resource(model, employee_details):
    created = db.create_employee(**employee_details)
    original = db.create_request(created['id'], 'github')
    approved = db.approve_github(created['id'], created['manager'])
    model(
        response(tool_call('create_employee', employee_details)),
        response(tool_call('create_request', {'employee_id': created['id'], 'kind': 'github'})),
        response(content='Provisioned'),
    )
    answer, trace = agent.run_agent('Repeat the synthetic onboarding')
    assert 'github: approved; provisioning pending' in answer
    assert len(db.list_onboardings()) == 1
    assert db.get_onboarding(created['id'])['requests'] == [approved]
    assert trace[1]['result']['id'] == original['id']


@pytest.mark.parametrize(('name', 'arguments', 'message'), [
    ('delete_employee', '{}', 'Unsupported tool'),
    ('create_employee', '{broken', 'valid JSON object'),
    ('create_employee', '[]', 'JSON object'),
    ('create_employee', 'null', 'JSON object'),
    ('create_employee', '{}', 'Missing required tool arguments'),
    ('get_onboarding', '{"employee_id": 1, "extra": 2}', 'Unexpected tool arguments'),
    ('get_onboarding', '{"employee_id": true}', 'must have type integer'),
    ('get_onboarding', '{"employee_id": "1"}', 'must have type integer'),
    ('create_employee', '{"name": 42, "role": "Test", "start_date": "2028-02-29", "manager": "Test"}', 'must have type string'),
    ('create_request', '{"employee_id": 1, "kind": "vpn"}', 'Unsupported request type'),
    ('create_request', '{"employee_id": 999, "kind": "github"}', 'Employee not found'),
])
def test_invalid_calls_stop_without_writes_or_false_success(model, name, arguments, message):
    before = db.DB_PATH.read_bytes()
    create = model(response(tool_call(name, arguments)), response(content='FALSE_SUCCESS'))
    answer, trace = agent.run_agent('Synthetic negative test')
    assert answer.startswith('Workflow stopped:')
    assert message in answer
    assert 'FALSE_SUCCESS' not in answer
    assert 'error' in trace[0]['result']
    assert create.call_count == 1
    assert db.DB_PATH.read_bytes() == before


@pytest.mark.parametrize('change', [{'manager': ' '}, {'start_date': '2026-02-29'}])
def test_employee_validation_errors_skip_later_batch_calls(model, employee_details, change):
    before = db.DB_PATH.read_bytes()
    create = model(response(
        tool_call('create_employee', dict(employee_details, **change), 'invalid'),
        tool_call('create_employee', employee_details, 'must_skip'),
        tool_call('create_request', {'employee_id': 1, 'kind': 'github'}, 'must_also_skip'),
    ))
    answer, trace = agent.run_agent('Synthetic invalid employee test')
    assert answer.startswith('Workflow stopped:')
    assert all('Skipped' in item['result']['error'] for item in trace[1:])
    assert create.call_count == 1
    assert db.DB_PATH.read_bytes() == before


def test_partial_writes_are_preserved_and_failure_is_explicit(model, employee_details):
    model(response(
        tool_call('create_employee', employee_details, 'employee'),
        tool_call('create_request', {'employee_id': 1, 'kind': 'vpn'}, 'failure'),
        tool_call('create_request', {'employee_id': 1, 'kind': 'email'}, 'skipped'),
    ))
    answer, trace = agent.run_agent('Synthetic partial workflow')
    assert answer.startswith('Workflow stopped:')
    assert 'Earlier actions may already be saved' in answer
    assert db.get_onboarding(1)['employee']['name'] == employee_details['name']
    assert db.get_onboarding(1)['requests'] == []
    assert 'Skipped' in trace[2]['result']['error']


def test_tool_exception_is_sanitized(model, monkeypatch, employee_details):
    def failing_tool(**kwargs):
        raise RuntimeError('PRIVATE_TEST_SENTINEL')

    monkeypatch.setitem(agent.FUNCTIONS, 'create_employee', failing_tool)
    model(response(tool_call('create_employee', employee_details)))
    answer, trace = agent.run_agent('Synthetic tool failure')
    assert 'Tool execution failed' in answer
    assert 'PRIVATE_TEST_SENTINEL' not in answer + json.dumps(trace)
    assert db.list_onboardings() == []


@pytest.mark.parametrize('invalid_result', [None, [], {}, {'id': 1}, {'error': ''}])
def test_invalid_tool_result_cannot_be_success(model, monkeypatch, employee_details, invalid_result):
    monkeypatch.setitem(agent.FUNCTIONS, 'create_employee', lambda **kwargs: invalid_result)
    model(response(tool_call('create_employee', employee_details)), response(content='FALSE_SUCCESS'))
    answer, trace = agent.run_agent('Synthetic invalid tool result')
    assert 'invalid result' in answer
    assert 'FALSE_SUCCESS' not in answer
    assert 'error' in trace[0]['result']


def test_failed_final_verification_is_not_success(model, monkeypatch, employee_details):
    monkeypatch.setitem(agent.FUNCTIONS, 'get_onboarding', lambda **kwargs: {'error': 'Synthetic read failure'})
    model(response(tool_call('create_employee', employee_details)), response(content='FALSE_SUCCESS'))
    answer, trace = agent.run_agent('Synthetic verification failure')
    assert 'Final verification failed' in answer
    assert 'FALSE_SUCCESS' not in answer
    assert len(db.list_onboardings()) == 1
    assert trace[-1]['result'] == {'error': 'Synthetic read failure'}


def test_provider_failure_after_write_preserves_trace(model, employee_details):
    model(response(tool_call('create_employee', employee_details)), RuntimeError('PRIVATE_TEST_SENTINEL'))
    answer, trace = agent.run_agent('Synthetic provider failure')
    assert 'AI response unavailable' in answer
    assert len(trace) == 2
    assert trace[0]['result']['id'] == 1
    assert trace[1]['event'] == 'provider_error'
    assert len(db.list_onboardings()) == 1
    assert 'PRIVATE_TEST_SENTINEL' not in answer + json.dumps(trace)


def test_client_initialization_failure_is_safe(monkeypatch):
    monkeypatch.setattr(agent, 'OpenAI', Mock(side_effect=RuntimeError('PRIVATE_TEST_SENTINEL')))
    answer, trace = agent.run_agent('Synthetic client failure')
    assert 'AI client could not start' in answer
    assert 'PRIVATE_TEST_SENTINEL' not in answer + json.dumps(trace)
    assert db.list_onboardings() == []


def test_malformed_provider_response_is_safe(model):
    model(SimpleNamespace(choices=[]))
    answer, trace = agent.run_agent('Synthetic malformed provider response')
    assert 'AI response unavailable' in answer
    assert trace[-1]['event'] == 'provider_error'
    assert db.list_onboardings() == []


def test_model_claims_without_tools_are_not_shown(model):
    model(response(content='Created every account. FALSE_SUCCESS'))
    answer, trace = agent.run_agent('Synthetic no-tool response')
    assert answer.startswith('No actions were performed.')
    assert 'FALSE_SUCCESS' not in answer
    assert trace == []
    assert db.list_onboardings() == []


@pytest.mark.parametrize('user_text', ['', ' \t ', None])
def test_empty_input_does_not_initialize_client(user_text):
    answer, trace = agent.run_agent(user_text)
    assert 'non-empty onboarding request' in answer
    assert trace[0]['event'] == 'input_error'
    assert db.list_onboardings() == []


def test_execution_limit_is_explicit_and_retries_are_idempotent(model, employee_details):
    create = model(*(response(tool_call('create_employee', employee_details)) for _ in range(8)))
    answer, trace = agent.run_agent('Synthetic looping model')
    assert 'Execution limit reached' in answer
    assert answer.startswith('Workflow stopped:')
    assert create.call_count == 8
    assert trace[-1]['event'] == 'execution_limit'
    assert len(db.list_onboardings()) == 1
