"""Freeze a tiny comparison plan; no model calls or installation.

The full current protocol is supplied only to the protocol instruction arm.
This does not exercise the interactive runtime and is not a leaderboard run.
"""
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'runs/vericoding-mini-20261004'
COMMIT = '387cd69996792d452ead7b0460f36ee4c5cdd148'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    RUN.mkdir(parents=True, exist_ok=True)
    existing = RUN / 'plan.json'
    if existing.exists():
        frozen = json.loads(existing.read_text(encoding='utf-8'))
        assert digest(RUN/'PROTOCOL.snapshot.md') == frozen['protocol_sha256']
        for task in frozen['tasks']:
            assert digest(RUN/(task['id']+'.dfy')) == task['sha256']
        print(json.dumps({'status':'frozen_plan_validated','planned_calls':frozen['calls'],
                          'budget_usd':frozen['budget_usd']}))
        return
    snapshot = RUN / 'PROTOCOL.snapshot.md'
    if not snapshot.exists():
        shutil.copyfile(ROOT / 'PROTOCOL.md', snapshot)
    tasks = []
    for ident in ('DA0000', 'DA0001'):
        source = ROOT / 'build/vericoding-mini' / (ident + '.dfy')
        target = RUN / (ident + '.dfy')
        if not target.exists():
            shutil.copyfile(source, target)
        assert digest(source) == digest(target), 'Do not overwrite changed tasks'
        text = target.read_text(encoding='utf-8')
        assert text.count('// <vc-code>') == text.count('// </vc-code>') == 1
        tasks.append(dict(id=ident, sha256=digest(target),
            url=f'https://raw.githubusercontent.com/Beneficial-AI-Foundation/vericoding-benchmark/{COMMIT}/specs/{ident}_specs.dfy'))
    plan = dict(schema_version=1, status='prepared_not_run', benchmark_commit=COMMIT,
        tasks=tasks, selection='First two Dafny spec filenames; no model outcomes used for selection',
        protocol_sha256=digest(snapshot), model='gpt-5-mini', provider='openai',
        conditions=['baseline', 'protocol_text_only'],
        schedule=[['DA0000','baseline'],['DA0000','protocol_text_only'],
                  ['DA0001','protocol_text_only'],['DA0001','baseline']],
        calls=4, repeats=1, automatic_retries=0, max_output_tokens=4000,
        max_request_utf8_bytes=180000, reserved_usd_per_call=0.06, budget_usd=0.24,
        input_usd_per_million=0.25, output_usd_per_million=2,
        price_source='https://developers.openai.com/api/docs/models/gpt-5-mini',
        preconditions=['Complete Dafny 4.11.0 installation and verify version',
            'Run known valid and invalid verifier controls',
            'Check source templates compile; stop on invalid specification, never silently repair it',
            'Recheck saved provider/model/endpoint and pricing before spending',
            'Freeze exact identical task/output prompts; only protocol text differs',
            'Persist reservation before every API call; do not retry unknown outcomes'],
        admission=['Only generated helper and code blocks may change; preserve specification',
            'Reject assumptions, axioms, verification disabling and other proof bypasses',
            'Dafny verification must succeed within a fixed timeout for both arms',
            'Save raw responses, generated files, verifier logs, timings and token usage'],
        limits=['Preparation only; no responses generated or checked',
            'Two public tasks, one attempt per condition: no statistical superiority claim',
            'Instruction comparison only, not the complete protocol runtime',
            'Formal conformance does not establish real-world adequacy of specification'])
    path = RUN / 'plan.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8')) == plan, 'Plan already frozen'
    else:
        path.write_text(json.dumps(plan, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(status=plan['status'], tasks=len(tasks), planned_calls=4,
                         budget_usd=0.24, actual_api_calls=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
