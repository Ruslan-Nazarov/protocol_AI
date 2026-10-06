"""Run the logic adapter and drift traps locally; no model or network required."""
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from protocol_atlas.logic import select, verify


def candidate(selection):
    return {'contract_sha256': selection['sha256'], 'scope': selection['contract']['scope'],
            'steps': [{'id': 't1', 'rule': 'barbara', 'inputs': ['p1', 'p2'], 'formula': ['all', 'S', 'P']}],
            'conclusions': ['t1']}


def mutations(good):
    result = {}
    def add(name, change):
        value = copy.deepcopy(good); change(value); result[name] = value
    add('S_to_G', lambda c: c['steps'][0]['formula'].__setitem__(1, 'G'))
    add('unicode_lookalike', lambda c: c['steps'][0]['formula'].__setitem__(1, 'Ѕ'))
    add('reversed_conclusion', lambda c: c['steps'][0].__setitem__('formula', ['all', 'P', 'S']))
    add('some_instead_of_all', lambda c: c['steps'][0]['formula'].__setitem__(0, 'some'))
    add('different_rule', lambda c: c['steps'][0].__setitem__('rule', 'modus_ponens'))
    add('missing_premise', lambda c: c['steps'][0].__setitem__('inputs', ['absent', 'p2']))
    add('stale_contract', lambda c: c.__setitem__('contract_sha256', '0'*64))
    add('changed_scope', lambda c: c.__setitem__('scope', 'Другой предмет'))
    add('unsupported_prose', lambda c: c.__setitem__('text', 'Все G являются P.'))
    return result


def run():
    contract = json.loads((ROOT/'examples/logic/syllogism.json').read_text(encoding='utf-8'))
    selection = select(contract)
    good = candidate(selection)
    reports = {'valid': verify(json.dumps(good, ensure_ascii=False), selection)}
    for name, value in mutations(good).items():
        reports[name] = verify(json.dumps(value, ensure_ascii=False), selection)
    assert reports['valid']['admitted']
    assert all(not r['admitted'] for n, r in reports.items() if n != 'valid')
    return {'selection': selection, 'candidate': good, 'reports': reports,
            'note': 'Deterministic injected faults; this does not measure a live model drift rate.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = run()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({n: {'admitted': r['admitted'], 'violations': r['violations']} for n, r in report['reports'].items()}, ensure_ascii=False, indent=2))
