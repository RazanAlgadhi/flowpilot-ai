"""Offline evidence verification and privacy-preserving publication export. No API calls."""
import argparse
import csv
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.heldout import run_heldout as h
from tools.audit_repository import scan_text

PUBLIC = h.HERE / 'publication'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def verify_csv(text, rows):
    records = list(csv.DictReader(io.StringIO(text)))
    require([r['id'] for r in records] == [r['id'] for r in rows], 'CSV IDs/order mismatch')
    for record, row in zip(records, rows):
        require(all(record[k] == row[k] for k in ('category', 'mode', 'status')), 'CSV status/category mismatch')
        require(float(record['agent_duration_seconds']) == row['agent_duration_seconds'], 'CSV timing mismatch')
        require(int(record['live_api_calls']) == row['api_usage']['live_sdk_calls'], 'CSV usage mismatch')
        require(json.loads(record['failed_checks']) == [k for k, v in row['judgment']['checks'].items() if not v], 'CSV checks mismatch')
        require(json.loads(record['errors']) == row['errors'] + row['judgment']['tool_errors'], 'CSV errors mismatch')


def verify_markdown(text, summary):
    require('Live OpenAI agent evaluation; no mocked primary results' in text, 'Missing live-mode disclosure')
    for key, metric in summary['metrics'].items():
        if 'denominator' in metric:
            require(f"| {key} | {metric['numerator']} | {metric['denominator']} | {metric['value']} |" in text,
                    'Markdown metric mismatch')
    for row in summary['scenarios']:
        failed = ', '.join(k for k, v in row['judgment']['checks'].items() if not v) or 'None'
        require(f"| {row['id']} | {row['category']} | {row['status']} | {failed} | {row['agent_duration_seconds']:.3f} |" in text,
                'Markdown case mismatch')


def verify_evidence(folder, *, originals=False):
    """Recompute decisions/aggregates from evidence, and check both run manifests."""
    folder = Path(folder)
    data = h.load_cases()
    frozen = h.verify_freeze()
    combined, pilot = read_json(folder / 'summary.json'), read_json(folder / 'pilot/summary.json')
    require(combined['mode'] == pilot['mode'] == 'live', 'Results are not live mode')
    require(combined['subset'] == 'combined_pilot_and_remaining' and pilot['subset'] == 'pilot', 'Wrong run subsets')
    require(combined['dataset_id'] == pilot['dataset_id'] == data['dataset_id'], 'Dataset mismatch')
    rows = combined['scenarios']
    cases = {s['id']: s for s in data['scenarios']}
    require(len(rows) == len(cases) == 15 and {r['id'] for r in rows} == set(cases), 'Expected 15 unique cases')
    require(combined['protocol'] == frozen and pilot['protocol'] == read_json(h.PROTOCOL), 'Source protocol mismatch')
    for row in rows:
        case = cases[row['id']]
        require(row['mode'] == 'live' and row['interface'] == 'agent' and row['expected'] == case['expected'], 'Row/expectation mismatch')
        require(row['category'] == case['category'] and row['rationale'] == case['rationale'], 'Case metadata mismatch')
        require([a['request'] for a in row['actions']] == case['requests'], 'Request mismatch')
        checked = h.judge(case, row['actions'], row['api_usage']['errors'], row['response_metadata'])
        if row['errors'] or row['api_usage']['errors']:
            checked['checks']['execution_completed_without_exception'] = False
            checked['passed'] = False
            if checked['invalid_safe'] is not None:
                checked['invalid_safe'] = False
        require(row['judgment'] == checked and row['status'] == ('passed' if checked['passed'] else 'failed'), 'Stored judgment mismatch')
        usage = row['api_usage']
        require(usage['mock_model_calls'] == 0 and usage['live_sdk_calls'] > 0, 'Missing live request evidence')
        require(len(row['response_metadata']) == usage['live_responses'], 'Response count mismatch')
        counts = usage['observed_tokens']
        if counts:
            require(all(type(v) is int and v >= 0 for v in counts.values()) and
                    counts['total_tokens'] == counts['prompt_tokens'] + counts['completion_tokens'], 'Invalid token totals')
    pilot_rows = [r for r in rows if r['id'] in data['pilot_ids']]
    require(pilot_rows == pilot['scenarios'], 'Pilot rows changed or counted incorrectly')
    require(combined['aggregation']['reused_pilot_ids'] == [r['id'] for r in pilot_rows], 'Imported pilot IDs mismatch')
    remaining_rows = [r for r in rows if r['id'] not in data['pilot_ids']]
    require(combined['aggregation']['new_scenario_ids'] == [r['id'] for r in remaining_rows], 'Remaining IDs mismatch')
    for label, selected in (('pilot', pilot_rows), ('remaining', remaining_rows)):
        source = combined['source_runs'][label]
        require(source['production_database_unchanged'] and source['frozen_sources_unchanged_after_run'], 'Run isolation/source check failed')
        if label == 'pilot':
            require(all(source[k] == pilot[k] for k in source), 'Pilot run provenance changed')
        else:
            require(source['protocol'] == frozen, 'Remaining run protocol mismatch')
        plan = source['preflight']
        budget = h.common.ApiBudget(plan['enforced_api_call_limit'], plan['max_output_tokens_per_call'], plan['configured_model'])
        require(plan['cost_ceiling'] == h.common.cost_ceiling(budget), 'Pricing/ceiling mismatch')
        require(plan['scenario_ids'] == [r['id'] for r in selected], 'Run selection mismatch')
        recalculated = h.summarize(selected, plan, source['command'], True, source['protocol'])
        require(recalculated['api_usage'] == source['api_usage'], 'Run usage or cost mismatch')
        require(source['safety_controls']['attempted_calls'] == recalculated['api_usage']['attempted_calls'] <= budget.max_api_calls,
                'Run call limit/accounting mismatch')
        if label == 'pilot':
            for key in ('metrics', 'direct_approval_api'):
                require(recalculated[key] == pilot[key], 'Pilot aggregate mismatch')
        else:
            require(recalculated['metrics'] == combined['aggregation']['new_run_metrics'], 'Remaining metric mismatch')
    aggregation_plan = dict(combined['preflight'], approval_probe_ids=[s['id'] for s in data['scenarios'] if 'approval_probe' in s])
    recomputed = h.summarize(rows, aggregation_plan, combined['command'], True, frozen)
    for key in ('metrics', 'api_usage', 'direct_approval_api'):
        require(combined[key] == recomputed[key], 'Combined aggregate mismatch')
    # Independently verify recorded simulator outcomes, without invoking approval APIs.
    probe_row = next(r for r in rows if 'approval_probe' in cases[r['id']])
    probe = probe_row['approval_probe']
    require(probe['interface'] == 'direct_approval_api' and all(probe['checks'].values()), 'Approval probe failed')
    require('error' in probe['results'][0] and probe['results'][1] == probe['results'][2] and
            probe['results'][1]['status'] == 'approved_pending_provisioning', 'Approval evidence inconsistent')
    expected_after = json.loads(json.dumps(probe_row['actions'][-1]['after']))
    for request in expected_after['requests']:
        if request['kind'] == 'github':
            require(request['status'] == 'pending_manager_approval', 'Agent prematurely approved GitHub')
            request['status'] = 'approved_pending_provisioning'
    require(probe['after'] == expected_after, 'Approval changed unrelated records')
    for location, summary in ((folder, combined), (folder / 'pilot', pilot)):
        verify_csv((location / 'results.csv').read_text(encoding='utf-8'), summary['scenarios'])
        verify_markdown((location / 'EVALUATION_REPORT.md').read_text(encoding='utf-8'), summary)
    if originals:
        require(combined['aggregation']['pilot_report_sha256'] == h.pilot_fingerprints(), 'Original pilot hashes changed')
        require((folder / 'EVALUATION_REPORT.md').read_text(encoding='utf-8') == h.markdown(combined), 'Combined Markdown differs from generator')
    return combined, pilot


def portable(value, roots):
    """Normalize only machine-specific location metadata, not results or identities."""
    if isinstance(value, dict):
        return {key: portable(item, roots) for key, item in value.items()}
    if isinstance(value, list):
        return [portable(item, roots) for item in value]
    if isinstance(value, str):
        for root in sorted(roots, key=len, reverse=True):
            for variant in (root, root.replace('\\', '/'), root.replace('\\', '\\\\')):
                value = value.replace(variant, '.')
        return value
    return value


def prepare():
    combined, pilot = verify_evidence(h.HERE, originals=True)
    roots = {combined['working_directory'], pilot['working_directory']}
    roots.update(run['working_directory'] for run in combined['source_runs'].values())
    manifest = {'kind': 'sanitized_publication_derivative', 'prepared_on': '2026-10-30',
                'note': 'Only local workstation paths were normalized to repository-relative paths. Original live evidence remains local and unchanged. Original hashes are provenance references, not hashes of sanitized copies.',
                'original_sha256': {}, 'published_sha256': {}}
    for src, dest, summary in ((h.HERE, PUBLIC, combined), (h.HERE / 'pilot', PUBLIC / 'pilot', pilot)):
        dest.mkdir(parents=True, exist_ok=True)
        for name in h.REPORT_FILES:
            relative = (dest / name).relative_to(PUBLIC).as_posix()
            manifest['original_sha256'][relative] = h.digest(src / name)
            if name == 'summary.json':
                content = json.dumps(portable(summary, roots), indent=2) + '\n'
            else:
                content = portable((src / name).read_text(encoding='utf-8'), roots)
            require(not scan_text(content), 'Publication still contains a sensitive pattern')
            (dest / name).write_text(content, encoding='utf-8')
            manifest['published_sha256'][relative] = h.digest(dest / name)
    (PUBLIC / 'PUBLICATION_MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    require(all(h.digest(h.HERE / name) == expected for name, expected in manifest['original_sha256'].items()),
            'Original held-out files changed during publication export')
    # Earlier tracked mocked reports also contain workstation paths. Normalize
    # only paths in those files; do not regenerate their outcomes or timings.
    for folder in (ROOT / 'evaluation', ROOT / 'evaluation/mocked'):
        old_summary = read_json(folder / 'summary.json')
        old_roots = roots | {old_summary['working_directory']}
        for name in ('summary.json', 'EVALUATION_REPORT.md'):
            path = folder / name
            path.write_text(portable(path.read_text(encoding='utf-8'), old_roots), encoding='utf-8')
    return check_publication()


def check_publication():
    manifest = read_json(PUBLIC / 'PUBLICATION_MANIFEST.json')
    expected_files = set(h.REPORT_FILES) | {'pilot/' + name for name in h.REPORT_FILES}
    require(set(manifest['published_sha256']) == set(manifest['original_sha256']) == expected_files, 'Export manifest file set mismatch')
    for name, expected in manifest['published_sha256'].items():
        require(h.digest(PUBLIC / name) == expected, 'Publication hash mismatch')
        require(not scan_text((PUBLIC / name).read_text(encoding='utf-8')), 'Sensitive publication content')
    combined, pilot = verify_evidence(PUBLIC)
    require(combined['aggregation']['pilot_report_sha256'] ==
            {name: manifest['original_sha256']['pilot/' + name] for name in h.REPORT_FILES}, 'Original pilot provenance mismatch')
    return {'verified': True, 'unique_scenarios': len(combined['scenarios']), 'metrics': combined['metrics'],
            'api_usage': combined['api_usage'], 'publication_paths_sanitized': True,
            'note': 'Offline consistency/manifest verification, not independent provider attestation. No APIs called.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true', help='Create sanitized copies from original local reports; normalize paths in older mocked reports')
    args = parser.parse_args()
    try:
        result = prepare() if args.prepare else check_publication()
    except Exception as exc:
        print(f'Offline verification failed ({type(exc).__name__}); inspect report consistency. Values suppressed.')
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
