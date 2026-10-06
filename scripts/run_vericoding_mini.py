"""Bounded, single-attempt instruction pilot; --preflight and --replay are free.

Not the authors' official harness; conservative syntax screening can reject
valid programs. Only existing formal specifications are checked, not intent.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from protocol_atlas.providers import saved_connection
from protocol_atlas.editor_ai import NoRedirect

RUN = ROOT / 'runs/vericoding-mini-20261004'
DAFNY = ROOT / 'build/vericoding-mini/tool/dafny/dafny.exe'
SYSTEM = '''Implement the supplied Dafny 4.11 specification. Return exactly a JSON
object with keys code and helpers, both strings. code is the complete method
body including outer braces; helpers contains any needed helper declarations.
The harness preserves the preamble and specification exactly. Only vc-code and
vc-helpers contents are replaced. Supply a verifiable implementation and any
proof annotations. Do not use assume, axiom, extern, include, attributes, comments,
strings, Unicode escapes, or verification bypasses. No tools are available to you;
the harness will run Dafny afterwards, with no repair attempts. Do not claim you
ran checks. Return only JSON, with no prose outside it.'''


def save(name, obj):
    (RUN / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(path):
    start = time.monotonic()
    try:
        p = subprocess.run([str(DAFNY), 'verify', str(path), '--verification-time-limit', '10'],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=25)
        log = p.stdout + p.stderr
        return dict(passed=p.returncode == 0 and bool(re.search(r'\b[1-9]\d* verified, 0 errors', log)),
                    exit_code=p.returncode, log=log, seconds=time.monotonic()-start)
    except subprocess.TimeoutExpired:
        return dict(passed=False, exit_code=None, log='Harness timeout 25 seconds', seconds=time.monotonic()-start)


def render(template, raw):
    obj = json.loads(raw)
    if set(obj) != {'code','helpers'} or not all(isinstance(v,str) for v in obj.values()):
        raise ValueError('Expected only code and helpers strings')
    for value in obj.values():
        # Deliberately strict mini-pilot interface, identical in both arms.
        if re.search(r'\b(assume|axiom|extern|include|opaque|reveal|module|import)\b|\{:|//|/\*|\*/|["\\#]',value) or not value.isascii():
            raise ValueError('Restricted syntax or potential verification bypass')
        depth=0
        for char in value:
            depth += (char == '{') - (char == '}')
            if depth < 0: raise ValueError('Escapes template block')
        if depth: raise ValueError('Unbalanced braces')
    if not obj['code'].strip().startswith('{') or not obj['code'].strip().endswith('}'):
        raise ValueError('Expected braced body')
    result=template
    for key in ('helpers','code'):
        pattern=rf'(?<=// <vc-{key}>).*?(?=// </vc-{key}>)'
        result,n=re.subn(pattern, lambda m:'\n'+obj[key]+'\n', result, flags=re.S)
        if n != 1: raise ValueError('Unexpected template')
    return result


def preflight():
    if not DAFNY.exists(): raise RuntimeError('Dafny is not installed; no API calls made')
    version=subprocess.check_output([str(DAFNY),'--version'],text=True).strip()
    if not version.startswith('4.11.0'): raise RuntimeError('Unexpected Dafny version')
    tests={}
    for name,body in [('valid','method M() returns (r:int) ensures r == 1 { r := 1; }'),
                      ('invalid','method M() returns (r:int) ensures r == 1 { r := 2; }')]:
        p=RUN/(name+'.dfy');p.write_text(body,encoding='utf-8');tests[name]=verify(p)
    plan=json.loads((RUN/'plan.json').read_text(encoding='utf-8'))
    if sha(RUN/'PROTOCOL.snapshot.md') != plan['protocol_sha256']: raise RuntimeError('Snapshot changed')
    for task in plan['tasks']:
        p=RUN/(task['id']+'.dfy')
        if sha(p)!=task['sha256']: raise RuntimeError('Task changed')
        # Original holes intentionally assume false. This tests template validity,
        # never counts the hole as an implemented/verified solution.
        tests[task['id']]=verify(p)
    ok=tests['valid']['passed'] and not tests['invalid']['passed'] and all(tests[t['id']]['passed'] for t in plan['tasks'])
    save('preflight.json',dict(version=version,passed=ok,checks=tests))
    return ok


def evaluate(cid, arm, response):
    template=(RUN/(cid+'.dfy')).read_text(encoding='utf-8')
    try:
        code=render(template,response.get('text',''))
    except (ValueError,TypeError) as e:
        return dict(passed=False,kind='interface_rejection',log=str(e))
    path=RUN/(cid+'-'+arm+'.dfy');path.write_text(code,encoding='utf-8')
    return dict(kind='dafny',**verify(path))


def report(rows):
    known=[r['cost_usd'] for r in rows if r.get('cost_usd') is not None]
    return dict(calls=len(rows),reserved_usd=len(rows)*.06,
        estimated_cost_usd=sum(known) if len(known)==len(rows) else None,
        arms={a:dict(attempts=sum(r['arm']==a for r in rows),
            passed=sum(r['arm']==a and r.get('verification',{}).get('passed',False) for r in rows))
            for a in ('baseline','protocol_text_only')},
        superiority=None,scope='Two tasks, single attempt, protocol text only; not full runtime or official benchmark score')


def run():
    if (RUN/'observations.json').exists(): raise RuntimeError('Existing reservations: no automatic rerun')
    if not preflight(): raise RuntimeError('Preflight failed; no API calls made')
    plan=json.loads((RUN/'plan.json').read_text(encoding='utf-8'))
    snapshot=(RUN/'PROTOCOL.snapshot.md').read_text(encoding='utf-8')
    prompts=[]
    for cid,arm in plan['schedule']:
        msgs=[{'role':'system','content':SYSTEM}]
        if arm=='protocol_text_only':
            msgs.append({'role':'system','content':'Apply the following protocol within the fixed single-response interface. External tools and persistence are supplied by the harness; do not invent their execution.\n'+snapshot})
        msgs.append({'role':'user','content':(RUN/(cid+'.dfy')).read_text(encoding='utf-8')})
        if len(json.dumps(msgs,ensure_ascii=False).encode())>180000: raise RuntimeError('Input bound exceeded')
        prompts.append(dict(case=cid,arm=arm,messages=msgs))
    if len(prompts)!=4 or plan['budget_usd']!=.24: raise RuntimeError('Unexpected budget/schedule')
    save('prompts.json',prompts)
    rows=[]
    for item in prompts:
        s=saved_connection(ROOT)
        if not s or (s['provider'],s['model'],s['endpoint'].rstrip('/'))!=('openai','gpt-5-mini','https://api.openai.com/v1'):
            raise RuntimeError('Saved connection changed')
        row=dict(case=item['case'],arm=item['arm'],status='reserved',cost_usd=None)
        rows.append(row);save('observations.json',rows)
        start=time.monotonic()
        try:
            payload=dict(model=s['model'],messages=item['messages'],max_completion_tokens=4000,
                         response_format={'type':'json_object'},stream=False)
            req=urllib.request.Request(s['endpoint'].rstrip('/')+'/chat/completions',
                data=json.dumps(payload,ensure_ascii=False).encode(),
                headers={'Content-Type':'application/json','Authorization':'Bearer '+s['api_key']})
            with urllib.request.build_opener(NoRedirect()).open(req,timeout=60) as res:
                raw=res.read(2_000_001)
            if len(raw)>2_000_000: raise ValueError('Oversized response')
            # Preserve content including length-limited responses and usage.
            data=json.loads(raw.decode().replace(s['api_key'],'[REDACTED]'))
            save(item['case']+'-'+item['arm']+'.response.json',data)
            choice=data['choices'][0];usage=data.get('usage',{})
            response=dict(text=choice.get('message',{}).get('content') or '',finish_reason=choice.get('finish_reason'),model=data.get('model'))
            it,ot=usage.get('prompt_tokens'),usage.get('completion_tokens')
            cost=(it*.25+ot*2)/1e6 if type(it)is int and type(ot)is int else None
            row.update(status='completed',response=response,usage=usage,cost_usd=cost,seconds=time.monotonic()-start)
            row['verification']=evaluate(item['case'],item['arm'],response)
        except Exception as e:
            row.update(status='failed',error_type=type(e).__name__,seconds=time.monotonic()-start)
            save('observations.json',rows);save('report.json',report(rows))
            raise RuntimeError('Attempt failed; reserved, no retry: '+type(e).__name__) from None
        save('observations.json',rows);save('report.json',report(rows))
        print(json.dumps({k:row[k] for k in ('case','arm','status','cost_usd')},ensure_ascii=False),flush=True)
        if row['cost_usd'] is None or row['cost_usd']>.06: raise RuntimeError('Unknown/excess usage; stop')
    return report(rows)


def replay():
    if not preflight(): raise RuntimeError('Preflight failed')
    rows=json.loads((RUN/'observations.json').read_text(encoding='utf-8'))
    plan=json.loads((RUN/'plan.json').read_text(encoding='utf-8'))
    if len(rows)>4: raise RuntimeError('Too many calls')
    if [[r['case'],r['arm']] for r in rows] != plan['schedule'][:len(rows)]:
        raise RuntimeError('Schedule mismatch')
    for row in rows:
        if row['status']=='completed':
            raw=json.loads((RUN/(row['case']+'-'+row['arm']+'.response.json')).read_text(encoding='utf-8'))
            if (raw['choices'][0]['message'].get('content') or '') != row['response']['text']:
                raise RuntimeError('Raw response mismatch')
            usage=raw.get('usage',{})
            it,ot=usage.get('prompt_tokens'),usage.get('completion_tokens')
            cost=(it*.25+ot*2)/1e6 if type(it)is int and type(ot)is int else None
            if cost!=row['cost_usd'] or cost is not None and cost>.06:
                raise RuntimeError('Usage mismatch or budget exceeded')
            result=evaluate(row['case'],row['arm'],row['response'])
            if result['passed']!=row['verification']['passed']: raise RuntimeError('Replay mismatch')
    save('replay.json',report(rows))
    return report(rows)


if __name__=='__main__':
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--preflight',action='store_true');g.add_argument('--run',action='store_true');g.add_argument('--replay',action='store_true')
    args=p.parse_args()
    result=run() if args.run else replay() if args.replay else dict(preflight=preflight())
    print(json.dumps(result,ensure_ascii=False))
