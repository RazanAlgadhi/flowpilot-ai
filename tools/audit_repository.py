"""Read-only source/history audit. Never print matched values or read current .env."""
import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

PATTERNS = {
    'openai_key_shape': re.compile(r'\bsk-[A-Za-z0-9_-]{20,}'),
    'github_token_shape': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{30,})'),
    'aws_access_key_shape': re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'private_key_header': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
}
REQUIRED_IGNORES = ['.env', '.env.production', '.venv/file', '__pycache__/file.pyc', '.pytest_cache/file',
                    'flowpilot.db', 'data.sqlite', 'data.sqlite3', 'data.db-wal', '.streamlit/secrets.toml',
                    '.aws/credentials', 'private.key']
PUBLIC_EXAMPLES = {'.env.example', '.streamlit/secrets.example.toml'}


def git(root, *args, input=None):
    return subprocess.run(['git', '-C', str(root), *args], input=input, capture_output=True)


def ignored_paths(root, paths):
    # An isolated throwaway repository tests actual Git ignore semantics without
    # initializing the user's project or copying any secret/database file.
    with tempfile.TemporaryDirectory(prefix='flowpilot-ignore-audit-') as directory:
        temporary = Path(directory)
        result = git(temporary, 'init', '-q')
        if result.returncode:
            raise RuntimeError('Cannot validate Git ignore rules')
        (temporary / '.gitignore').write_bytes((root / '.gitignore').read_bytes())
        result = git(temporary, 'check-ignore', '--no-index', '-z', '--stdin', input='\0'.join(paths).encode() + b'\0')
        if result.returncode not in (0, 1):
            raise RuntimeError('Cannot validate Git ignore rules')
        return set(result.stdout.decode('utf-8', errors='replace').strip('\0').split('\0')) - {''}


def scan_text(content):
    findings = [name for name, pattern in PATTERNS.items() if pattern.search(content)]
    literal = re.compile(r'''(?im)(?:api[_-]?key|client[_-]?secret|password|access[_-]?token)\s*["']?\s*[:=]\s*["']([^"'\n]{12,})["']''')
    for match in literal.finditer(content):
        value = match.group(1)
        if not any(word in value.lower() for word in ('test', 'synthetic', 'sentinel', 'placeholder', 'your_', 'example', 'redacted')):
            if re.fullmatch(r'[A-Za-z0-9_./+=-]{24,}', value):
                findings.append('suspicious_credential_literal')
                break
    return findings


def sensitive_path(name):
    path = Path(name)
    return (path.name.startswith('.env') and name not in PUBLIC_EXAMPLES
            or path.name == 'secrets.toml'
            or path.suffix in ('.db', '.sqlite', '.sqlite3', '.pem', '.key')
            or any(part in ('.venv', '.aws', '__pycache__') for part in path.parts))


def audit(root):
    root = Path(root).resolve()
    findings = []
    checked = ignored_paths(root, REQUIRED_IGNORES + list(PUBLIC_EXAMPLES))
    for name in REQUIRED_IGNORES:
        if name not in checked:
            findings.append({'path': name, 'category': 'missing_ignore_rule'})
    for name in PUBLIC_EXAMPLES:
        if name in checked:
            findings.append({'path': name, 'category': 'public_template_ignored'})
    repo = git(root, 'rev-parse', '--is-inside-work-tree').returncode == 0
    tracked = set()
    if repo:
        tracked = set(git(root, 'ls-files', '-z').stdout.decode().strip('\0').split('\0')) - {''}
        for name in sorted(tracked):
            if sensitive_path(name):
                findings.append({'path': name, 'category': 'sensitive_file_already_tracked'})
    paths = []
    for directory, children, files in os.walk(root):
        children[:] = [name for name in children if name not in ('.git', '.venv', 'venv', '__pycache__', '.pytest_cache', '.aws', '.codex', '.agents')]
        paths.extend((Path(directory) / name).relative_to(root).as_posix() for name in files)
    ignored = ignored_paths(root, paths)
    candidates = sorted(set(paths) - ignored)
    scanned = 0
    for name in sorted(set(candidates) | tracked):
        if sensitive_path(name):
            continue  # Never open current .env, secrets, or employee database files.
        path = root / name
        if not path.is_file():
            continue
        content = path.read_text(encoding='utf-8', errors='replace')
        scanned += 1
        findings.extend({'path': name, 'category': category} for category in scan_text(content))
        if name in PUBLIC_EXAMPLES:
            for line in content.splitlines():
                if line.strip().startswith('OPENAI_API_KEY') and '=' in line:
                    value = line.split('=', 1)[1].strip().strip('"\'')
                    if value not in ('YOUR_OPENAI_API_KEY', ''):
                        findings.append({'path': name, 'category': 'template_has_non_placeholder_key'})
    history_blobs = 0
    history_status = 'unavailable_no_git_repository'
    if repo:
        history_status = 'inspected_reachable_refs_and_reflogs'
        objects = git(root, 'rev-list', '--objects', '--all', '--reflog')
        if objects.returncode:
            history_status = 'history_scan_failed'
            findings.append({'category': history_status})
        for line in objects.stdout.decode(errors='replace').splitlines():
            parts = line.split(' ', 1)
            oid, name = parts[0], parts[1] if len(parts) == 2 else '(unnamed object)'
            if git(root, 'cat-file', '-t', oid).stdout.strip() != b'blob':
                continue
            if sensitive_path(name):
                findings.append({'path': name, 'category': 'sensitive_file_in_history'})
            # Values remain in memory; never output blob text or match snippets.
            content = git(root, 'cat-file', 'blob', oid).stdout.decode(errors='replace')
            history_blobs += 1
            findings.extend({'path': name, 'category': 'history_' + category} for category in scan_text(content))
    return {'git_repository': repo, 'history_status': history_status, 'history_blobs_scanned': history_blobs,
            'candidate_files_scanned': scanned, 'required_ignore_rules_passed': all(name in checked for name in REQUIRED_IGNORES),
            'findings': findings,
            'limitations': 'Pattern scan, not a guarantee that every possible secret is detectable. No remote history or unreachable pruned Git objects inspected. Current .env and databases were not opened.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result = audit(args.root)
    except Exception:
        print('Audit could not complete; check Git availability and file permissions. Details suppressed.')
        return 1
    print(json.dumps(result, indent=2))
    return 1 if result['findings'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
