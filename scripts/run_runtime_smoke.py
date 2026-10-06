"""Isolated real-client smoke test; generated projects and reports stay in build/."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from protocol_atlas.runtime_install import install
from protocol_atlas.project_runtime import ProjectRuntime


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex',type=Path,required=True)
    args=parser.parse_args()
    project=ROOT/'build'/('runtime-smoke-'+uuid.uuid4().hex[:8]);project.mkdir(parents=True)
    install(project,'codex',ROOT)
    (project/'sample.json').write_text(json.dumps([{'track':'AI'},{'track':'AI'},{'track':'Fintech'}]),encoding='utf-8')
    prompt=('Это изолированный интеграционный тест установленного протокола. '
            'В sample.json три тестовые сессии. Получи stats.json с общим количеством и количеством по трекам. '
            'Работай как с обычной новой задачей: сам составь план и критерии, выполни и проверь результат. '
            'Используй подключённый протокол в этом рабочем чате, без ручных форм атласа. '
            'Никакого человеческого принятия ещё не было. Не подключай внешние API и не изменяй файлы вне этой папки. '
            'Это тест на синтетических данных, а не программа реальной конференции.')
    # This invocation runs only vetted project hooks installed above. No persisted trust changes.
    command=[str(args.codex),'exec','--ephemeral','--json','--ignore-user-config','--skip-git-repo-check',
             '--dangerously-bypass-hook-trust','-s','workspace-write',
             '-c','mcp_servers.protocol_ai.command='+json.dumps(sys.executable),
             '-c','mcp_servers.protocol_ai.args='+json.dumps([str(project/'.protocol/engine/runner.py'),'mcp','--project',str(project)],ensure_ascii=False),
             '-c','projects.'+json.dumps(str(project),ensure_ascii=False)+'.trust_level="trusted"',
             '-C',str(project),'-o',str(project/'last-message.txt'),prompt]
    print(json.dumps({'project':str(project),'status':'running'},ensure_ascii=False),flush=True)
    with (project/'client-events.jsonl').open('w',encoding='utf-8') as output,(project/'client-stderr.txt').open('w',encoding='utf-8') as errors:
        process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=output,stderr=errors)
        try:code=process.wait(timeout=240)
        except subprocess.TimeoutExpired:
            process.kill();process.wait();code=-1
    state=ProjectRuntime(project).status()
    stats=json.loads((project/'stats.json').read_text(encoding='utf-8')) if (project/'stats.json').is_file() else None
    report={'project':str(project),'client_exit_code':code,'stats':stats,
            'state_revision':state['revision'],'tasks':[{k:t[k] for k in ('goal','status','stages')} for t in state['tasks']],
            'observed_host_events':state['diagnostics']['observed_host_events']}
    (project/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'project':str(project),'exit_code':code,'stats':stats,'statuses':[t['status'] for t in state['tasks']],
                      'events':report['observed_host_events']},ensure_ascii=False),flush=True)
    if code or stats is None or not state['tasks'] or any(t['status']!='awaiting_review' for t in state['tasks']):raise SystemExit(1)


if __name__=='__main__':main()
