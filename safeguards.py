"""Atomic server-side quotas and workflow leases on one shared local filesystem."""
import hashlib
import secrets
import sqlite3
import time
from contextlib import closing, contextmanager
from datetime import datetime, timezone


class QuotaExceeded(RuntimeError):
    pass


class SafeguardUnavailable(RuntimeError):
    pass


class WorkflowBusy(RuntimeError):
    pass


def connect_control(settings):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(settings.data_dir / 'control.sqlite3', timeout=5)
    try:
        con.executescript('''
            CREATE TABLE IF NOT EXISTS daily_requests(day TEXT PRIMARY KEY, count INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS workflow_leases(
                session_id TEXT PRIMARY KEY, token TEXT, expires REAL NOT NULL,
                request_hash TEXT NOT NULL, finished REAL NOT NULL DEFAULT 0
            );
        ''')
    except Exception:
        con.close()
        raise
    return con


def reserve_api_request(settings, now=None):
    """Reserve before sending. Failures consume quota; a UTC day defines reset."""
    day = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date().isoformat()
    try:
        with closing(connect_control(settings)) as con, con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT count FROM daily_requests WHERE day=?', (day,)).fetchone()
            used = row[0] if row else 0
            if used >= settings.daily_api_quota:
                raise QuotaExceeded('Daily demo API quota reached. Try again after 00:00 UTC or contact the demo owner.')
            con.execute('''INSERT INTO daily_requests(day,count) VALUES (?,1)
                           ON CONFLICT(day) DO UPDATE SET count=count+1''', (day,))
            return used + 1
    except (sqlite3.Error, OSError):
        raise SafeguardUnavailable('API quota storage is unavailable; no model request was sent.') from None


@contextmanager
def workflow_lease(settings, session_id, request, now=None):
    """Reject overlapping workflows and rapid identical resubmissions server-side."""
    timestamp = time.time() if now is None else now
    digest = hashlib.sha256(request.strip().encode('utf-8')).hexdigest()
    token = secrets.token_hex(16)
    try:
        with closing(connect_control(settings)) as con, con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT token,expires,request_hash,finished FROM workflow_leases WHERE session_id=?', (session_id,)).fetchone()
            if row and row[0] and row[1] > timestamp:
                raise WorkflowBusy('An onboarding is already running in this session. Wait for it to finish.')
            if row and row[2] == digest and row[3] and timestamp - row[3] < 30:
                raise WorkflowBusy('This request just finished. Review the result before retrying in 30 seconds.')
            con.execute('''INSERT INTO workflow_leases(session_id,token,expires,request_hash,finished)
                           VALUES (?,?,?,?,0) ON CONFLICT(session_id) DO UPDATE SET
                           token=excluded.token, expires=excluded.expires, request_hash=excluded.request_hash, finished=0''',
                        (session_id, token, timestamp + settings.max_model_calls * 120 + 120, digest))
    except (sqlite3.Error, OSError):
        raise SafeguardUnavailable('Workflow lock storage is unavailable; no workflow was started.') from None
    try:
        yield
    finally:
        try:
            with closing(connect_control(settings)) as con, con:
                con.execute('UPDATE workflow_leases SET token=NULL, expires=0, finished=? WHERE session_id=? AND token=?',
                            (time.time() if now is None else now, session_id, token))
        except (sqlite3.Error, OSError):
            # Fail closed: the existing lease remains until expiration.
            pass
