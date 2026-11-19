#!/usr/bin/env python3
"""Validate skill metadata, templates, checksums and Python syntax."""
from pathlib import Path
import ast
import hashlib
import json
import re
import yaml

root = Path(__file__).resolve().parents[1]
skill = root / 'skills/pdf-zh-localization'
text = (skill / 'SKILL.md').read_text(encoding='utf-8')
assert text.startswith('---\n'), 'Missing YAML front matter'
metadata = yaml.safe_load(text.split('---', 2)[1])
assert re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', metadata['name'])
assert metadata['name'] == skill.name
assert metadata['description'].strip()
for path in skill.rglob('*.json'):
    json.loads(path.read_text(encoding='utf-8'))
for path in list(skill.rglob('*.yaml')) + list((root/'.github/workflows').glob('*.yml')):
    yaml.safe_load(path.read_text(encoding='utf-8'))
for path in root.rglob('*.py'):
    ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
for row in (skill / 'SHA256SUMS.txt').read_text().splitlines():
    expected, relative = row.split('  ', 1)
    path = skill / relative
    assert path.is_file() and skill.resolve() in path.resolve().parents
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, relative
for required in ['README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md']:
    assert (root/required).is_file()
print('PASS: skill metadata, JSON/YAML, Python syntax and packaged file checksums')
