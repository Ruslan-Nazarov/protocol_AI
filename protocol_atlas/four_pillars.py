"""A bounded, offline four-pillar adapter for an actual append-only file.

The host pins the contract before a candidate is constructed. Candidates cannot
supply observations, paths, commands, premises or a free-form admitted answer.
This is a local demonstrator, not a sandbox or a general semantic truth checker.
"""
import copy
import hashlib
import os
from pathlib import Path
import tempfile

from protocol_atlas.logic import canonical, fields, require, select, sha, strict_json, verify

MAX_CANDIDATE_BYTES = 16000
SCOPE = 'One fresh local file; successful sequential byte appends; no other writers.'


def make_contract(initial=b'A', additions=(b'B', b'C')):
    """Trusted host operation: changing task data creates a different contract."""
    require(type(initial) is bytes and len(initial) <= 64, 'task', 'initial', '0–64 bytes')
    require(type(additions) in (tuple, list) and 1 <= len(additions) <= 4,
            'task', 'additions', '1–4 operations')
    require(all(type(b) is bytes and len(b) <= 64 for b in additions),
            'task', 'additions', '0–64 bytes per operation')
    symbols = [{'id':f'state{i}', 'symbol':f'S{i}',
                'meaning':f'The file has the predicted exact bytes after {i} append operations.'}
               for i in range(len(additions)+1)]
    premises = [{'id':'initial', 'formula':'S0',
                 'basis':{'kind':'assumption','reason':'Fresh file initialization is checked by reading bytes.'}}]
    for i in range(1, len(symbols)):
        premises.append({'id':f'append{i}', 'formula':['implies',f'S{i-1}',f'S{i}'],
                         'basis':{'kind':'assumption','reason':
                                  'A successful append adds exactly the fixed bytes; no other writer intervenes. '
                                  'The byte transition is checked before execution and compared with actual reads.'}})
    logical = {'id':'file-append', 'version':1, 'profile':'classical-propositional-v1',
               'scope':SCOPE, 'selection_reason':'Finite conditional transitions; modus ponens is sufficient.',
               'alternatives':[{'profile':'syllogistic-universal-v1',
                                'reason_not_selected':'Class inclusion does not express these state transitions.'}],
               'enabled_rules':['modus_ponens','and_intro','and_left','and_right'],
               'symbols':symbols, 'sources':{}, 'premises':premises}
    return {'adapter':'file-append-v1', 'world':{
        'object':'fresh-file', 'unit':'byte', 'initial_hex':initial.hex(),
        'events':[{'id':f'append{i}', 'operation':'append', 'hex':b.hex()}
                  for i,b in enumerate(additions,1)], 'conditions':SCOPE},
        'logic':select(logical), 'reality':{
            'observer':'close-and-reopen-read-bytes-v1',
            'support':'Every observed state equals its predeclared byte prediction.',
            'refute':'Any successfully observed state differs from its prediction.',
            'unknown':'An operation or observation fails.',
            'alternatives':['write or read failure','interference by another writer','wrong byte interpretation']},
        'budget':{'candidate_bytes':MAX_CANDIDATE_BYTES,'attempts':1,'api_calls':0}}


def validate_contract(contract):
    # Reconstruct from task data, rejecting edited premises/conditions/limits.
    world = contract['world']
    expected = make_contract(bytes.fromhex(world['initial_hex']),
                             [bytes.fromhex(e['hex']) for e in world['events']])
    require(canonical(contract) == canonical(expected), 'contract', '$',
            'Host contract must exactly match the supported adapter and current checker.')
    return contract


def example_candidate(contract):
    """A fixture for the offline example; never called to repair a failed candidate."""
    validate_contract(contract)
    value = bytes.fromhex(contract['world']['initial_hex'])
    states, steps = [], []
    for i,event in enumerate(contract['world']['events'],1):
        before = value
        value += bytes.fromhex(event['hex'])
        states.append({'event':event['id'], 'before_hex':before.hex(), 'after_hex':value.hex()})
        steps.append({'id':f'derived{i}', 'rule':'modus_ponens',
                      'inputs':['initial' if i==1 else f'derived{i-1}',event['id']], 'formula':f'S{i}'})
    return {'contract_sha256':sha(canonical(contract)), 'world':'fresh-file',
            'development':states, 'logic':{
                'contract_sha256':contract['logic']['sha256'], 'scope':SCOPE,
                'steps':steps, 'conclusions':[steps[-1]['id']]},
            'reality':'close-and-reopen-read-bytes-v1'}


def _predict(raw, contract):
    require(isinstance(raw,str) and len(raw.encode('utf-8'))<=MAX_CANDIDATE_BYTES,
            'candidate_limit','$','Candidate exceeds byte budget.')
    candidate = strict_json(raw)
    fields(candidate, ('contract_sha256','world','development','logic','reality'), '$')
    require(candidate['contract_sha256']==sha(canonical(contract)), 'stale_contract','$','Pinned contract differs.')
    require(candidate['world']==contract['world']['object'], 'world','$','Object identity differs.')
    require(candidate['reality']==contract['reality']['observer'], 'reality','$','Required observation was replaced.')
    states = candidate['development']
    require(isinstance(states,list) and len(states)==len(contract['world']['events']),
            'development','$','Every subject transition is required.')
    value = bytes.fromhex(contract['world']['initial_hex'])
    predictions = [value]
    for state,event in zip(states,contract['world']['events']):
        fields(state,('event','before_hex','after_hex'),'development')
        require(state['event']==event['id'] and state['before_hex']==value.hex(),
                'development','before','Wrong event or preceding subject state.')
        value += bytes.fromhex(event['hex'])
        require(state['after_hex']==value.hex(), 'development','after','Append must retain all previous bytes.')
        predictions.append(value)
    proof = verify(canonical(candidate['logic']),contract['logic'])
    require(proof['admitted'], 'logic','$','Formal proof rejected: '+canonical(proof['violations']))
    require([c['formula'] for c in proof['conclusions']]==[f'S{len(states)}'],
            'logic','$','Proof must conclude the final subject state, not an unrelated fact.')
    return predictions, proof


def _write(path, value, append):
    with path.open('ab' if append else 'xb') as stream:
        require(stream.write(value)==len(value),'write','file','Partial write')
        stream.flush()
        os.fsync(stream.fileno())


def _observe(path):
    # A fresh handle, not the predicted buffer or writer's return value.
    return path.read_bytes()


def run(raw, pinned_contract):
    """Validate first, then execute and observe; never admit a supplied report.

    TemporaryDirectory owns the path. The candidate cannot select external files
    or commands. Reports are observations of this run, not reusable admission tokens.
    """
    report = {'status':'rejected','admitted':False,'answer':'','observations':[],
              'phases':['received'],'api_calls':0,
              'limits':'One local run; no claim of general semantic correctness, hidden model reasoning, '
                       'future persistence, exclusion of outside writers, or protection against editing this code.'}
    try:
        contract = copy.deepcopy(validate_contract(pinned_contract))
        report['contract_sha256'] = sha(canonical(contract))
        report['adapter_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        report['phases'].append('contract_pinned')
        predictions, proof = _predict(raw,contract)
        report.update(candidate_sha256=sha(raw), logic=proof)
        report['phases'].append('prediction_checked')
    except (ValueError,TypeError,KeyError,RecursionError) as exc:
        report['reason'] = str(exc)
        return report
    try:
        with tempfile.TemporaryDirectory(prefix='protocol-four-pillars-') as directory:
            path = Path(directory)/'subject.bin'
            report['phases'].append('execution_started')
            events = [{'id':'initial','hex':contract['world']['initial_hex']}, *contract['world']['events']]
            for i,event in enumerate(events):
                _write(path,bytes.fromhex(event['hex']),append=i>0)
                observed = _observe(path)
                report['observations'].append({'event':event['id'], 'expected_hex':predictions[i].hex(),
                    'actual_hex':observed.hex(),'sha256':hashlib.sha256(observed).hexdigest(),
                    'origin':'local_file_read','matched':observed==predictions[i]})
                if observed != predictions[i]:
                    report.update(status='contradicted',reason='Observed bytes differ; dependent execution stopped.')
                    return report
            report['phases'].append('reality_checked')
    except (OSError,ValueError) as exc:
        report.update(status='unverified',reason=str(exc))
        return report
    changes = ' → '.join(v.hex() or '∅' for v in predictions)
    additions = ', '.join(e['hex'] or '∅' for e in contract['world']['events'])
    report.update(status='admitted',admitted=True,answer=(
        f'В этом запуске файл изменился так (байты hex): {changes}. '
        f'Последовательные добавления {additions} сохранили прежние байты и дописали новые. '
        'Прогноз получен из закреплённых переходов по modus ponens; предпосылки — успешная запись '
        'и отсутствие вмешательства. После каждой операции файл закрыт и прочитан заново; '
        'наблюдения совпали с прогнозом. Вывод относится к этим состояниям данного запуска.'))
    report['phases'].append('admitted')
    return report
