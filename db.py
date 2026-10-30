import sqlite3
from contextlib import closing, contextmanager
from contextvars import ContextVar
from datetime import date
from pathlib import Path

DB_PATH = Path(__file__).with_name('flowpilot.db')
_database_path = ContextVar('flowpilot_database_path', default=None)


@contextmanager
def use_database(path):
    """Scope a database to this Streamlit execution thread, never a global patch."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    token = _database_path.set(path)
    try:
        yield
    finally:
        _database_path.reset(token)

def connect():
    con = sqlite3.connect(_database_path.get() or DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    return con

def init_db():
    with closing(connect()) as con, con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, role TEXT NOT NULL,
            start_date TEXT NOT NULL, manager TEXT NOT NULL,
            UNIQUE(name, start_date)
        );
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL REFERENCES employees(id),
            kind TEXT NOT NULL, status TEXT NOT NULL,
            UNIQUE(employee_id, kind)
        );
        ''')

def valid_employee_id(employee_id):
    return type(employee_id) is int and employee_id > 0


def create_employee(name=None, role=None, start_date=None, manager=None):
    fields = {'name': name, 'role': role, 'start_date': start_date, 'manager': manager}
    missing = [key for key, value in fields.items() if not isinstance(value, str) or not value.strip()]
    if missing:
        return {'error': 'Employee details must be non-empty text: ' + ', '.join(missing)}
    name, role, start_date, manager = (value.strip() for value in fields.values())
    try:
        parsed_date = date.fromisoformat(start_date)
    except ValueError:
        return {'error': 'Start date must be a valid calendar date in YYYY-MM-DD format'}
    if parsed_date.isoformat() != start_date:
        return {'error': 'Start date must be a valid calendar date in YYYY-MM-DD format'}
    with closing(connect()) as con, con:
        # Only the known identity conflict is ignored; other integrity errors surface.
        con.execute('''INSERT INTO employees(name,role,start_date,manager) VALUES (?,?,?,?)
                       ON CONFLICT(name, start_date) DO NOTHING''', (name,role,start_date,manager))
        row = con.execute('SELECT * FROM employees WHERE name=? AND start_date=?',(name,start_date)).fetchone()
        return dict(row)

def create_request(employee_id, kind):
    if not valid_employee_id(employee_id):
        return {'error': 'Employee ID must be a positive integer'}
    if kind not in ('laptop','email','github'):
        return {'error':'Unsupported request type'}
    with closing(connect()) as con, con:
        employee = con.execute('SELECT id FROM employees WHERE id=?',(employee_id,)).fetchone()
        if employee is None:
            return {'error':'Employee not found'}
        status = 'pending_manager_approval' if kind == 'github' else 'requested'
        con.execute('''INSERT INTO requests(employee_id,kind,status) VALUES (?,?,?)
                       ON CONFLICT(employee_id, kind) DO NOTHING''',(employee_id,kind,status))
        row = con.execute('SELECT * FROM requests WHERE employee_id=? AND kind=?',(employee_id,kind)).fetchone()
        return dict(row)

def get_onboarding(employee_id):
    if not valid_employee_id(employee_id):
        return {'error': 'Employee ID must be a positive integer'}
    with closing(connect()) as con, con:
        employee = con.execute('SELECT * FROM employees WHERE id=?',(employee_id,)).fetchone()
        if employee is None:
            return {'error':'Employee not found'}
        requests = con.execute('SELECT * FROM requests WHERE employee_id=? ORDER BY id',(employee_id,)).fetchall()
        return {'employee':dict(employee),'requests':[dict(x) for x in requests]}

def list_onboardings():
    with closing(connect()) as con, con:
        return [dict(x) for x in con.execute('SELECT * FROM employees ORDER BY id DESC').fetchall()]

def approve_github(employee_id, approver):
    if not valid_employee_id(employee_id):
        return {'error': 'Employee ID must be a positive integer'}
    if not isinstance(approver, str) or not approver.strip():
        return {'error': 'Approval must be provided by the assigned manager'}
    with closing(connect()) as con, con:
        employee = con.execute('SELECT manager FROM employees WHERE id=?',(employee_id,)).fetchone()
        if employee is None or employee['manager'].strip().casefold() != approver.strip().casefold():
            return {'error':'Approval must be provided by the assigned manager'}
        row = con.execute("SELECT * FROM requests WHERE employee_id=? AND kind='github'",(employee_id,)).fetchone()
        if row is None:
            return {'error':'No GitHub request exists'}
        con.execute("UPDATE requests SET status='approved_pending_provisioning' WHERE id=? AND status='pending_manager_approval'",(row['id'],))
        return dict(con.execute('SELECT * FROM requests WHERE id=?',(row['id'],)).fetchone())
