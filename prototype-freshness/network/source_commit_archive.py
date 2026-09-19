#!/usr/bin/env python3
"""Archive explicit run identities, including failures; never infer latest by mtime."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('selection', type=Path)
    args = parser.parse_args()
    assert sys.platform == 'win32', 'use existing WSL share from Windows for byte-preserving copy'
    base = Path(r'\\wsl.localhost\Ubuntu\home\alan\.cache\tyche-prototypes\quic-20260919')
    destination = HERE / 'evidence'
    selection = json.loads(args.selection.read_text())
    reports = []
    for item in selection:
        source, target = base / item['source'], destination / item['archive']
        assert source.is_dir() and not target.exists()
        assert not list(source.rglob('*.key'))
        original = {p.relative_to(source).as_posix(): sha(p) for p in source.rglob('*') if p.is_file()}
        shutil.copytree(source, target)
        copied = {p.relative_to(target).as_posix(): sha(p) for p in target.rglob('*') if p.is_file()}
        assert copied == original
        report = {**item, 'files_copied': len(copied), 'bytes_copied': sum(p.stat().st_size for p in target.rglob('*') if p.is_file()),
                  'copied_utc': datetime.now(timezone.utc).isoformat(), 'sha256': copied}
        (target / 'archive.json').write_text(json.dumps(report, indent=2))
        reports.append({k: v for k, v in report.items() if k != 'sha256'})
        print(json.dumps({'archive': item['archive'], 'files': len(copied), 'verified': True}), flush=True)
    output = destination / 'source-commit-archive-index.json'
    assert not output.exists()
    output.write_text(json.dumps(reports, indent=2))


if __name__ == '__main__':
    main()
