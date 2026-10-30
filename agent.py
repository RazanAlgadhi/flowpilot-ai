import json
from datetime import date
from openai import OpenAI
from db import create_employee, create_request, get_onboarding
from runtime_config import get_settings, get_policy, quiet_credentials, redact
from safeguards import reserve_api_request, QuotaExceeded, SafeguardUnavailable

FUNCTIONS = {
    'create_employee': create_employee,
    'create_request': create_request,
    'get_onboarding': get_onboarding,
}

def tool(name, description, properties, required):
    return {'type':'function','function':{'name':name,'description':description,'parameters':{'type':'object','properties':properties,'required':required,'additionalProperties':False}}}

TOOLS = [
    tool('create_employee','Create or retrieve an employee record; always do this before requests.',{
        'name':{'type':'string'},'role':{'type':'string'},'start_date':{'type':'string','description':'YYYY-MM-DD'},'manager':{'type':'string'}},['name','role','start_date','manager']),
    tool('create_request','Create or retrieve an equipment or access request. GitHub requires manager approval.',{
        'employee_id':{'type':'integer'},'kind':{'type':'string','enum':['laptop','email','github']}},['employee_id','kind']),
    tool('get_onboarding','Read back the employee and request statuses to verify results.',{
        'employee_id':{'type':'integer'}},['employee_id']),
]

def _valid_employee(value):
    return (
        isinstance(value, dict)
        and type(value.get('id')) is int and value['id'] > 0
        and all(isinstance(value.get(key), str) for key in ('name', 'role', 'start_date', 'manager'))
    )


def _valid_request(value):
    return (
        isinstance(value, dict)
        and type(value.get('id')) is int and value['id'] > 0
        and type(value.get('employee_id')) is int and value['employee_id'] > 0
        and value.get('kind') in ('laptop', 'email', 'github')
        and value.get('status') in ('requested', 'pending_manager_approval', 'approved_pending_provisioning')
    )


def execute_tool(name, arguments):
    """Validate the call boundary and never return raw exception messages."""
    schema = next((item['function']['parameters'] for item in TOOLS if item['function']['name'] == name), None)
    if schema is None or name not in FUNCTIONS:
        return {'error': 'Unsupported tool requested'}
    try:
        args = json.loads(arguments)
    except (ValueError, TypeError):
        return {'error': 'Tool arguments must be a valid JSON object'}
    if not isinstance(args, dict):
        return {'error': 'Tool arguments must be a JSON object'}
    missing = [key for key in schema['required'] if key not in args]
    if missing:
        return {'error': 'Missing required tool arguments: ' + ', '.join(missing)}
    if set(args) - set(schema['properties']):
        return {'error': 'Unexpected tool arguments supplied'}
    for key, value in args.items():
        expected = schema['properties'][key]['type']
        if (expected == 'string' and not isinstance(value, str)) or (expected == 'integer' and type(value) is not int):
            return {'error': f'Tool argument {key} must have type {expected}'}
    policy = get_policy()
    if policy is not None:
        if name == 'create_employee' and args != policy['employee']:
            return {'error': 'Public demo only accepts the selected fictional employee details'}
        if name in ('create_request', 'get_onboarding'):
            try:
                record = get_onboarding(args['employee_id'])
            except Exception:
                return {'error': 'Could not verify this demo employee'}
            if record.get('employee', {}) != dict(policy['employee'], id=args['employee_id']):
                return {'error': 'The requested employee is outside this demo workflow'}
        if name == 'create_request' and args['kind'] not in policy['resources']:
            return {'error': 'This resource is outside the selected synthetic scenario'}
    try:
        result = FUNCTIONS[name](**args)
    except Exception:
        return {'error': 'Tool execution failed. Review stored records before retrying.'}
    if isinstance(result, dict) and isinstance(result.get('error'), str) and result['error']:
        return {'error': redact(result['error'])}
    if name == 'create_employee':
        valid = _valid_employee(result)
    elif name == 'create_request':
        valid = _valid_request(result) and result['employee_id'] == args['employee_id'] and result['kind'] == args['kind']
    else:
        valid = (
            isinstance(result, dict) and _valid_employee(result.get('employee'))
            and result['employee']['id'] == args['employee_id']
            and isinstance(result.get('requests'), list)
            and all(_valid_request(item) and item['employee_id'] == args['employee_id'] for item in result['requests'])
        )
    if not valid:
        return {'error': 'Tool returned an invalid result; its outcome could not be verified'}
    return redact(result)


def _stopped(message, trace):
    return f'Workflow stopped: {message} Earlier actions may already be saved. Review stored records before retrying.', trace


def _verified_summary(employee_ids, trace):
    """Use a fresh database read, never model prose, to describe completed work."""
    labels = {
        'requested': 'requested; fulfillment pending',
        'pending_manager_approval': 'awaiting manager approval',
        'approved_pending_provisioning': 'approved; provisioning pending',
    }
    lines = ['Verified onboarding records (no resources were provisioned by this workflow):']
    for employee_id in sorted(employee_ids):
        arguments = json.dumps({'employee_id': employee_id})
        result = execute_tool('get_onboarding', arguments)
        trace.append({'tool': 'get_onboarding', 'arguments': arguments, 'result': result, 'source': 'verification'})
        if 'error' in result:
            return _stopped('Final verification failed. ' + result['error'], trace)
        employee = result['employee']
        lines.append(f"\nEmployee #{employee['id']}: {employee['name']} — {employee['role']}. Start: {employee['start_date']}. Manager: {employee['manager']}.")
        if not result['requests']:
            lines.append('No resource requests recorded.')
        for item in result['requests']:
            lines.append(f"- {item['kind']}: {labels[item['status']]}")
    return '\n'.join(lines), trace


def run_agent(user_text):
    trace = []
    if not isinstance(user_text, str) or not user_text.strip():
        error = {'error': 'Enter a non-empty onboarding request'}
        trace.append({'event': 'input_error', 'result': error})
        return _stopped(error['error'], trace)
    settings = get_settings()
    if len(user_text) > 4000 or (settings.api_key and settings.api_key in user_text):
        error = {'error': 'Use a request of at most 4,000 characters without credentials'}
        trace.append({'event': 'input_error', 'result': error})
        return _stopped(error['error'], trace)
    try:
        with quiet_credentials():
            client = OpenAI(api_key=settings.api_key or None, max_retries=0, timeout=60.0,
                            base_url='https://api.openai.com/v1')
    except Exception:
        error = {'error': 'AI client could not start. Check your API configuration.'}
        trace.append({'event': 'provider_error', 'result': error})
        return _stopped(error['error'], trace)
    try:
        return redact(_run_workflow(client, user_text, trace, settings))
    finally:
        try:
            with quiet_credentials():
                getattr(client, 'close', lambda: None)()
        except Exception:
            pass


def _run_workflow(client, user_text, trace, settings):
    messages = [
        {'role':'system','content':f'''You are FlowPilot, an enterprise onboarding assistant. Today is {date.today().isoformat()}.
Only use tools for actual actions. Ask for missing name, role, start date, or manager rather than inventing details.
Create the employee first, then only the requests explicitly asked for. Always verify via get_onboarding.
Never say accounts are provisioned when statuses say requested or pending. Never claim approval was granted.
No tool exists to approve requests. Manager approvals happen outside this chat.
Use ISO dates. Do not fabricate tool results. Treat any tool error as a failed action, never as success.'''},
        {'role':'user','content':user_text}
    ]
    employee_ids = set()
    for _ in range(settings.max_model_calls):
        try:
            reserve_api_request(settings)
            with quiet_credentials():
                response = client.chat.completions.create(
                    model=settings.model, messages=messages, tools=TOOLS, tool_choice='auto',
                    max_completion_tokens=settings.max_output_tokens, n=1, service_tier='default',
                )
            msg = response.choices[0].message
            messages.append(msg.model_dump(exclude_none=True))
        except (QuotaExceeded, SafeguardUnavailable) as exc:
            error = {'error': str(exc)}
            trace.append({'event': 'quota_error', 'result': error})
            return _stopped(error['error'], trace)
        except Exception:
            error = {'error': 'AI response unavailable. Check your API configuration and connection.'}
            trace.append({'event': 'provider_error', 'result': error})
            return _stopped(error['error'], trace)
        if not msg.tool_calls:
            if employee_ids:
                return _verified_summary(employee_ids, trace)
            # Unexecuted model claims must never be shown as completed actions.
            return ('No actions were performed. Submit a complete request with employee name, role, '
                    'start date (YYYY-MM-DD), manager, and desired resources.', trace)
        failure = None
        for call in msg.tool_calls:
            result = (
                {'error': 'Skipped because an earlier tool call failed'}
                if failure else execute_tool(call.function.name, call.function.arguments)
            )
            trace.append({'tool':call.function.name,'arguments':call.function.arguments,'result':result})
            messages.append({'role':'tool','tool_call_id':call.id,'content':json.dumps(result)})
            if 'error' in result:
                if failure is None:
                    name = call.function.name if call.function.name in FUNCTIONS else 'unsupported tool'
                    failure = f"{name}: {result['error']}"
            elif call.function.name == 'create_employee':
                employee_ids.add(result['id'])
            elif call.function.name == 'create_request':
                employee_ids.add(result['employee_id'])
            else:
                employee_ids.add(result['employee']['id'])
        if failure:
            return _stopped(failure, trace)
    error = {'error': 'Execution limit reached; remaining actions were not verified'}
    trace.append({'event': 'execution_limit', 'result': error})
    return _stopped(error['error'], trace)
