"""Read-only source/installation audit, plus optional complete local regression."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from protocol_atlas.catalog import build_catalog,digest,parse_document
from protocol_atlas.runtime_rules import verify_registry,section_basis
from protocol_atlas.translations import TranslationStore
from protocol_atlas.connection_files import CONNECTION_FILES,connection_download


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tests',action='store_true')
    args=parser.parse_args()
    manifest=verify_registry(ROOT)
    assert json.loads((ROOT/'.protocol/rules.json').read_text(encoding='utf-8'))==manifest, 'Installed rules stale'
    for name in ('logic.py','project_runtime.py','runtime_cli.py','runtime_install.py','runtime_rules.py'):
        assert (ROOT/'protocol_atlas'/name).read_bytes()==(ROOT/'.protocol/engine/protocol_atlas'/name).read_bytes(), 'Installed code stale: '+name
    for name in ('SKILL.md','references/contract.md'):
        # Installer writes text using host line endings; compare decoded content.
        assert (ROOT/'skills/protocol-work'/name).read_text(encoding='utf-8')==(ROOT/'.protocol/skills/protocol-work'/name).read_text(encoding='utf-8'), 'Installed instructions stale: '+name
    assert (ROOT/'protocol_atlas/web/runtime_dashboard.js').read_text(encoding='utf-8')==(ROOT/'.protocol/engine/protocol_atlas/web/runtime_dashboard.js').read_text(encoding='utf-8'), 'Installed dashboard stale'
    catalog=build_catalog(ROOT)
    assert catalog['coverage']['source_text_complete']
    doc=parse_document('PROTOCOL.md',(ROOT/'PROTOCOL.md').read_bytes())
    audit=json.loads((ROOT/'atlas/logic_rule_audit.json').read_text(encoding='utf-8'))
    expected={s['title'].split()[0].rstrip('.') for s in doc['sections'] if s['title'][0].isdigit()}
    assert audit['source_sha256']==doc['sha256'], 'Audit refers to an old protocol'
    assert len(audit['sections'])==len(expected)
    assert {s['section'] for s in audit['sections']}==expected
    for row in audit['sections']:
        assert row['basis_sha256']==digest(section_basis(doc,row['section'])[1].encode('utf-8')), row['section']
        assert row['note'] and row['decision']
        assert all((ROOT/p).is_file() for p in row['related_files'])
    documents=('PROTOCOL.md','README.md','docs/PROTOCOL_BRIEF.md','docs/PROCESS_AUDIT.md',
               'docs/LOGIC_ADAPTER.md','docs/LOGIC_RULE_AUDIT.md','docs/LOGIC_TESTS.md',
               'docs/UNCERTAINTY_REVIEW.md','docs/DETECTION_EVALUATION.md','docs/ENFORCEMENT_BOUNDARY.md',
               'docs/VERIFICATION_MODES.md','docs/LOGIC_PILOT_RESULTS.md','docs/REMEDIATION_DELIVERY.md',
               'docs/CORRECTNESS_REVISION.md','docs/TOKEN_ECONOMY.md','docs/FOUR_PILLARS.md','docs/SECTION2_REVISION.md','docs/EXECUTION_PROTOCOL.md')
    links=0
    for relative in documents:
        path=ROOT/relative
        for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)',path.read_text(encoding='utf-8')):
            if re.match(r'[a-zA-Z][a-zA-Z0-9+.-]*:',target) or target.startswith('#'):continue
            assert (path.parent/target.split('#',1)[0]).is_file(), relative+' -> '+target
            links+=1
    store=TranslationStore(ROOT)
    for relative in CONNECTION_FILES:
        assert store.read(relative)['pending']==0, 'Stale English connection document: '+relative
    bundle,_,media=connection_download(ROOT,language='en')
    assert bundle and media=='application/zip'
    print(json.dumps({'audit_sections':len(expected),'instructions':len(manifest['rules']),
                      'local_links':links,'installed':'current','english_connection':'current','catalog':'pass'}))
    if args.tests:
        result=subprocess.run([sys.executable,'-X','utf8','-m','unittest','discover','-s','tests','-q'],
                              cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        output=result.stdout+result.stderr
        (ROOT/'build').mkdir(exist_ok=True)
        (ROOT/'build/logic_revision_test_output.txt').write_text(output,encoding='utf-8')
        print(output.strip())
        return result.returncode
    return 0


if __name__=='__main__':raise SystemExit(main())
