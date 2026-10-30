"""Server-owned configuration and secret-safe operations; no Streamlit dependency."""
import logging
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path

import dotenv

ROOT = Path(__file__).resolve().parent
_settings = ContextVar('flowpilot_settings', default=None)
_policy = ContextVar('flowpilot_synthetic_policy', default=None)
_log_lock = threading.RLock()
_quiet_count = 0
_previous_disable = 0


@contextmanager
def quiet_credentials():
    """Keep logging disabled until all overlapping credential operations finish."""
    global _quiet_count, _previous_disable
    with _log_lock:
        if _quiet_count == 0:
            _previous_disable = logging.root.manager.disable
            logging.disable(logging.CRITICAL)
        _quiet_count += 1
    try:
        yield
    finally:
        with _log_lock:
            _quiet_count -= 1
            if _quiet_count == 0:
                logging.disable(_previous_disable)


@dataclass(frozen=True)
class Settings:
    api_key: str = field(default='', repr=False)
    model: str = 'gpt-4.1-mini'
    public_demo: bool = True
    max_model_calls: int = 8
    max_output_tokens: int = 1024
    daily_api_quota: int = 100
    data_dir: Path = field(default_factory=lambda: Path(tempfile.gettempdir()) / 'flowpilot')
    private_db_path: str = ''


def load_settings(secrets=None, *, local_env=True):
    """Environment > Streamlit root secrets > local .env; values are never logged."""
    with quiet_credentials():
        local = dotenv.dotenv_values(ROOT / '.env', interpolate=False, verbose=False) if local_env else {}

    def value(name, default):
        if name in os.environ:
            return os.environ[name]
        if secrets is not None:
            try:
                found = secrets.get(name)
                if found is not None:
                    return found
            except FileNotFoundError:
                pass
        return local.get(name) if local.get(name) is not None else default

    def integer(name, default, low, high):
        raw = value(name, default)
        if isinstance(raw, bool):
            raise ValueError('Invalid numeric server configuration')
        try:
            parsed = int(raw)
        except (TypeError, ValueError):
            raise ValueError('Invalid numeric server configuration') from None
        if not low <= parsed <= high:
            raise ValueError('Server limit is outside its permitted range')
        return parsed

    public = str(value('FLOWPILOT_PUBLIC_DEMO', 'true')).lower()
    if public not in ('true', 'false'):
        raise ValueError('Public demo setting must be true or false')
    return Settings(
        api_key=str(value('OPENAI_API_KEY', '')), model=str(value('OPENAI_MODEL', 'gpt-4.1-mini')),
        public_demo=public == 'true',
        max_model_calls=integer('FLOWPILOT_MAX_MODEL_CALLS', 8, 1, 16),
        max_output_tokens=integer('FLOWPILOT_MAX_OUTPUT_TOKENS', 1024, 1, 4096),
        daily_api_quota=integer('FLOWPILOT_DAILY_API_QUOTA', 100, 0, 100000),
        data_dir=Path(str(value('FLOWPILOT_DATA_DIR', Path(tempfile.gettempdir()) / 'flowpilot'))).expanduser(),
        private_db_path=str(value('FLOWPILOT_DB_PATH', '')),
    )


def get_settings():
    return _settings.get() or load_settings(local_env=False)


@contextmanager
def use_settings(settings):
    token = _settings.set(settings)
    try:
        yield
    finally:
        _settings.reset(token)


@contextmanager
def synthetic_policy(policy):
    token = _policy.set(policy)
    try:
        yield
    finally:
        _policy.reset(token)


def get_policy():
    return _policy.get()


def redact(value):
    credentials = [get_settings().api_key, os.getenv('OPENAI_API_KEY', ''), os.getenv('OPENAI_ADMIN_KEY', '')]
    if isinstance(value, str):
        for credential in credentials:
            if credential:
                value = value.replace(credential, '[REDACTED]')
        return re.sub(r'\b(?:sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{36,})', '[REDACTED]', value)
    if isinstance(value, dict):
        return {redact(key): redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    return value
