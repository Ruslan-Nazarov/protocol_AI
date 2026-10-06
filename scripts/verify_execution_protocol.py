"""Validate editorial coverage and route scenarios, not truth or real execution."""
import json
from pathlib import Path
import sys
import subprocess

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from protocol_atlas.catalog import digest,parse_document
from protocol_atlas.runtime_rules import compile_rules,section_basis


def validate(root):
    spec=json.loads((root/'atlas/execution_protocol.json').read_text(encoding='utf-8'))
    rules=spec['rules'];lookup={r['id']:r for r in rules}
    assert len(lookup)==len(rules) and spec['entry']=='1.1'
    stages={s['id'] for s in spec['stages']}
    assert stages=={str(n) for n in range(1,11)}
    for r in rules:
        assert r['stage'] in stages and r['id'].startswith(r['stage']+'.')
        assert all(isinstance(r[k],str) and r[k].strip() for k in
                   ('action','check','instruction','implementation_scope','checker_kind','transition_text'))
        for k in ('on_pass','on_fail','on_unknown'):
            assert r[k] in lookup or r[k] in ('done','wait','return_origin')
        assert r['on_unknown']=='wait' and r['on_fail']!='done'
        if r['mechanism']:assert (root/r['mechanism']).is_file()
    # Reconstruct exact main text: no free-floating principles or orphan rules.
    parts=['# Протокол работы с ИИ — v0.5']
    for s in spec['stages']:
        parts += [f"## {s['id']}. {s['title']}",s['guard']]
        for r in rules:
            if r['stage']==s['id']:parts += [f"### {r['id']} {r['title']}",r['action'],'**Проверка.** '+r['check'],r['transition_text']]
    raw=(root/'PROTOCOL.md').read_bytes()
    assert raw.decode('utf-8').replace('\r\n','\n')=='\n\n'.join(parts)+'\n'
    migration=json.loads((root/'atlas/execution_migration.json').read_text(encoding='utf-8'))
    oldraw=(root/migration['old_source']).read_bytes()
    assert digest(oldraw)==migration['old_sha256'] and digest(raw)==migration['new_sha256']
    olddoc=parse_document('PROTOCOL.md',oldraw)
    oldids={s['title'].split()[0].rstrip('.') for s in olddoc['sections'] if s['title'][0].isdigit()}
    assert oldids=={r['old_section'] for r in migration['sections']}
    for row in migration['sections']:
        assert row['new_rules'] and set(row['new_rules'])<=set(lookup)
        assert row['old_basis_sha256']==digest(section_basis(olddoc,row['old_section'])[1].encode())
        assert all(row['old_section'] in lookup[target]['old_sections'] for target in row['new_rules'])
    previous=json.loads((root/'atlas/section2_migration.json').read_text(encoding='utf-8'))
    assert previous['new_sha256']==migration['old_sha256'] and previous['new_source']==migration['old_source']
    all_rules=compile_rules(root)
    for stage in stages:
        compact=compile_rules(root,stage=stage)
        selected={r['section'] for r in compact['rules']}
        assert selected==stages|{r['id'] for r in rules if r['stage']==stage}
        assert compact['characters']<all_rules['characters']<=12000
        assert len(compact['omitted'])==len(rules)-sum(r['stage']==stage for r in rules)
    return spec


def walk(spec, events=None, origin=None):
    """Synthetic routing exercise. Supplied outcomes are not execution evidence."""
    lookup={r['id']:r for r in spec['rules']};events={k:list(v) for k,v in (events or {}).items()}
    at=spec['entry'];visited=[]
    for _ in range(150):
        if at in ('done','wait'):return at,visited
        visited.append(at)
        outcomes=events.get(at,[]);outcome=outcomes.pop(0) if outcomes else 'pass'
        assert outcome in ('pass','fail','unknown')
        at=lookup[at]['on_'+outcome]
        if at=='return_origin':
            assert origin in lookup and not origin.startswith('8.')
            at=origin
    raise AssertionError('Non-terminating scenario')


def scenarios(spec):
    results={}
    end,path=walk(spec);assert end=='done' and '8.1' not in path and '7.3' in path
    results['normal_completion']=end
    end,path=walk(spec,{'6.1':['fail','pass']},'6.1')
    assert end=='done' and path.count('6.1')==2 and path.index('8.3')<path.index('9.1')
    results['invalid_inference_then_recheck']=end
    for name,at in [('missing_data','2.2'),('unavailable_practice','7.1')]:
        end,path=walk(spec,{at:['unknown']});assert end=='wait' and '9.1' not in path
        results[name]=end
    end,path=walk(spec,{'7.3':['fail','pass']},'2.3')
    assert end=='done' and path.count('2.3')==2 and path.count('3.2')==2 and path.count('7.1')==2
    results['changed_premise_repeats_dependencies']=end
    return results


if __name__=='__main__':
    spec=validate(ROOT)
    print(json.dumps({'stages':len(spec['stages']),'rules':len(spec['rules']),
        'scenarios':scenarios(spec),'scope':'structural and synthetic routes; not semantic proof or human acceptance','api_calls':0}))
    subprocess.run([sys.executable,'-X','utf8','scripts/verify_correctness_revision.py'],cwd=ROOT,check=True)
