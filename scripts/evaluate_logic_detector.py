"""Evaluate a fixed reference corpus; no calls to a live model."""
import copy
import json
from pathlib import Path
import sys
import time
import argparse
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from protocol_atlas.logic import select, verify, sha, canonical
from protocol_atlas.evaluation import summarize

def run():
    corpus=json.loads((ROOT/'examples/logic/detection-corpus.json').read_text(encoding='utf-8'))
    contract=json.loads((ROOT/'examples/logic/syllogism.json').read_text(encoding='utf-8'))
    records=[];reports=[]
    for case in corpus['cases']:
        c=copy.deepcopy(contract);c['symbols'][0]['symbol']=case['symbol'];c['premises'][0]['formula'][1]=case['symbol']
        selected=select(c)
        value={'contract_sha256':'0'*64 if case.get('stale') else selected['sha256'],'scope':c['scope'],
               'steps':[{'id':'t1','rule':case.get('rule','barbara'),'inputs':case.get('inputs',['p1','p2']),'formula':case['formula']}],
               'conclusions':['t1']}
        raw=json.dumps(value,ensure_ascii=False);start=time.perf_counter()
        report=verify(raw,selected);elapsed=(time.perf_counter()-start)*1000
        records.append(dict(run_id=corpus['version'],case_id=case['id'],cluster_id='authored_syllogism_family',
            reference_origin=corpus['reference_origin'],violation=case['violation'],detected=not report['admitted'],admitted=report['admitted'],
            task_success=None,violation_at_ms=None,detected_at_ms=None,cost_usd=0,latency_ms=elapsed))
        reports.append({'case_id':case['id'],'selection':selected,'report':report})
    return {'manifest':{'corpus_sha256':sha(canonical(corpus)),'version':corpus['version'],'model_calls':0,
                        'cost_scope':'API only; developer and CPU cost excluded','property':corpus['property']},
            'records':records,'reports':reports,'metrics':summarize(records,[c['id'] for c in corpus['cases']])}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path);args=p.parse_args()
    result=run()
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result['metrics'],ensure_ascii=False))
    raise SystemExit(bool(result['metrics']['counts']['fp'] or result['metrics']['counts']['fn']))
