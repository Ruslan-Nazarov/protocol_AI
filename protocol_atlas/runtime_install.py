"""Workspace installation and optional host lifecycle observations."""
import json
import base64
from pathlib import Path
import re
import shutil
import sys
import io
import zipfile

from protocol_atlas.catalog import digest
from protocol_atlas.project_runtime import ProjectRuntime, canonical, stamp
from protocol_atlas.runtime_rules import compile_rules
from protocol_atlas.translations import write_json
from protocol_atlas.configuration import current_configuration

CLIENTS = {'codex':'AGENTS.md','claude':'CLAUDE.md','gemini':'GEMINI.md','generic':'AGENTS.md'}
START='<!-- protocol-ai:start -->'
END='<!-- protocol-ai:end -->'
EVENTS=('SessionStart','UserPromptSubmit','PreToolUse','PostToolUse','Stop','Interrupt')


def safe_write(path, value):
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):raise ValueError('Нельзя заменять ссылку: '+str(path))
    path.parent.mkdir(parents=True,exist_ok=True)
    if isinstance(value,str):path.write_text(value,encoding='utf-8')
    else:write_json(path,value)


def is_protocol_hook(command):
    if ' -EncodedCommand ' in command:
        try:
            command=base64.b64decode(command.rsplit(' -EncodedCommand ',1)[1],validate=True).decode('utf-16-le')
        except (ValueError, UnicodeError):
            return False
    return 'engine/runner.py' in command.replace('\\','/') and ' hook ' in command


def install(project,client='codex',source=None):
    if client not in (*CLIENTS,'api','files'):raise ValueError('Неизвестный клиент.')
    source=Path(source or Path(__file__).resolve().parents[1]).resolve()
    runtime=ProjectRuntime(project)
    configuration = current_configuration(source if (source/'PROTOCOL.md').is_file() else runtime.root)
    target_configuration = runtime.folder/'configuration.json'
    if configuration and target_configuration.is_file():
        if json.loads(target_configuration.read_text(encoding='utf-8')) != configuration:
            raise ValueError('В рабочем проекте уже другая настройка. Сначала согласуйте её замену; прежняя сохранена.')
    if not runtime.status()['installed']:runtime.dispatch('init')
    engine=runtime.folder/'engine'
    if engine.is_symlink() or not engine.resolve().is_relative_to(runtime.root):raise ValueError('Недопустимое место установки.')
    package=engine/'protocol_atlas'
    if package.is_symlink():raise ValueError('Недопустимый каталог движка.')
    package.mkdir(parents=True,exist_ok=True)
    # Code only; never the atlas databases, project memory, keys or historical runs.
    names=('__init__.py','project_runtime.py','runtime_cli.py','runtime_install.py','runtime_rules.py','logic.py',
           'catalog.py','source_editor.py','translations.py','translation_history.py','ui_messages.py','workflows.py','configuration.py')
    for name in names:
        target=package/name
        if target.is_symlink():raise ValueError('Файл движка заменён ссылкой.')
        original=source/'protocol_atlas'/name
        if original.resolve()!=target.resolve():shutil.copyfile(original,target)
    for name in ('runtime_dashboard.html','runtime_dashboard.js','runtime_dashboard.css'):
        original=source/'protocol_atlas/web'/name
        target=package/'web'/name
        if original.is_file() and original.resolve()!=target.resolve():safe_write(target,original.read_text(encoding='utf-8'))
    runner=engine/'runner.py'
    safe_write(runner,"from protocol_atlas.runtime_cli import main\nif __name__=='__main__': main()\n")
    manifest=compile_rules(source) if (source/'PROTOCOL.md').is_file() else json.loads((runtime.folder/'rules.json').read_text(encoding='utf-8'))
    safe_write(runtime.folder/'rules.json',manifest)
    if configuration:
        target = runtime.folder/'configuration.json'
        if target.is_file():
            previous = json.loads(target.read_text(encoding='utf-8'))
        else:
            safe_write(target, configuration)
        # Keep the project's own profile. Its authoritative source is recorded.
        if configuration.get('reader') and not (runtime.root/'memory/READER.md').exists():
            reader = configuration['reader']
            content = '# Профиль читателя\n\nИсточник: .protocol/configuration.json, версия '+str(reader['revision'])+'.\n\n'
            content += json.dumps(reader, ensure_ascii=False, indent=2)+'\n'
            safe_write(runtime.root/'memory/READER.md',content)
    skill_source=source/'skills/protocol-work'
    skill_target=runtime.folder/'skills/protocol-work'
    if skill_source.is_dir():
        for original in skill_source.rglob('*'):
            if original.is_file():
                target=skill_target/original.relative_to(skill_source)
                safe_write(target,original.read_text(encoding='utf-8'))
    instruction=(START+'\nРабота по протоколу подключена к этому проекту.\n'
                 'Перед содержательной задачей прочитай .protocol/skills/protocol-work/SKILL.md.\n'
                 'Текущее состояние получи командой python .protocol/engine/runner.py context --project .\n'
                 'При отсутствии python используй py -3. Выполняй работу в этом чате, без переноса в атлас.\n'
                 'Формы постановки заполняет агент; замечания и принятие берутся из реальных сообщений человека.\n'+END+'\n')
    if client in CLIENTS:
        path=runtime.root/CLIENTS[client]
        old=path.read_text(encoding='utf-8') if path.is_file() else ''
        if START in old:
            if END not in old:raise ValueError('Повреждён блок протокола в инструкции.')
            old=re.sub(re.escape(START)+r'.*?'+re.escape(END)+r'\n?',lambda _:instruction,old,flags=re.S)
        else:old=old.rstrip()+'\n\n'+instruction if old.strip() else instruction
        safe_write(path,old)
    hooks_status='not_applicable'
    if client=='codex':
        codex=runtime.root/'.codex'
        if codex.is_symlink():raise ValueError('Недопустимый каталог конфигурации.')
        path=codex/'hooks.json'
        value=json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {'hooks':{}}
        hooks=value.setdefault('hooks',{})
        if sys.platform == 'win32':
            # Codex's command-hook launcher uses COMSPEC (cmd.exe), regardless
            # of the shell used for agent tools. Keep its command free of
            # nested quotes and pass Unicode paths literally inside PowerShell.
            quote=lambda value: "'"+str(value).replace("'", "''")+"'"
            script='& '+quote(sys.executable)+' '+quote(runner)+' hook --project '+quote(runtime.root)+'; exit $LASTEXITCODE'
            encoded=base64.b64encode(script.encode('utf-16-le')).decode('ascii')
            command='powershell.exe -NoProfile -NonInteractive -EncodedCommand '+encoded
        else:
            command='"'+sys.executable+'" "'+str(runner)+'" hook --project "'+str(runtime.root)+'"'
        for event in EVENTS:
            groups=hooks.setdefault(event,[])
            groups[:]=[g for g in groups if not any(is_protocol_hook(h.get('command','')) for h in g.get('hooks',[]))]
            groups.append({'hooks':[{'type':'command','command':command,'timeout':3 if event=='Interrupt' else 10}]})
        safe_write(path,value)
        config=codex/'config.toml'
        old=config.read_text(encoding='utf-8') if config.is_file() else ''
        config_start='# protocol-ai:mcp:start'
        config_end='# protocol-ai:mcp:end'
        block=(config_start+'\n[mcp_servers.protocol_ai]\ncommand = '+json.dumps(sys.executable)+'\nargs = '+
               json.dumps([str(runner),'mcp','--project',str(runtime.root)],ensure_ascii=False)+'\n'+config_end+'\n')
        if config_start in old:
            if config_end not in old:raise ValueError('Повреждён блок MCP.')
            old=re.sub(re.escape(config_start)+r'.*?'+re.escape(config_end)+r'\n?',lambda _:block,old,flags=re.S)
        elif re.search(r'^\s*\[mcp_servers\.protocol_ai\]',old,re.M):
            raise ValueError('Имя MCP protocol_ai уже занято. Существующая конфигурация сохранена.')
        else:old=old.rstrip()+'\n\n'+block
        safe_write(config,old)
        # Native skill discovery, as well as the explicit project instruction.
        for original in skill_target.rglob('*'):
            if original.is_file():safe_write(runtime.root/'.agents/skills/protocol-work'/original.relative_to(skill_target),original.read_text(encoding='utf-8'))
        hooks_status='requires_client_trust'
    current=runtime.status()
    result=runtime.dispatch('connection',{'expected_revision':current['revision'],'client':client,
          'capabilities':{'read':True,'write':client!='files','execute':client in CLIENTS or client=='api','lifecycle_declared':client=='codex'},
          'observed_events':[]})
    safe_write(runtime.folder/'PACKAGE.json',runtime.dispatch('export'))
    return {'project':str(runtime.root),'project_id':result['state']['project_id'],'client':client,
            'runner':str(runner),'hooks':hooks_status,'state_revision':result['state']['revision'],
            'mcp':{'command':sys.executable,'args':[str(runner),'mcp','--project',str(runtime.root)]},
            'package':str(runtime.folder/'PACKAGE.json'),'atlas_memory_copied':False}


def bundle(source):
    """Portable code and rules. No project identifiers, histories or credentials."""
    source=Path(source)
    result=io.BytesIO()
    names=('__init__.py','project_runtime.py','runtime_cli.py','runtime_install.py','runtime_rules.py','logic.py',
           'catalog.py','source_editor.py','translations.py','translation_history.py','ui_messages.py','workflows.py','configuration.py')
    with zipfile.ZipFile(result,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in names:archive.write(source/'protocol_atlas'/name,'.protocol/engine/protocol_atlas/'+name)
        for name in ('runtime_dashboard.html','runtime_dashboard.js','runtime_dashboard.css'):
            archive.write(source/'protocol_atlas/web'/name,'.protocol/engine/protocol_atlas/web/'+name)
        for original in (source/'skills/protocol-work').rglob('*'):
            if original.is_file():archive.write(original,'.protocol/skills/protocol-work/'+original.relative_to(source/'skills/protocol-work').as_posix())
        archive.writestr('.protocol/engine/runner.py',"from protocol_atlas.runtime_cli import main\nif __name__=='__main__': main()\n")
        archive.writestr('.protocol/rules.json',json.dumps(compile_rules(source),ensure_ascii=False))
        configuration = current_configuration(source)
        if configuration:
            archive.writestr('.protocol/configuration.json', json.dumps(configuration, ensure_ascii=False, indent=2))
        archive.writestr('install_protocol.py',"import sys\nfrom pathlib import Path\nsys.path.insert(0,str(Path(__file__).resolve().parent/'.protocol/engine'))\nfrom protocol_atlas.runtime_cli import main\nif __name__=='__main__': main()\n")
    return result.getvalue()


def hook(runtime,payload):
    kind=payload.get('hook_event_name','unknown')
    if kind not in EVENTS:return {}
    if not runtime.status()['installed']:return {}
    tool=payload.get('tool_name')
    args=payload.get('tool_input',{})
    response=payload.get('tool_response',{})
    # Host observations do not increment workflow revisions or race agent mutations.
    ident=digest(canonical([kind,payload.get('session_id'),payload.get('turn_id'),payload.get('tool_use_id'),args,payload.get('prompt')]).encode())
    details={'client':'codex','event':kind,'session_id':payload.get('session_id'),'turn_id':payload.get('turn_id'),
             'tool':tool,'input_sha256':digest(canonical(args).encode()),'response_sha256':digest(canonical(response).encode()),
             'origin':'host_hook','at':stamp()}
    if isinstance(response,dict):
        details['exit_code']=response.get('exit_code')
    with runtime.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS host_events (id TEXT PRIMARY KEY, kind TEXT NOT NULL, body TEXT NOT NULL)')
        db.execute('INSERT OR IGNORE INTO host_events VALUES (?,?,?)',(ident,kind,canonical(details)))
        limit=runtime._load(db).get('storage_policy',{}).get('host_event_limit',2000)
        db.execute('DELETE FROM host_events WHERE rowid NOT IN (SELECT rowid FROM host_events ORDER BY rowid DESC LIMIT ?)',(limit,))
    state=runtime.status()
    if kind in ('SessionStart','UserPromptSubmit'):
        instruction=(runtime.folder/'skills/protocol-work/SKILL.md').read_text(encoding='utf-8')
        context=runtime.dispatch('context')['text']
        rules=json.loads((runtime.folder/'rules.json').read_text(encoding='utf-8'))['text']
        # Full compiled rules are supplied at session start; user turns receive only current state.
        additional=context+'\n\n'+instruction+(('\n\n'+rules) if kind=='SessionStart' else '')
        return {'hookSpecificOutput':{'hookEventName':kind,'additionalContext':additional}}
    active=next((t for t in state['tasks'] if t['id']==state.get('active_task')),None)
    if kind=='Interrupt' and active and active['status'] in ('planning','running'):
        runtime.dispatch('interrupt',{'expected_revision':state['revision'],'reason':'Клиент сообщил об остановке текущего ответа.',
                                     'request_id':'interrupt-'+ident})
    if kind=='Stop' and not payload.get('stop_hook_active'):
        task=next((t for t in state['tasks'] if t['id']==state.get('active_task')),None)
        if task and task['status'] in ('planning','running'):
            return {'decision':'block','reason':'Заверши учёт текущего этапа протокола: сохрани выполненную проверку и результат либо зафиксируй interrupt с причиной незавершённости. Не выдумывай успешную проверку.'}
    return {}
