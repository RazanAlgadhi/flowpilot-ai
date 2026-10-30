import streamlit as st
import secrets
import re
from pathlib import Path

import db
import runtime_config as config
from demo_scenarios import SCENARIOS, request_for
from safeguards import workflow_lease, WorkflowBusy, SafeguardUnavailable
from db import init_db, list_onboardings, get_onboarding, approve_github
from agent import run_agent


RESOURCE_LABELS = {'laptop': 'Laptop', 'email': 'Email account', 'github': 'GitHub access'}
STATUS_DETAILS = {
    'requested': ('Requested', 'Request logged. Fulfillment is pending.', 'info'),
    'pending_manager_approval': (
        'Awaiting manager', 'Manager approval is required before provisioning.', 'warning'
    ),
    'approved_pending_provisioning': (
        'Approved · provisioning pending', 'Manager approval recorded. Access is not provisioned.', 'info'
    ),
}


def render_progress(record):
    """Track recorded milestones without treating approval as fulfillment."""
    requests = record['requests']
    github = next((item for item in requests if item['kind'] == 'github'), None)
    milestones = [('Employee profile created', True)]
    if requests:
        milestones.append(('Resource requests logged', True))
        if github:
            milestones.append((
                'Manager approval recorded',
                github['status'] == 'approved_pending_provisioning',
            ))
        # This simulator has no fulfillment action; approval is not completion.
        milestones.append(('Resources fulfilled', False))
    completed = sum(done for _, done in milestones)
    st.progress(completed / len(milestones), text=f'{completed} of {len(milestones)} milestones recorded')
    for label, done in milestones:
        st.write(f'{"✓" if done else "○"} {label}')
    if not requests:
        st.caption('Profile recorded. No resource requests to track yet.')
    else:
        st.caption('Progress covers requested resources only. This demo does not fulfill resources.')


def render_employee(record):
    employee = record['employee']
    requests = record['requests']
    details, progress = st.columns([3, 2], gap='large')
    with details, st.container(border=True):
        st.subheader(employee['name'])
        st.text(employee['role'])
        st.caption(f"Employee #{employee['id']}")
        start, manager = st.columns(2)
        start.caption('START DATE')
        start.text(employee['start_date'])
        manager.caption('ASSIGNED MANAGER')
        manager.text(employee['manager'])
    with progress, st.container(border=True):
        st.subheader('Onboarding progress')
        render_progress(record)

    st.subheader('Resource requests')
    if not requests:
        st.info('No resources requested. Submit a workflow with this employee’s name and start date to add resources.')
    else:
        columns = st.columns(3)
        for index, item in enumerate(requests):
            with columns[index % 3], st.container(border=True):
                st.subheader(RESOURCE_LABELS.get(item['kind'], item['kind']))
                label, description, level = STATUS_DETAILS.get(
                    item['status'], (item['status'].replace('_', ' ').capitalize(), 'Recorded request status.', 'info')
                )
                getattr(st, level)(label)
                st.write(description)
                st.caption(f"Request #{item['id']}")

    github = next((item for item in requests if item['kind'] == 'github'), None)
    if github and github['status'] == 'pending_manager_approval':
        with st.container(border=True):
            st.subheader('Manager approval')
            st.caption('Demo simulator only · Manager names are not authenticated. Approval does not provision access.')
            with st.form(f"approval_{employee['id']}"):
                approver = st.text_input('Assigned manager name', key=f"manager_{employee['id']}")
                if st.form_submit_button('Simulate manager approval'):
                    result = approve_github(employee['id'], approver)
                    if 'error' in result:
                        st.error(result['error'])
                    else:
                        st.session_state['approval_notice'] = 'GitHub request approved; provisioning is still pending.'
                        st.rerun()


def main():
    st.set_page_config(page_title='FlowPilot AI | Onboarding', page_icon='🧭', layout='wide')
    try:
        with config.quiet_credentials():
            settings = config.load_settings(st.secrets)
        if not re.fullmatch(r'[0-9a-f]{64}', str(st.session_state.get('_demo_session', ''))):
            st.session_state['_demo_session'] = secrets.token_hex(32)
        session_id = st.session_state['_demo_session']
        path = (settings.data_dir / 'sessions' / f'{session_id}.sqlite3' if settings.public_demo
                else Path(settings.private_db_path) if settings.private_db_path else db.DB_PATH)
        with config.use_settings(settings), db.use_database(path):
            render_dashboard(settings, session_id)
    except Exception:
        # Never render a configuration, database, or provider traceback to viewers.
        st.error('The demo is temporarily unavailable. Ask the owner to check server configuration and writable storage.')


def render_dashboard(settings, session_id):
    init_db()

    with st.sidebar:
        st.title('🧭 FlowPilot AI')
        st.caption('ONBOARDING OPERATIONS')
        st.divider()
        st.write('Coordinate employee setup, resource requests, and manager reviews in one workspace.')
        st.info('Simulation workspace')
        st.caption('HR, IT, and access systems are simulated. No accounts or equipment are provisioned.')
        st.caption('Temporary demo storage. Records may disappear on restart or redeploy.')
        if settings.public_demo:
            st.caption('Fictional records only. This browser session has its own workspace; it is not an authenticated account.')
        st.button('Refresh records', use_container_width=True)

    st.title('Employee onboarding')
    st.caption('Track every new hire, resource request, and approval from a single workspace.')
    notice = st.session_state.pop('approval_notice', None)
    if notice:
        st.success(notice)

    overview = st.container()

    with st.expander('Run an onboarding workflow', expanded=True):
        scenario = None
        if settings.public_demo:
            selected_scenario = st.selectbox('Synthetic demo scenario', list(SCENARIOS))
            scenario = SCENARIOS[selected_scenario]
            st.caption('Public mode accepts only these fictional scenarios. Do not enter real employee information.')
        st.caption('Include the employee’s name, role, start date, manager, and desired resources: laptop, email, or GitHub.')
        with st.form('onboarding_workflow'):
            request = st.text_area(
                'Onboarding request',
                placeholder='Onboard Sarah Ahmed as a Data Scientist starting 2026-11-09. Her manager is Omar. Request a laptop, email, and GitHub access.',
                height=110,
                value=request_for(scenario) if scenario else '',
                disabled=settings.public_demo,
            )
            submitted = st.form_submit_button('Execute onboarding', type='primary')
        if submitted:
            if scenario:
                # Ignore even a forged disabled text-area value; use server-owned data.
                request = request_for(scenario)
            if not request.strip():
                st.warning('Enter a request first.')
            else:
                with st.spinner('Executing and verifying workflow...'):
                    try:
                        with workflow_lease(settings, session_id, request), config.synthetic_policy(scenario):
                            st.session_state.pop('workflow_result', None)
                            answer, trace = run_agent(request)
                        st.session_state['workflow_result'] = config.redact({'answer': answer, 'trace': trace})
                    except (WorkflowBusy, SafeguardUnavailable) as exc:
                        st.warning(str(exc))
                    except Exception:
                        # Provider exceptions can include credentials or other sensitive data.
                        st.error('Workflow could not finish. Check your API configuration and connection, then retry. Review stored records below for any completed actions.')

    if 'workflow_result' in st.session_state:
        result = config.redact(st.session_state['workflow_result'])
        with st.container(border=True):
            st.markdown('**Latest workflow response**')
            if any('error' in item.get('result', {}) for item in result['trace']):
                st.error(result['answer'])
            else:
                st.write(result['answer'])
            with st.expander('Inspect tool execution trace', expanded=False):
                st.caption('Debug details from the latest execution in this session.')
                st.json(result['trace'])

    records = config.redact([get_onboarding(employee['id']) for employee in list_onboardings()])
    requests = [item for record in records for item in record['requests']]
    awaiting = sum(item['status'] == 'pending_manager_approval' for item in requests)
    pending = sum(item['status'] in ('requested', 'approved_pending_provisioning') for item in requests)
    with overview:
        for column, label, value in zip(
            st.columns(4),
            ('Employees', 'Resource requests', 'Awaiting approval', 'Pending fulfillment'),
            (len(records), len(requests), awaiting, pending),
        ):
            column.metric(label, value)
        st.caption('Pending fulfillment includes requested resources and approved access awaiting provisioning.')
    st.divider()

    st.subheader('Employee directory')
    if not records:
        st.info('Your workspace is ready. Submit an onboarding request above to create your first employee.')
        return

    search_column, filter_column = st.columns([3, 1])
    search = search_column.text_input('Search employees', placeholder='Name, role, or manager').strip().casefold()
    scope = filter_column.selectbox('Show', ['All employees', 'Awaiting approval', 'No resource requests'])
    visible = [
        record for record in records
        if (not search or any(search in record['employee'][field].casefold() for field in ('name', 'role', 'manager')))
        and (scope != 'Awaiting approval' or any(item['status'] == 'pending_manager_approval' for item in record['requests']))
        and (scope != 'No resource requests' or not record['requests'])
    ]
    if not visible:
        st.info('No employees match these filters. Try another search or choose All employees.')
        return

    st.dataframe([
        {
            'Employee ID': record['employee']['id'],
            'Employee': record['employee']['name'],
            'Role': record['employee']['role'],
            'Start date': record['employee']['start_date'],
            'Manager': record['employee']['manager'],
            'Requests': len(record['requests']),
            'Awaiting approval': sum(item['status'] == 'pending_manager_approval' for item in record['requests']),
        }
        for record in visible
    ], hide_index=True, use_container_width=True)

    by_id = {record['employee']['id']: record for record in visible}
    if st.session_state.get('selected_employee') not in by_id:
        st.session_state['selected_employee'] = next(iter(by_id))
    selected = st.selectbox(
        'View employee details', options=list(by_id), key='selected_employee',
        format_func=lambda employee_id: f"{by_id[employee_id]['employee']['name']} · #{employee_id}",
    )
    render_employee(by_id[selected])


if __name__ == '__main__':
    main()
