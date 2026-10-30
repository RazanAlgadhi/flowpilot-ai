import db
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

def test_idempotent_workflow(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'test.db')
    db.init_db()
    a = db.create_employee('Sarah','Scientist','2026-11-09','Omar')
    b = db.create_employee('Sarah','Scientist','2026-11-09','Omar')
    assert a['id'] == b['id']
    first = db.create_request(a['id'],'github')
    second = db.create_request(a['id'],'github')
    assert first['id'] == second['id']
    assert first['status'] == 'pending_manager_approval'
    assert 'error' in db.approve_github(a['id'],'Someone Else')
    approved = db.approve_github(a['id'],'Omar')
    assert approved['status'] == 'approved_pending_provisioning'
    assert len(db.get_onboarding(a['id'])['requests']) == 1


def test_database_rejects_direct_duplicate_employee(employee):
    with closing(db.connect()) as con, con:
        with pytest.raises(sqlite3.IntegrityError, match='UNIQUE'):
            con.execute('INSERT INTO employees(name, role, start_date, manager) VALUES (?, ?, ?, ?)',
                        tuple(employee[key] for key in ('name', 'role', 'start_date', 'manager')))
    assert db.list_onboardings() == [employee]


def test_database_rejects_direct_duplicate_request(employee):
    original = db.create_request(employee['id'], 'github')
    with closing(db.connect()) as con, con:
        with pytest.raises(sqlite3.IntegrityError, match='UNIQUE'):
            con.execute('INSERT INTO requests(employee_id, kind, status) VALUES (?, ?, ?)',
                        (employee['id'], 'github', 'requested'))
    assert db.get_onboarding(employee['id'])['requests'] == [original]


def test_database_enforces_foreign_key():
    with closing(db.connect()) as con, con:
        with pytest.raises(sqlite3.IntegrityError, match='FOREIGN KEY'):
            con.execute("INSERT INTO requests(employee_id, kind, status) VALUES (999, 'email', 'requested')")


def test_employee_retry_trims_whitespace_and_preserves_existing_profile(employee, employee_details):
    retry = dict(employee_details, name='  Test Employee Alpha  ', role='Changed role', manager='Changed manager')
    assert db.create_employee(**retry) == employee
    assert db.list_onboardings() == [employee]


def test_same_name_with_different_start_date_is_distinct(employee, employee_details):
    other = db.create_employee(**dict(employee_details, start_date='2028-03-01'))
    assert other['id'] != employee['id']
    assert len(db.list_onboardings()) == 2


@pytest.mark.parametrize('field', ['name', 'role', 'start_date', 'manager'])
@pytest.mark.parametrize('value', [None, '', ' \t ', 42])
def test_missing_or_non_text_details_do_not_write(employee_details, field, value):
    before = db.DB_PATH.read_bytes()
    result = db.create_employee(**dict(employee_details, **{field: value}))
    assert field in result['error']
    assert db.DB_PATH.read_bytes() == before
    assert db.list_onboardings() == []


@pytest.mark.parametrize('field', ['name', 'role', 'start_date', 'manager'])
def test_omitted_employee_details(employee_details, field):
    del employee_details[field]
    assert field in db.create_employee(**employee_details)['error']
    assert db.list_onboardings() == []


@pytest.mark.parametrize('start_date', [
    '2026-02-29', '2028-02-30', '2028-13-01', '0000-01-01',
    '2028-2-09', '29/02/2028', '20280229', '2028-W09-2', '2028-02-29T00:00:00',
])
def test_invalid_start_dates_do_not_write(employee_details, start_date):
    before = db.DB_PATH.read_bytes()
    assert 'YYYY-MM-DD' in db.create_employee(**dict(employee_details, start_date=start_date))['error']
    assert db.DB_PATH.read_bytes() == before


@pytest.mark.parametrize('start_date', ['2028-02-29', '2000-01-01'])
def test_valid_dates_including_leap_day_and_past_dates(employee_details, start_date):
    result = db.create_employee(**dict(employee_details, start_date=' ' + start_date + ' '))
    assert result['start_date'] == start_date
    assert db.get_onboarding(result['id'])['employee'] == result


@pytest.mark.parametrize('kind', ['laptop', 'email', 'github'])
def test_each_resource_request_is_idempotent(employee, kind):
    first = db.create_request(employee['id'], kind)
    assert db.create_request(employee['id'], kind) == first
    expected = 'pending_manager_approval' if kind == 'github' else 'requested'
    assert first['status'] == expected
    assert db.get_onboarding(employee['id'])['requests'] == [first]


@pytest.mark.parametrize('kind', ['vpn', '', None, ['github']])
def test_unsupported_resource_does_not_write(employee, kind):
    before = db.DB_PATH.read_bytes()
    assert 'error' in db.create_request(employee['id'], kind)
    assert db.DB_PATH.read_bytes() == before


@pytest.mark.parametrize('employee_id', [0, -1, True, '1', None, 1.5, 999])
def test_invalid_or_unknown_employee_cannot_be_used(employee_id):
    before = db.DB_PATH.read_bytes()
    assert 'error' in db.create_request(employee_id, 'github')
    assert 'error' in db.get_onboarding(employee_id)
    assert 'error' in db.approve_github(employee_id, 'Test Manager Alpha')
    assert db.DB_PATH.read_bytes() == before


@pytest.mark.parametrize('approver', ['Wrong Test Manager', '', '  ', None, 123])
@pytest.mark.parametrize('already_approved', [False, True])
def test_incorrect_approval_leaves_entire_database_unchanged(employee, approver, already_approved):
    db.create_request(employee['id'], 'github')
    db.create_request(employee['id'], 'email')
    if already_approved:
        db.approve_github(employee['id'], employee['manager'])
    before = db.DB_PATH.read_bytes()
    assert 'error' in db.approve_github(employee['id'], approver)
    assert db.DB_PATH.read_bytes() == before


def test_approval_without_github_does_not_write(employee):
    db.create_request(employee['id'], 'laptop')
    before = db.DB_PATH.read_bytes()
    assert db.approve_github(employee['id'], employee['manager']) == {'error': 'No GitHub request exists'}
    assert db.DB_PATH.read_bytes() == before


def test_approval_only_changes_target_and_retries_preserve_status(employee, employee_details):
    other = db.create_employee(**dict(employee_details, name='Test Employee Beta'))
    other_request = db.create_request(other['id'], 'github')
    email = db.create_request(employee['id'], 'email')
    github = db.create_request(employee['id'], 'github')
    approved = db.approve_github(employee['id'], '  TEST MANAGER ALPHA  ')
    assert approved == dict(github, status='approved_pending_provisioning')
    assert db.approve_github(employee['id'], employee['manager']) == approved
    assert db.create_request(employee['id'], 'github') == approved
    assert db.get_onboarding(employee['id'])['requests'] == [email, approved]
    assert db.get_onboarding(other['id'])['requests'] == [other_request]


def test_concurrent_duplicate_workflows_use_one_employee_and_request(employee_details):
    def create_workflow(_):
        created = db.create_employee(**employee_details)
        return created, db.create_request(created['id'], 'github')

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(create_workflow, range(12)))
    assert all(result == results[0] for result in results)
    assert db.list_onboardings() == [results[0][0]]
    assert db.get_onboarding(results[0][0]['id'])['requests'] == [results[0][1]]


def test_unrelated_integrity_failure_is_not_silently_ignored(employee_details):
    with closing(db.connect()) as con, con:
        con.execute("""CREATE TRIGGER reject_test_employee BEFORE INSERT ON employees
                       BEGIN SELECT RAISE(ABORT, 'synthetic constraint failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match='synthetic constraint failure'):
        db.create_employee(**employee_details)
    assert db.list_onboardings() == []


def test_database_helpers_close_connections(employee_details, monkeypatch):
    original = db.connect
    connections = []

    def tracked_connect():
        con = original()
        connections.append(con)
        return con

    monkeypatch.setattr(db, 'connect', tracked_connect)
    db.init_db()
    created = db.create_employee(**employee_details)
    db.create_request(created['id'], 'github')
    db.get_onboarding(created['id'])
    db.list_onboardings()
    db.approve_github(created['id'], 'Wrong manager')
    db.approve_github(created['id'], created['manager'])
    for con in connections:
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            con.execute('SELECT 1')
