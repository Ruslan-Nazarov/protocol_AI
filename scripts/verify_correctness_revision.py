"""Offline preservation, traceability and context-budget checks; no API calls."""
import json
from pathlib import Path
import sys
import subprocess

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from protocol_atlas.catalog import digest,parse_document
from protocol_atlas.runtime_rules import compile_rules,section_basis,CORE_SECTIONS


def main():
    data=json.loads((ROOT/'atlas/correctness_migration.json').read_text(encoding='utf-8'))
    previous=(ROOT/data['old_source']).read_bytes()
    current=(ROOT/data.get('new_source','PROTOCOL.md')).read_bytes()
    assert digest(previous)==data['old_sha256']
    assert digest(current)==data['new_sha256']
    old=previous.decode('utf-8').replace('\r\n','\n')
    new=current.decode('utf-8').replace('\r\n','\n')
    replaced={r['before'] for r in data['replacements']}
    assert len(replaced)==7
    for replacement in data['replacements']:
        assert replacement['before'] in old and replacement['after'] in new
    for paragraph in old.split('\n\n'):
        assert not paragraph.strip() or paragraph in new or paragraph in replaced, paragraph[:120]
    before=parse_document('PROTOCOL.md',previous)
    after=parse_document('PROTOCOL.md',current)
    ids=lambda d:[s['title'].split()[0].rstrip('.') for s in d['sections'] if s['title'][0].isdigit()]
    assert ids(before)==ids(after)==[r['section'] for r in data['sections']]
    assert len(data['sections'])==75
    for r in data['sections']:
        assert digest(section_basis(before,r['section'])[1].encode())==r['old_basis_sha256']
        assert digest(section_basis(after,r['section'])[1].encode())==r['new_basis_sha256']
    # Preserve the first migration exactly, then verify the human's later edits.
    follow=json.loads((ROOT/'atlas/four_pillars_migration.json').read_text(encoding='utf-8'))
    assert data['new_source']==follow['old_source']
    assert data['new_sha256']==follow['old_sha256']
    latest=(ROOT/follow.get('new_source','PROTOCOL.md')).read_bytes()
    assert digest(latest)==follow['new_sha256']
    newest=latest.decode('utf-8').replace('\r\n','\n')
    changed={r['before'] for r in follow['replacements']}
    assert len(changed)==3
    for row in follow['replacements']:
        assert row['before'] in new and row['reason']
        if row['after']:
            assert row['after'] in newest
        else:
            assert row['before'] not in newest
            assert row['before'] in (ROOT/row['preserved_in']).read_text(encoding='utf-8')
    for paragraph in new.split('\n\n'):
        assert not paragraph.strip() or paragraph in newest or paragraph in changed, paragraph[:120]
    latestdoc=parse_document('PROTOCOL.md',latest)
    assert ids(after)==ids(latestdoc)==[r['section'] for r in follow['sections']]
    for row in follow['sections']:
        assert digest(section_basis(after,row['section'])[1].encode())==row['old_basis_sha256']
        assert digest(section_basis(latestdoc,row['section'])[1].encode())==row['new_basis_sha256']
    revision=json.loads((ROOT/'atlas/section2_migration.json').read_text(encoding='utf-8'))
    assert follow['new_source']==revision['old_source']
    assert follow['new_sha256']==revision['old_sha256']
    final=(ROOT/revision.get('new_source','PROTOCOL.md')).read_bytes()
    assert digest(final)==revision['new_sha256']
    finaltext=final.decode('utf-8').replace('\r\n','\n')
    def split_section2(text):
        start,end=text.index('## 2.'),text.index('## 3.')
        return text[:start],text[start:end],text[end:]
    oldparts,newparts=split_section2(newest),split_section2(finaltext)
    assert oldparts[0]==newparts[0] and oldparts[2]==newparts[2], 'Changed outside section 2'
    assert digest(oldparts[1].encode())==revision['old_section_sha256']
    assert digest(newparts[1].encode())==revision['new_section_sha256']
    assert len(oldparts[1])==revision['old_characters']
    assert len(newparts[1])==revision['new_characters'] < revision['old_characters']
    assert ids(latestdoc)==ids(parse_document('PROTOCOL.md',final))
    assert (ROOT/revision['meaning_review']).is_file()
    core=compile_rules(ROOT,[]);all_rules=compile_rules(ROOT)
    assert CORE_SECTIONS <= {r['section'] for r in core['rules']}
    assert core['characters'] <= all_rules['characters'] <= 12000
    assert all_rules['characters'] < all_rules['full_characters']
    assert core['context_size']['exact_tokens'] is None
    assert (ROOT/'protocol_atlas/runtime_rules.py').read_bytes()==(ROOT/'.protocol/engine/protocol_atlas/runtime_rules.py').read_bytes()
    for name in ('docs/CORRECTNESS_REVISION.md','docs/TOKEN_ECONOMY.md'):
        assert (ROOT/name).is_file()
    for script in ('verify_logic_revision.py','verify_remediation_inventory.py'):
        subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts'/script)],cwd=ROOT,check=True)
    print(json.dumps(dict(historical_sections=75,historical_replacements=7,followup_changes=3,historical_paragraphs_accounted=True,
                         historical_rewritten_section='2',historical_outside_section2_unchanged=True,
                         core_characters=core['characters'],all_characters=all_rules['characters'],
                         full_characters=all_rules['full_characters'],api_calls=0)))


if __name__=='__main__':main()
