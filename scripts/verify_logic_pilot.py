"""Recompute saved pilot statistics and replay raw answers with current checker."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_logic_pilot import report,reference,RESERVE,LIMIT
from protocol_atlas.logic import select,verify,sha,canonical

folder=ROOT/'runs/logic-pilot-20261004'
manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
observations=json.loads((folder/'observations.json').read_text(encoding='utf-8'))
saved=json.loads((folder/'report.json').read_text(encoding='utf-8'))
assert report(manifest,observations)==saved
assert len(observations)==len(manifest['schedule'])==12
assert len(observations)*RESERVE<=LIMIT
for item in observations:
    assert item['status']=='completed'
    case=next(c for c in manifest['cases'] if c['id']==item['case_id'])
    assert sha(canonical(item['messages']))==item['messages_sha256']
    assert reference(item['response']['text'],case)==item['task_reference_passed']
    old=item['logic_report']
    assert old['raw']==item['response']['text'] and old['raw_sha256']==sha(old['raw'])
    assert old['checker_sha256']==manifest['checker_sha256']
    # A replay is fresh local evidence, not an edit of the original experiment.
    current=verify(old['raw'],select(case['selection']['contract']))
    assert current['admitted']==old['admitted']
    assert canonical(current['conclusions'])==canonical(old['conclusions'])
known=sum(i['estimated_cost_usd'] for i in observations)
print(json.dumps({'calls':len(observations),'task_success':sum(i['task_reference_passed'] for i in observations),
                  'estimated_api_cost_usd':round(known,9),'raw_preserved':True,'current_checker_replay':'pass',
                  'superiority':'not_established','latent_logic_use':'not_measured'}))
