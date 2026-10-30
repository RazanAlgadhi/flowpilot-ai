"""Start Streamlit locally, verify its health endpoint, then stop it. No workflows."""
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fingerprint():
    path = ROOT / 'flowpilot.db'
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def main():
    before = fingerprint()
    healthy = False
    with tempfile.TemporaryDirectory(prefix='flowpilot-startup-') as directory:
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        environment = dict(os.environ, FLOWPILOT_PUBLIC_DEMO='true', FLOWPILOT_DAILY_API_QUOTA='0', FLOWPILOT_DATA_DIR=directory)
        environment.pop('OPENAI_API_KEY', None)
        process = subprocess.Popen(
            [sys.executable, '-m', 'streamlit', 'run', 'app.py', '--server.address', '127.0.0.1',
             '--server.port', str(port), '--server.headless', 'true'],
            cwd=ROOT, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
        )
        try:
            deadline = time.monotonic() + 25
            while process.poll() is None and time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}/_stcore/health', timeout=1) as response:
                        healthy = response.status == 200 and response.read() == b'ok'
                    if healthy:
                        break
                except OSError:
                    time.sleep(0.1)
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    unchanged = fingerprint() == before
    print(json.dumps({'streamlit_startup_healthy': healthy, 'demo_database_unchanged': unchanged,
                      'workflows_submitted': 0, 'daily_api_quota_during_smoke': 0}))
    return 0 if healthy and unchanged else 1


if __name__ == '__main__':
    raise SystemExit(main())
