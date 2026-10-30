"""All tests use synthetic records, isolated SQLite files, and no live API calls."""
import pytest

import agent
import db
import dotenv
import runtime_config


@pytest.fixture(autouse=True)
def isolated_services(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'isolated.db')
    monkeypatch.setattr(dotenv, 'load_dotenv', lambda: None)

    def no_live_client(*args, **kwargs):
        pytest.fail('Tests must explicitly mock OpenAI; live API calls are forbidden')

    monkeypatch.setattr(agent, 'OpenAI', no_live_client)
    db.init_db()
    settings = runtime_config.Settings(api_key='synthetic-test-key', public_demo=False,
                                       daily_api_quota=10000, data_dir=tmp_path / 'runtime')
    monkeypatch.setattr(runtime_config, 'load_settings', lambda *args, **kwargs: settings)
    with runtime_config.use_settings(settings):
        yield


@pytest.fixture
def employee_details():
    return {'name': 'Test Employee Alpha', 'role': 'Test Engineer',
            'start_date': '2028-02-29', 'manager': 'Test Manager Alpha'}


@pytest.fixture
def employee(employee_details):
    return db.create_employee(**employee_details)
