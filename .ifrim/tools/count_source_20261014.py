"""Physical source lines with a finite manifest, excluding generated/vendor/archives."""
import hashlib, json, os
from pathlib import Path
from datetime import datetime, timezone

A = Path(__file__).resolve().parents[2]
extensions = {'.py', '.js', '.jsx', '.ts', '.tsx', '.css', '.html', '.cjs', '.mjs', '.kt', '.java', '.swift'}
skip = {'node_modules', '.venv', '__pycache__', '.pytest_cache', '.git', '.tmp', 'build', 'dist', 'artifacts', 'fixtures'}
groups = {'frontend': A / 'frontend', 'backend': A / 'backend', 'mobile_probe': A / 'tools/mobile-gps-probe'}
rows = []
for group, root in groups.items():
    for parent, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip and not (group == 'mobile_probe' and Path(parent) == root and d in {'android', 'ios'})]
        for name in files:
            p = Path(parent) / name
            if p.suffix not in extensions:
                continue
            rel = p.relative_to(A).as_posix()
            data = p.read_bytes()
            lines = len(data.splitlines())
            is_test = 'tests' in p.relative_to(root).parts or '.test.' in name or name == 'setupTests.js'
            rows.append({'path': rel, 'group': group, 'kind': 'tests' if is_test else 'source',
                'physical_lines': lines, 'sha256': hashlib.sha256(data).hexdigest()})
totals = {group: {kind: sum(x['physical_lines'] for x in rows if x['group'] == group and x['kind'] == kind)
    for kind in ('source', 'tests')} for group in groups}
report = {'generated_at': datetime.now(timezone.utc).isoformat(), 'totals': totals,
    'source_lines': sum(v['source'] for v in totals.values()), 'test_lines': sum(v['tests'] for v in totals.values()),
    'includes_comments_and_blank_lines': True, 'excludes': sorted(skip) + ['generated_mobile_android_ios', 'QA archives', 'configuration JSON', 'QA orchestration scripts'],
    'scope': 'frontend including authored build config/plugins, backend Python, authored mobile probe TS/JS/native modules/plugins; tests separate; third-party fixture copies excluded',
    'files': rows}
out = A / '.ifrim/QA_RUNS/2026-10-14-source-count'
out.mkdir(exist_ok=True)
dest = out / (datetime.now(timezone.utc).strftime('%H%M%S') + '-count.json')
with dest.open('x', encoding='utf-8') as f:
    json.dump(report, f, indent=2)
print(json.dumps({k: v for k, v in report.items() if k != 'files'}))
