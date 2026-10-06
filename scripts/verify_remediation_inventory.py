"""Validate the actionable register without certifying its prose semantics."""
from pathlib import Path
import json, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from protocol_atlas.catalog import parse_document
data=json.loads((ROOT/'atlas/remediation.json').read_text(encoding='utf-8'))
assert data['schema_version']==1
ids=set()
for row in data['requirements']:
    assert row['id'] not in ids and row['criterion'].strip()
    ids.add(row['id'])
    assert row['status'] in ('open','implemented','environment_limit','research_open')
    assert row['priority'] in (1,2,3) and (ROOT/row['source']).is_file()
audit=json.loads((ROOT/'atlas/logic_rule_audit.json').read_text(encoding='utf-8'))
doc=parse_document('PROTOCOL.md',(ROOT/'PROTOCOL.md').read_bytes())
expected={s['title'].split()[0].rstrip('.') for s in doc['sections'] if s['title'][0].isdigit()}
assert {s['section'] for s in audit['sections']}==expected
print(json.dumps({'requirements':len(ids),'protocol_sections':len(expected),'historical_topics':len(data['historical_questions']), 'semantic_review':'agent, not mechanically verified'}))
