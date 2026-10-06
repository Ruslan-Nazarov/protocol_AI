"""Offline demonstration. Persist the contract and predictions BEFORE execution."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from protocol_atlas.four_pillars import make_contract, example_candidate, run
from protocol_atlas.logic import canonical


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--save',action='store_true',help='Save a fresh run under runs/four-pillars (never overwrite).')
    args=parser.parse_args()
    contract=make_contract()
    candidate=example_candidate(contract)
    raw=canonical(candidate)
    output=None
    if args.save:
        from datetime import datetime,timezone
        import uuid
        output=ROOT/'runs/four-pillars'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
        output.mkdir(parents=True,exist_ok=False)
        for name,value in [('contract',contract),('candidate',candidate),('proof',candidate['logic'])]:
            (output/(name+'.json')).write_text(canonical(value),encoding='utf-8')
    report=run(raw,contract)
    if output:
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':report['status'],'answer':report['answer'],'api_calls':0,
                      'directory':str(output) if output else None},ensure_ascii=False))
    return 0 if report['admitted'] else 1


if __name__=='__main__':raise SystemExit(main())
