"""Offline review of committed sanitized evidence; no original private files needed."""
import json
import shutil
import subprocess
from unittest.mock import Mock

import pytest

import agent
import db
from tools import prepare_submission as submission
from tools.audit_repository import scan_text


@pytest.fixture
def public_copy(tmp_path, monkeypatch):
    destination = tmp_path / 'publication'
    shutil.copytree(submission.PUBLIC, destination)
    monkeypatch.setattr(submission, 'PUBLIC', destination)
    return destination


def test_published_evidence_recomputes_without_database_or_model_calls(public_copy, monkeypatch):
    forbidden = Mock(side_effect=AssertionError('Review is offline'))
    monkeypatch.setattr(agent, 'OpenAI', forbidden)
    monkeypatch.setattr(agent, 'run_agent', forbidden)
    monkeypatch.setattr(db, 'connect', forbidden)
    result = submission.check_publication()
    assert result['verified'] and result['unique_scenarios'] == 15
    assert result['metrics']['scenario_exact_success']['numerator'] == 15
    assert result['api_usage']['attempted_calls'] == 52
    assert result['api_usage']['observed_tokens']['total_tokens'] == 25355
    assert result['api_usage']['approximate_uncached_cost_usd'] == pytest.approx(0.0126728)
    forbidden.assert_not_called()


@pytest.mark.parametrize('change', ['duplicate_id', 'false_metric', 'false_cost', 'false_provenance', 'wrong_expected'])
def test_evidence_verifier_rejects_inconsistent_results(public_copy, change):
    path = public_copy / 'summary.json'
    data = json.loads(path.read_text())
    if change == 'duplicate_id':
        data['scenarios'][1]['id'] = data['scenarios'][0]['id']
    elif change == 'false_metric':
        data['metrics']['employee_information_accuracy']['numerator'] -= 1
    elif change == 'false_cost':
        data['api_usage']['approximate_uncached_cost_usd'] = 0
    elif change == 'false_provenance':
        data['source_runs']['pilot']['command'] = 'fabricated command'
    else:
        data['scenarios'][0]['expected']['resources'] = {}
    path.write_text(json.dumps(data))
    # Check substantive verification, not just manifest mismatch.
    with pytest.raises(ValueError):
        submission.verify_evidence(public_copy)


@pytest.mark.parametrize('name', ['results.csv', 'EVALUATION_REPORT.md'])
def test_csv_and_markdown_must_agree_with_json(public_copy, name):
    path = public_copy / name
    text = path.read_text()
    if name.endswith('.csv'):
        text = text.replace(',passed,', ',failed,', 1)
    else:
        text = text.replace('| scenario_exact_success | 15 | 15 |', '| scenario_exact_success | 0 | 15 |')
    path.write_text(text)
    with pytest.raises(ValueError):
        submission.verify_evidence(public_copy)


def test_export_hashes_detect_changes_and_paths_are_sanitized(public_copy):
    path = public_copy / 'summary.json'
    path.write_text(path.read_text() + '\n')
    with pytest.raises(ValueError):
        submission.check_publication()
    root = 'C:' + '\\Users\\' + 'SyntheticWorkstation' + '\\fixture-project'
    sample = {'command': root + '\\.venv\\Scripts\\python.exe', 'working_directory': root,
              'tokens': 100, 'employee': {'name': 'Synthetic Fixture'}}
    clean = submission.portable(sample, {root})
    assert clean['working_directory'] == '.' and clean['command'].startswith('.\\.venv')
    assert clean['tokens'] == 100 and clean['employee'] == sample['employee']
    assert 'sensitive_local_user_path' in scan_text(json.dumps(sample))
    assert not scan_text(json.dumps(clean))


def test_git_preserves_frozen_source_and_publication_bytes():
    paths = list(submission.h.FROZEN_FILES) + ['evaluation/heldout/protocol.json',
             'evaluation/heldout/protocol_remaining.json']
    paths += [path.relative_to(submission.ROOT).as_posix() for path in submission.PUBLIC.rglob('*') if path.is_file()]
    for name in paths:
        raw = subprocess.run(['git', 'hash-object', '--no-filters', name], cwd=submission.ROOT, capture_output=True, check=True)
        filtered = subprocess.run(['git', 'hash-object', '--path=' + name, name], cwd=submission.ROOT, capture_output=True, check=True)
        assert raw.stdout == filtered.stdout, f'Git would change frozen bytes: {name}'
