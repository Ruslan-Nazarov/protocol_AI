"""Client-independent project workflow. Transports call this one state machine."""
from contextlib import contextmanager
from datetime import datetime, timezone
import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import time
import uuid

from protocol_atlas.catalog import digest
from protocol_atlas.source_editor import SourceConflict
from protocol_atlas.translations import write_json
from protocol_atlas.workflows import validate_plan
from protocol_atlas.logic import select as select_logic, verify as verify_logic, checker_version, PROFILES, LIMITS


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def stamp():
    return datetime.now(timezone.utc).isoformat()


def changes(before, after, path=''):
    """Only changed leaves/subtrees; existing tasks are not copied into every event."""
    old, new = {}, {}
    if before == after:return old,new
    if isinstance(before,dict) and isinstance(after,dict):
        for key in before.keys() | after.keys():
            pointer=path+'/'+key.replace('~','~0').replace('/','~1')
            if key not in before:new[pointer]=after[key]
            elif key not in after:old[pointer]=before[key]
            else:
                a,b=changes(before[key],after[key],pointer);old.update(a);new.update(b)
    elif isinstance(before,list) and isinstance(after,list) and len(after)>=len(before):
        for i,value in enumerate(after):
            pointer=path+'/'+str(i)
            if i>=len(before):new[pointer]=value
            else:
                a,b=changes(before[i],value,pointer);old.update(a);new.update(b)
    else:old[path]=before;new[path]=after
    return old,new


def string(value, label, limit=20000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or '\0' in value:
        raise ValueError('Нужно непустое поле '+label)
    return value.strip()


class ProjectRuntime:
    """State and evidence belong to a workspace, never to the atlas installation."""
    actions = ('init', 'status', 'context', 'start', 'plan', 'begin_stage', 'check',
               'observe', 'complete_stage', 'review', 'interrupt', 'connection', 'export', 'import', 'storage',
               'select_logic', 'check_logic', 'logic_profiles', 'set_verification', 'admit_result')

    def __init__(self, root):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError('Рабочая папка проекта не найдена.')
        self.folder = self.root/'.protocol'
        self.path = self.folder/'project.sqlite3'
        if self.folder.is_symlink() or self.path.is_symlink() or not self.path.resolve().is_relative_to(self.root):
            raise ValueError('Недопустимое хранилище проекта.')

    @contextmanager
    def db(self,write=True):
        if self.folder.is_symlink() or self.path.is_symlink() or not self.path.resolve().is_relative_to(self.root):
            raise ValueError('Хранилище проекта изменилось.')
        self.folder.mkdir(exist_ok=True)
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            if write:db.executescript('''
                CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS objects (sha TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, at TEXT NOT NULL,
                    action TEXT NOT NULL, request_id TEXT UNIQUE NOT NULL, request_sha TEXT NOT NULL,
                    before_sha TEXT, after_sha TEXT NOT NULL, details TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS receipts (request_id TEXT PRIMARY KEY, response TEXT NOT NULL);
            ''')
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _load(self, db):
        row = db.execute('SELECT body FROM state WHERE id=1').fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def _object(db, value):
        raw = canonical(value)
        sha = digest(raw.encode())
        db.execute('INSERT OR IGNORE INTO objects VALUES (?,?)', (sha, raw))
        return sha

    def file(self, name):
        if not isinstance(name, str) or not name or '\\' in name or name.startswith('/'):
            raise ValueError('Артефакт задаётся относительным путём проекта.')
        path = self.root/name
        first = name.split('/')[0]
        if first in ('.protocol', '.git', '.env') or first.startswith('.env.') or ':' in name or any(p in ('..', '.', '') for p in name.split('/')):
            raise ValueError('Этот путь не является рабочим артефактом.')
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ValueError('Артефакт выходит за пределы проекта.')
        return path

    def snapshot(self, names):
        if not isinstance(names, list) or len(names) > 200:
            raise ValueError('Список артефактов: до 200 файлов.')
        result = {}
        for name in names:
            path = self.file(name)
            if not path.is_file():
                raise ValueError('Артефакт не найден: '+name)
            result[name] = digest(path.read_bytes())
        return result

    def view(self, state,scope=None):
        result = copy.deepcopy(state)
        for task in result['tasks']:
            if scope is not None and task['id'] not in scope:continue
            by_id = {s['id']:s for s in task['stages']}
            changed = set()
            for stage in task['stages']:
                reasons = []
                if stage.get('result') and stage['result'].get('verification_version',0) != stage.get('verification',{}).get('version',0):
                    reasons.append('Изменён режим проверки этапа.')
                if stage.get('result') and stage.get('logic_selection'):
                    if not self.logic_check_current(stage):
                        reasons.append('Логическая проверка отсутствует, не пройдена или устарела.')
                    elif stage['result'].get('logic_check_id') != stage['logic_checks'][-1]['id']:
                        reasons.append('Изменилась проверенная версия логического вывода.')
                if stage.get('result'):
                    for name, sha in stage['result']['artifacts'].items():
                        path = self.file(name)
                        if not path.is_file() or digest(path.read_bytes()) != sha:
                            reasons.append('Изменён или недоступен '+name)
                if any(dep in changed for dep in stage['requires']):
                    reasons.append('Изменён входной результат этапа.')
                if stage.get('result'):
                    for dep,sha in stage['result'].get('input_versions',{}).items():
                        if by_id[dep]['status'] not in ('verified','accepted') or digest(canonical(by_id[dep].get('result')).encode())!=sha:
                            reasons.append('Изменена проверенная версия входного этапа '+dep)
                if reasons or stage['status'] == 'needs_recheck':
                    changed.add(stage['id'])
                    stage.update(status='needs_recheck', recheck_reasons=reasons or stage.get('recheck_reasons', []))
                elif stage['status'] in ('ready', 'blocked'):
                    blocked = [dep for dep in stage['requires'] if by_id[dep]['status'] not in ('verified','accepted')
                               or by_id[dep].get('gate') == 'human' and by_id[dep]['status'] != 'accepted']
                    stage.update(status='blocked' if blocked else 'ready', blockers=blocked)
                stage['evidence_summary'] = self.evidence_summary(stage)
            if changed:
                task['status'] = 'needs_recheck'
            task['next_stage'] = next((s['id'] for s in task['stages'] if s['status'] in ('running','ready','needs_recheck','interrupted') and
                                      all(by_id[d]['status'] in ('verified','accepted') and (by_id[d]['gate']!='human' or by_id[d]['status']=='accepted') for d in s['requires'])), None)
        result['installed'] = True
        result['artifact_validation_scope']='all' if scope is None else 'active_and_requested_task'
        result['experience']=self.experience(result)
        return result

    def evidence_summary(self, stage):
        """Computed properties only; narrative claims cannot grant these statuses."""
        checks = stage.get('logic_checks', [])
        formal = 'not_checked'
        if checks:
            report = checks[-1]['report']
            formal = 'passed' if self.logic_check_current(stage) else 'stale' if report.get('admitted') else 'failed'
            if formal == 'failed' and any(v['code'] in ('formula_syntax','candidate_limit') for v in report.get('violations',[])):
                formal = 'unsupported'
        return {'schema_version':1, 'mode':stage.get('verification',{}).get('mode','legacy_criteria'),
                'mode_explicit':bool(stage.get('verification')), 'formal_conformance':formal,
                'premise_truth':'not_checked', 'source_translation':'not_checked',
                'actual_model_logic_use':'not_checked',
                'stage_criteria':'passed' if stage['status'] in ('verified','accepted') else 'not_established',
                'contract_sha256':stage.get('logic_selection',{}).get('sha256'),
                'control_scope':'registered_stage_only', 'external_enforcement':False,
                'trust_boundary':'Workspace owner can change checker, state and reference; no OS isolation.'}

    @staticmethod
    def experience(state):
        """Scoped observations; no invented numeric C/D or cross-model learning."""
        groups={}
        for task in state['tasks']:
            executor=task.get('executor',{})
            if not executor.get('model') or executor['model']=='unknown' or not executor.get('client'):continue
            for stage in task['stages']:
                key=(executor['client'],executor['model'],stage['type'])
                row=groups.setdefault(key,{'client':key[0],'model':key[1],'type':key[2],'accepted':0,'failed_checks':0,'corrections':0,'recommendation':None})
                row['accepted']+=stage['status']=='accepted'
                row['failed_checks']+=sum(c['passed'] is False and c['origin']=='executed' for c in stage['checks'])
                row['corrections']+=sum(f['outcome'] in ('revise','rejected') and stage['id'] in f['stage_ids'] and f.get('origin')!='imported' for f in task['feedback'])
        for row in groups.values():
            if row['failed_checks'] or row['corrections']:
                row['recommendation']='Уменьшить объём следующего этапа этого типа; сохранить отдельную проверку причины предыдущей ошибки.'
            elif row['accepted']>=5:
                row['recommendation']='Есть пять принятых этапов. Возможна одна ограниченная проба большего объёма с явной проверкой; предел автоматически не повышается.'
            else:row['recommendation']='Опыт ограничен. Не повышать объём или самостоятельность по одному успеху.'
        return list(groups.values())

    def status(self,scope=None):
        if not self.path.is_file():
            return {'installed':False,'tasks':[], 'connections':[], 'revision':0}
        with self.db(write=False) as db:
            state = self._load(db)
            count = db.execute('SELECT count(*) FROM events').fetchone()[0]
            host_table = db.execute("SELECT name FROM sqlite_master WHERE name='host_events'").fetchone()
            host_counts = {row[0]:row[1] for row in db.execute('SELECT kind,count(*) FROM host_events GROUP BY kind')} if host_table else {}
        if not state:return {'installed':False,'tasks':[], 'connections':[], 'revision':0}
        result = self.view(state,{state.get('active_task')} if scope=='active' else scope)
        result['diagnostics'] = {'database_bytes':self.path.stat().st_size, 'workflow_events':count,
                                 'observed_host_events':host_counts, 'storage_policy':state.get('storage_policy',{'host_event_limit':2000,'workflow_event_limit':2000,'command_output':'errors'})}
        return result

    def _task(self, state, payload):
        ident = payload.get('task_id') or state.get('active_task')
        task = next((t for t in state['tasks'] if t['id'] == ident), None)
        if task is None:
            raise ValueError('Задача не найдена.')
        return task

    def _stage(self, state, payload):
        task = self._task(state, payload)
        stage = next((s for s in task['stages'] if s['id'] == payload.get('stage_id')), None)
        if stage is None:
            raise ValueError('Этап не найден.')
        return task, stage

    def _stages(self, stages):
        if not isinstance(stages, list) or any(not isinstance(s,dict) for s in stages):
            raise ValueError('Этапы составляет агент; нужен список stages.')
        order = validate_plan([{k:s.get(k) for k in ('id','title','requires')} for s in stages])
        values = {s['id']:s for s in stages}
        result = []
        for item in order:
            value = values[item['id']]
            criteria = value.get('criteria')
            if not isinstance(criteria, list) or not 1 <= len(criteria) <= 30:
                raise ValueError('Каждому этапу нужны критерии проверки.')
            seen = set()
            for criterion in criteria:
                if not isinstance(criterion, dict) or criterion.get('kind') not in ('command','agent_review','human'):
                    raise ValueError('Вид проверки: command, agent_review или human.')
                ident = string(criterion.get('id'), 'criterion.id', 60)
                if ident in seen:
                    raise ValueError('Повтор критерия.')
                seen.add(ident)
                string(criterion.get('text'), 'criterion.text', 3000)
            gate = value.get('gate','automatic')
            if gate not in ('automatic','human'):
                raise ValueError('Неизвестный способ перехода этапа.')
            result.append({**item, 'type':string(value.get('type'),'type',200),
                           'volume':string(value.get('volume'),'volume',3000),
                           'complexity':string(value.get('complexity'),'complexity',3000),
                           'criteria':criteria, 'gate':gate, 'status':'ready', 'checks':[], 'result':None})
        return result

    def _context(self, state):
        task = next((t for t in reversed(state['tasks']) if t['id']==state.get('active_task')), None)
        lines = ['Проект: '+state['name'], 'Версия состояния: '+str(state['revision'])]
        if task:
            lines += ['Цель: '+task['goal'], 'Статус: '+task['status']]
            for stage in task['stages']:
                lines.append(stage['id']+' · '+stage['title']+' · '+stage['status'])
                if stage.get('logic_selection'):
                    selection = stage['logic_selection']
                    lines += ['Выбранная логика и адаптер этапа '+stage['id']+':', canonical(selection),
                              'Язык, семантика и реализованные правила: '+canonical(PROFILES[selection['contract']['profile']]),
                              'Используйте check_logic; вывод действителен условно относительно посылок.']
                else:
                    lines.append('Логика этапа явно не подключена; формальная выводимость не проверяется.')
                if stage.get('recheck_reasons'):
                    lines.append('; '.join(stage['recheck_reasons']))
            lines.append('Следующий этап: '+str(task.get('next_stage') or 'проверить готовность и решение человека'))
            if task.get('feedback'):
                lines.append('Последнее замечание человека: '+task['feedback'][-1]['message'])
            executor=task.get('executor',{})
            advice=[r for r in state.get('experience',[]) if r['client']==executor.get('client') and r['model']==executor.get('model')]
            for row in advice:lines.append('Опыт для '+row['type']+': '+row['recommendation'])
        lines.append('Техническая проверка и человеческое принятие — разные состояния. Сохраняйте свидетельства; используйте только актуальные входные результаты.')
        rules = self.folder/'rules.json'
        if rules.is_file():
            manifest=json.loads(rules.read_text(encoding='utf-8'))
            lines.append('Правила проекта: .protocol/rules.json; версия '+str(manifest.get('sha256',manifest.get('registry_sha256','сохранена при подключении')))+'. Прочитайте text перед постановкой новой задачи.')
        configuration_path = self.folder/'configuration.json'
        # Runtime restoration reads the installed snapshot, never the atlas database.
        configuration = None
        if configuration_path.is_file():
            if configuration_path.is_symlink():
                raise ValueError('Недопустимая настройка рабочего проекта.')
            configuration = json.loads(configuration_path.read_text(encoding='utf-8'))
            lines += ['Подключённая настройка и профиль читателя (.protocol/configuration.json):',
                      canonical(configuration), 'Если в memory/READER.md есть более новое решение человека, восстановите его и согласуйте расхождение до использования прежнего профиля.']
        reader_path = self.root/'memory/READER.md'
        reader_source = None
        if reader_path.is_file():
            if reader_path.is_symlink() or not reader_path.resolve().is_relative_to(self.root):
                raise ValueError('Недопустимый профиль рабочего проекта.')
            raw = reader_path.read_bytes()
            reader_source = {'path':'memory/READER.md', 'sha256':digest(raw), 'text':raw.decode('utf-8')}
            lines += ['Профиль из памяти именно этого рабочего проекта; SHA-256 '+reader_source['sha256']+':', reader_source['text']]
        return {'state':self.response_state(state),'text':'\n'.join(lines), 'configuration':configuration, 'reader_source':reader_source}

    @staticmethod
    def response_state(state,target=None):
        """Normal turns need the current task, not every past task's full evidence."""
        result=copy.deepcopy({k:v for k,v in state.items() if k!='tasks'})
        result['task_count']=len(state['tasks'])
        result['tasks']=copy.deepcopy([t for t in state['tasks'] if t['id'] in (state.get('active_task'),target)])
        result['state_scope']='active_and_requested_task'
        return result

    def dispatch(self, action, payload=None):
        payload = {} if payload is None else payload
        if action not in self.actions or not isinstance(payload, dict):
            raise ValueError('Неизвестная операция протокола.')
        if action == 'logic_profiles':
            return {'profiles':copy.deepcopy(PROFILES),'checker_sha256':checker_version(),'limits':LIMITS}
        if action == 'admit_result':
            state = self.status()
            _, stage = self._stage(state, payload)
            if stage['status'] not in ('verified','accepted') or not self.logic_check_current(stage):
                raise ValueError('Результат не имеет актуального формального допуска.')
            checked = stage['logic_checks'][-1]
            if stage['result'].get('logic_check_id') != checked['id'] or any(
                    checked['artifacts'].get(n) != h for n,h in stage['result']['artifacts'].items()):
                raise ValueError('Свидетельство не связано с предъявленным результатом.')
            report = checked['report']
            return {'schema_version':1,'stage_id':stage['id'],'logic_check_id':checked['id'],
                    'answer':report['answer'],'conclusions':report['conclusions'],
                    'artifacts':stage['result']['artifacts'],'evidence':self.evidence_summary(stage)}
        if action in ('status','context','export'):
            state = self.status(scope='active' if action=='context' else None)
            if action == 'status':return state
            if not state['installed']:raise ValueError('Сначала подключите протокол к проекту.')
            if action == 'context':return self._context(state)
            content = {'schema_version':1, 'project_id':state['project_id'], 'base_revision':state['revision'],
                       'state':state, 'context':self._context(state)['text'], 'operations':[],
                       'limitations':'Для продолжения добавьте operations и пересчитайте sha256 от остальных полей: UTF-8 JSON, sort_keys=True, separators=(comma,colon), ensure_ascii=False. Команды из пакета не исполняются; отчёты потребуют локальной проверки.'}
            instructions=[]
            for name in ('skills/protocol-work/SKILL.md','skills/protocol-work/references/contract.md','rules.json'):
                path=self.folder/name
                if path.is_file():
                    value=path.read_text(encoding='utf-8')
                    instructions.append(json.loads(value)['text'] if name=='rules.json' else value)
            content['agent_instructions']='\n\n'.join(instructions)
            content['reply_template']={'expected_revision':state['revision'],'reply':{'schema_version':1,
                                      'project_id':state['project_id'],'base_revision':state['revision'],'operations':[]}}
            content['limitations']+=' Для текстового чата проще вернуть reply_template с operations: пересчитывать контрольную сумму исходного пакета не нужно.'
            return {**content, 'sha256':digest(canonical(content).encode())}
        request_id = payload.get('request_id') or uuid.uuid4().hex
        string(request_id,'request_id',200)
        request_sha = digest(canonical([action,payload]).encode())
        replay = None
        with self.db() as db:
            old_event = db.execute('SELECT * FROM events WHERE request_id=?',(request_id,)).fetchone()
            if old_event:
                if old_event['request_sha'] != request_sha:
                    raise SourceConflict('Повторный request_id содержит другое действие.')
                receipt=json.loads(db.execute('SELECT response FROM receipts WHERE request_id=?',(request_id,)).fetchone()[0])
                stored=self._load(db)
                replay = {'state':self.response_state(self.view(stored,{stored.get('active_task'),payload.get('task_id')}),payload.get('task_id')), 'operation':receipt['operation'], 'applied_revision':receipt['applied_revision']}
            if replay is not None:
                result = replay
            else:
                try:result = self._mutate(db,action,payload,request_id,request_sha)
                except (KeyError,TypeError,AttributeError) as exc:raise ValueError('Некорректная структура операции: '+str(exc)) from exc
        self.materialize()
        return result

    def _mutate(self,db,action,payload,request_id,request_sha):
            before = self._load(db)
            if before is None:
                if action not in ('init','import'):
                    raise ValueError('Сначала подключите протокол к проекту.')
                before = {'project_id':uuid.uuid4().hex, 'name':self.root.name, 'revision':0,
                          'tasks':[], 'connections':[], 'active_task':None}
            if action != 'init' and payload.get('expected_revision') != before['revision']:
                raise SourceConflict('Состояние проекта изменилось. Перечитайте context; данные не потеряны.')
            state = self.view(before,{before.get('active_task'),payload.get('task_id')})
            state.pop('installed',None)
            state.pop('experience',None)
            state.pop('artifact_validation_scope',None)
            details = self._apply(state, action, payload)
            state['revision'] = before['revision']+1
            state['updated_at'] = stamp()
            db.execute('INSERT INTO state VALUES (1,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',(canonical(state),))
            before_delta,after_delta=changes(before,state)
            db.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?,?)',
                       (state['revision'],stamp(),action,request_id,request_sha,self._object(db,before_delta),self._object(db,after_delta),canonical(details)))
            result = {'state':self.response_state(self.view(state,{state.get('active_task'),payload.get('task_id')}),payload.get('task_id')), 'operation':details, 'applied_revision':state['revision']}
            db.execute('INSERT INTO receipts VALUES (?,?)',(request_id,canonical({'operation':details,'applied_revision':state['revision']})))
            limit=state.get('storage_policy',{}).get('workflow_event_limit',2000)
            db.execute('DELETE FROM events WHERE seq NOT IN (SELECT seq FROM events ORDER BY seq DESC LIMIT ?)',(limit,))
            db.execute('DELETE FROM receipts WHERE request_id NOT IN (SELECT request_id FROM events)')
            db.execute('DELETE FROM objects WHERE sha NOT IN (SELECT before_sha FROM events UNION SELECT after_sha FROM events)')
            return result

    def _apply(self, state, action, payload):
        if action == 'init':
            state['name'] = string(payload.get('name',state['name']),'name',300)
            return {'kind':'project_initialized'}
        if action == 'connection':
            name = string(payload.get('client'),'client',100)
            capabilities = payload.get('capabilities',{})
            if not isinstance(capabilities, dict) or any(type(v) is not bool for v in capabilities.values()):
                raise ValueError('Возможности подключения задаются флагами.')
            item = {'client':name,'capabilities':capabilities,'last_seen':stamp(),
                    'observed_events':[], 'declaration_origin':'client_configuration'}
            old = next((c for c in state['connections'] if c['client']==name), None)
            if old:state['connections'].remove(old)
            state['connections'].append(item)
            return item
        if action == 'storage':
            limit=payload.get('host_event_limit',2000)
            if type(limit) is not int or not 0<=limit<=100000:
                raise ValueError('Хранить 0–100000 событий среды.')
            workflow_limit=payload.get('workflow_event_limit',state.get('storage_policy',{}).get('workflow_event_limit',2000))
            if type(workflow_limit) is not int or not 100<=workflow_limit<=100000:raise ValueError('Хранить 100–100000 изменений состояния.')
            output=payload.get('command_output',state.get('storage_policy',{}).get('command_output','errors'))
            if output not in ('none','errors','all'):raise ValueError('Вывод команд: none, errors или all.')
            state['storage_policy']={'host_event_limit':limit,'workflow_event_limit':workflow_limit,'command_output':output}
            return {'kind':'storage_policy_changed','policy':state['storage_policy'],
                    'note':'Сохраняются контрольные суммы и служебные события. Полные диалоги и копии файлов не записываются.'}
        if action == 'start':
            goal = string(payload.get('goal'),'goal')
            stages = self._stages(payload.get('stages',[])) if payload.get('stages') else []
            executor=payload.get('executor',{'client':'unknown','model':'unknown'})
            if not isinstance(executor,dict) or any(not isinstance(executor.get(k),str) for k in ('client','model')):raise ValueError('Исполнитель: client и model; неизвестную модель обозначьте unknown.')
            task = {'id':uuid.uuid4().hex,'goal':goal,'executor':executor,'status':'running' if stages else 'planning',
                    'stages':stages,'created_at':stamp(),'feedback':[], 'observations':[]}
            state['tasks'].append(task);state['active_task']=task['id']
            return {'task_id':task['id'],'kind':'task_started','requires_agent_plan':not stages}
        if action == 'plan':
            task = self._task(state,payload)
            state['active_task']=task['id']
            previous={s['id']:s for s in task['stages']}
            stages=self._stages(payload.get('stages'))
            if any((s.get('logic_selection') or s.get('verification')) and s['id'] not in {v['id'] for v in stages} for s in previous.values()):
                raise ValueError('Нельзя удалить этап с выбранной логикой через замену плана; сохраните его и оформите пересмотр.')
            preserved=[]
            fields=('id','title','requires','type','volume','complexity','criteria','gate')
            for index,item in enumerate(stages):
                old=previous.get(item['id'])
                if old and all(old[key]==item[key] for key in fields):
                    stages[index]=old;preserved.append(item['id'])
                elif old and old.get('logic_selection'):
                    for key in ('logic_selection', 'logic_history', 'logic_checks'):
                        if key in old:stages[index][key]=old[key]
                if old and old.get('verification'):
                    stages[index]['verification']=old['verification']
                    stages[index]['verification_history']=old.get('verification_history',[])
                if old and old.get('result_history'):
                    stages[index]['result_history']=old['result_history']
            task['stages'] = stages
            task['status'] = 'accepted' if all(s['status']=='accepted' for s in stages) else 'awaiting_review' if all(s['status'] in ('verified','accepted') for s in stages) else 'running'
            return {'kind':'plan_proposed','task_id':task['id'],'human_accepted':False,'preserved_stage_ids':preserved}
        if action == 'import':
            reply='reply' in payload
            package = payload.get('reply') if reply else payload.get('package')
            if not isinstance(package,dict) or package.get('schema_version') != 1:
                raise ValueError('Неизвестный пакет состояния.')
            if not reply:
                content = {k:v for k,v in package.items() if k!='sha256'}
                if digest(canonical(content).encode()) != package.get('sha256'):
                    raise ValueError('Пакет повреждён или изменён; нужно пересобрать sha256.')
            if state['revision'] and state['project_id'] != package['project_id']:
                raise SourceConflict('Пакет принадлежит другому проекту.')
            if state['revision'] and package['base_revision'] != state['revision']:
                raise SourceConflict('Пакет устарел. Соберите актуальное продолжение.')
            operations=package.get('operations',[])
            if not isinstance(operations,list) or len(operations)>100:
                raise ValueError('Пакет может содержать до 100 операций.')
            if operations:
                if not state['revision']:raise ValueError('Сначала импортируйте исходный снимок без операций.')
                allowed={'start','plan','begin_stage','check','complete_stage','observe','review','interrupt'}
                results=[]
                for operation in operations:
                    if not isinstance(operation,dict) or operation.get('action') not in allowed or not isinstance(operation.get('payload'),dict):
                        raise ValueError('Неизвестная операция файлового продолжения.')
                    if operation['action']=='check':
                        _, stage=self._stage(state,operation['payload'])
                        criterion=next((c for c in stage['criteria'] if c['id']==operation['payload'].get('criterion_id')),None)
                        if criterion and criterion['kind']=='command':
                            raise ValueError('Команда из пакета не запускается автоматически. Выполните локальный check через агент или API.')
                    results.append(self._apply(state,operation['action'],operation['payload']))
                return {'kind':'file_operations_applied','operations':results}
            if reply:raise ValueError('Файловый ответ не содержит операций.')
            incoming = copy.deepcopy(package['state'])
            if incoming.get('project_id') != package.get('project_id'):
                raise ValueError('Проект пакета не совпадает со снимком.')
            # Imported reports retain their origin; re-run command checks locally before a new result.
            if not isinstance(incoming.get('tasks'),list):raise ValueError('Нет задач в снимке.')
            for task in incoming.get('tasks',[]):
                string(task.get('id'),'task.id',100)
                string(task.get('goal'),'goal')
                validated=self._stages(task['stages']) if task.get('stages') else []
                original={s['id']:s for s in task.get('stages',[])}
                for stage in validated:
                    previous=original[stage['id']]
                    stage['result_history']=previous.get('result_history',[])
                    if previous.get('verification'):
                        policy=previous['verification']
                        if policy.get('mode') not in ('criteria','formal','empirical','manual') or type(policy.get('version')) is not int or policy['version']<1:
                            raise ValueError('Некорректный импорт режима проверки.')
                        stage['verification']=policy
                        stage['verification_history']=previous.get('verification_history',[])
                    if previous.get('logic_selection'):
                        stage['logic_selection']=select_logic(previous['logic_selection']['contract'])
                        stage['logic_history']=previous.get('logic_history',[])
                        stage['logic_checks']=previous.get('logic_checks',[])
                        for check in stage['logic_checks']:check['origin']='imported'
                    stage['checks']=previous.get('checks',[])
                    for check in stage['checks']:check['origin']='imported'
                    stage['result']=previous.get('result')
                    if stage['result']:
                        for path in stage['result']['artifacts']:self.file(path)
                    if stage['checks'] or stage['result']:
                        stage.update(status='needs_recheck',recheck_reasons=['Импортированное свидетельство требует локального подтверждения.'])
                task['stages']=validated
                task['status']='needs_recheck' if any(s['status']=='needs_recheck' for s in validated) else 'running' if validated else 'planning'
                for feedback in task.get('feedback',[]):feedback['origin']='imported'
            state.update({k:incoming[k] for k in ('project_id','name','tasks','active_task')})
            return {'kind':'state_imported','source_revision':incoming['revision']}
        task, stage = self._stage(state,payload) if action in ('begin_stage','check','complete_stage','select_logic','check_logic','set_verification') else (self._task(state,payload),None)
        if stage:
            by_id = {s['id']:s for s in task['stages']}
            if any(by_id[d]['status'] not in ('verified','accepted') or
                   by_id[d]['gate']=='human' and by_id[d]['status']!='accepted' for d in stage['requires']):
                raise ValueError('Входной результат не проверен или требует пересмотра.')
        if action == 'set_verification':
            mode=payload.get('mode')
            if mode not in ('criteria','formal','empirical','manual'):raise ValueError('Режим: criteria, formal, empirical или manual.')
            reason=string(payload.get('reason'),'reason')
            previous=stage.get('verification')
            if previous:stage.setdefault('verification_history',[]).append(copy.deepcopy(previous))
            stage['verification']={'mode':mode,'version':previous['version']+1 if previous else 1,'reason':reason,'at':stamp()}
            stage.update(status='needs_recheck',recheck_reasons=['Изменён режим проверки; нужны новые свидетельства.'])
            return {'kind':'verification_selected','verification':stage['verification']}
        if action == 'begin_stage':
            state['active_task']=task['id']
            if stage.get('result'):
                stage.setdefault('result_history',[]).append(copy.deepcopy(stage['result']))
                stage['result']=None
            stage['status']='running';stage['recheck_reasons']=[];task['status']='running'
            return {'kind':'stage_started','stage_id':stage['id']}
        if action == 'select_logic':
            selection=select_logic(payload.get('contract'))
            previous=stage.get('logic_selection')
            if previous:
                string(payload.get('change_reason'),'change_reason')
                if selection['sha256']!=previous['sha256'] and (
                        selection['contract']['id']!=previous['contract']['id'] or
                        selection['contract']['version']<=previous['contract']['version']):
                    raise ValueError('Изменение логики требует того же id и новой возрастающей версии договора.')
                stage.setdefault('logic_history',[]).append({'selection':previous,'at':stamp(),'reason':payload['change_reason']})
            stage['logic_selection']=selection
            stage.update(status='needs_recheck',recheck_reasons=['Выбрана или изменена логика; выполните check_logic.'])
            task['status']='needs_recheck'
            return {'kind':'logic_selected','stage_id':stage['id'],'selection':selection,'origin':'agent_selection'}
        if action == 'check_logic':
            if not stage.get('logic_selection'):raise ValueError('Сначала явно выберите логику этапа через select_logic.')
            if stage['status']!='running':raise ValueError('Сначала begin_stage для логической проверки.')
            name=string(payload.get('candidate_path'),'candidate_path',400)
            path=self.file(name)
            if path.stat().st_size>64000:raise ValueError('Кандидат превышает 64000 байт; разделите вывод.')
            artifacts=self.snapshot(payload.get('artifacts',[]))
            if name not in artifacts:raise ValueError('Включите candidate_path в проверяемые artifacts.')
            raw=path.read_text(encoding='utf-8')
            report=verify_logic(raw,stage['logic_selection'])
            after=self.snapshot(list(artifacts))
            if after!=artifacts:
                report.update(status='fail',admitted=False)
                report['violations'].append({'code':'artifact_changed','where':name,'detail':'Artifact changed during check'})
            check={'id':uuid.uuid4().hex,'at':stamp(),'origin':'executed','artifacts':artifacts,
                   'verification_version':stage.get('verification',{}).get('version',0),
                   'candidate_path':name,'report':report}
            stage.setdefault('logic_checks',[]).append(check)
            stage['status']='running';task['status']='running'
            return {'kind':'logic_checked','stage_id':stage['id'],'check':check}
        if action == 'check':
            criterion = next((c for c in stage['criteria'] if c['id']==payload.get('criterion_id')),None)
            if criterion is None:raise ValueError('Критерий не найден.')
            artifacts = self.snapshot(payload.get('artifacts',[]))
            kind = criterion['kind']
            if kind == 'command':
                argv = payload.get('argv')
                if not isinstance(argv,list) or not 1 <= len(argv) <= 100 or any(not isinstance(a,str) or '\0' in a for a in argv):
                    raise ValueError('Команда проверки задаётся списком аргументов.')
                timeout = payload.get('timeout',60)
                if type(timeout) is not int or not 1<=timeout<=120:raise ValueError('Таймаут проверки: 1–120 секунд.')
                started=time.monotonic()
                try:
                    process = subprocess.run(argv,cwd=self.root,capture_output=True,encoding='utf-8',errors='replace',
                                             timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    code,output,error=process.returncode,process.stdout+process.stderr,None
                except subprocess.TimeoutExpired as exc:
                    code,output,error=None,'','Превышен таймаут '+str(timeout)+' с.'
                except OSError as exc:
                    code,output,error=None,'',str(exc)
                try:after=self.snapshot(list(artifacts))
                except ValueError:after=None
                passed = code==0 and after==artifacts and error is None
                policy=state.get('storage_policy',{}).get('command_output','errors')
                keep_output=policy=='all' or policy=='errors' and not passed
                evidence = {'argv':argv,'exit_code':code,'output':output[-12000:] if keep_output else '',
                            'output_sha256':digest(output.encode()),'output_bytes':len(output.encode()),'output_policy':policy,
                            'duration_seconds':round(time.monotonic()-started,3),'error':error,
                            'changed_during_check':after!=artifacts}
                origin = 'executed'
            else:
                passed = payload.get('passed')
                if type(passed) is not bool:raise ValueError('Нужен явный исход проверки.')
                evidence = {'explanation':string(payload.get('evidence'),'evidence'),
                            'method':'human' if kind=='human' else 'agent_review'}
                origin = 'human_report' if kind=='human' else 'agent_report'
            check = {'id':uuid.uuid4().hex,'criterion_id':criterion['id'],'passed':passed,'kind':kind,
                     'origin':origin,'at':stamp(),'artifacts':artifacts,'evidence':evidence,
                     'verification_version':stage.get('verification',{}).get('version',0)}
            stage['checks'].append(check)
            stage['status']='running';task['status']='running'
            return {'kind':'check_recorded','check':check}
        if action == 'complete_stage':
            artifacts = self.snapshot(payload.get('artifacts',[]))
            mode=stage.get('verification',{}).get('mode','legacy_criteria')
            if mode=='formal' and not stage.get('logic_selection'):
                raise ValueError('Формальный режим требует select_logic и check_logic.')
            if mode=='empirical' and not any(c['kind']=='command' for c in stage['criteria']):
                raise ValueError('Эмпирический режим требует командного критерия.')
            if mode=='manual' and not any(c['kind'] in ('human','agent_review') for c in stage['criteria']):
                raise ValueError('Ручной режим требует содержательной проверки.')
            if stage.get('logic_selection'):
                if not self.logic_check_current(stage):raise ValueError('Нет успешной актуальной логической проверки.')
                logical=stage['logic_checks'][-1]
                if logical['candidate_path'] not in artifacts or any(logical['artifacts'].get(n)!=h for n,h in artifacts.items()):
                    raise ValueError('Логическая проверка должна связывать кандидат и все предъявленные артефакты.')
            for criterion in stage['criteria']:
                check = next((c for c in reversed(stage['checks']) if c['criterion_id']==criterion['id']),None)
                if check and check.get('verification_version',0)!=stage.get('verification',{}).get('version',0):
                    raise ValueError('Проверка относится к прежнему режиму: '+criterion['id'])
                if not check or not check['passed'] or check['origin']=='imported' or any(
                        not self.file(name).is_file() or digest(self.file(name).read_bytes())!=sha for name,sha in check['artifacts'].items()):
                    raise ValueError('Не пройден или устарел критерий '+criterion['id'])
                if any(check['artifacts'].get(name)!=sha for name,sha in artifacts.items()):
                    raise ValueError('Проверка не покрывает предъявленный артефакт '+criterion['id'])
            result = {'summary':string(payload.get('summary'),'summary'), 'artifacts':artifacts,
                      'verification_version':stage.get('verification',{}).get('version',0),
                      'checks':[c['id'] for c in stage['checks']], 'at':stamp(),
                      'input_versions':{d:digest(canonical(by_id[d]['result']).encode()) for d in stage['requires']}}
            if stage.get('logic_selection'):
                result.update(logic_check_id=stage['logic_checks'][-1]['id'],
                              logic_contract_sha256=stage['logic_selection']['sha256'])
            stage.update(result=result,status='verified',recheck_reasons=[])
            task['status']='awaiting_review' if all(s['status'] in ('verified','accepted') for s in task['stages']) else 'running'
            return {'kind':'stage_verified','stage_id':stage['id'],'human_accepted':False}
        if action == 'observe':
            event = {'id':payload.get('event_id') or uuid.uuid4().hex,'at':stamp(),
                     'kind':string(payload.get('kind'),'kind',100),'summary':string(payload.get('summary'),'summary',4000),
                     'origin':payload.get('origin','client_report'),'details':payload.get('details',{})}
            task['observations'].append(event)
            return event
        if action == 'interrupt':
            task['status']='interrupted'
            for item in task['stages']:
                if item['status']=='running':item['status']='interrupted'
            task['interruption']={'reason':string(payload.get('reason','Работа прервана клиентом.'),'reason',4000),'at':stamp()}
            return {'kind':'task_interrupted','task_id':task['id'],'interruption':task['interruption']}
        if action == 'review':
            outcome = payload.get('outcome')
            if outcome not in ('accepted','revise','rejected'):raise ValueError('Исход: accepted, revise или rejected.')
            message = string(payload.get('human_message'),'human_message')
            selected = payload.get('stage_ids') if 'stage_ids' in payload else [s['id'] for s in task['stages']]
            if not isinstance(selected,list) or not selected or any(not isinstance(i,str) for i in selected):raise ValueError('Укажите область замечания: stage_ids.')
            if any(i not in {s['id'] for s in task['stages']} for i in selected):raise ValueError('Этап замечания не найден.')
            if outcome=='accepted':
                if not selected or any(s['status'] not in ('verified','accepted') for s in task['stages'] if s['id'] in selected):
                    raise ValueError('Сначала проверка актуального результата, затем принятие человеком.')
                for stage in task['stages']:
                    if stage['id'] in selected:stage['status']='accepted'
                task['status']='accepted' if all(s['status']=='accepted' for s in task['stages']) else 'running'
            else:
                affected = set(selected)
                for stage in task['stages']:
                    if stage['id'] in affected or any(d in affected for d in stage['requires']):
                        affected.add(stage['id']);stage.update(status='needs_recheck',recheck_reasons=[message])
                task['status']='revise' if outcome=='revise' else 'rejected'
            item = {'outcome':outcome,'message':message,'stage_ids':selected,'at':stamp(),'origin':'human_message_via_client'}
            task['feedback'].append(item)
            return {'kind':'human_review','review':item}
        raise ValueError('Операция не реализована.')

    def logic_check_current(self, stage):
        """The newest failure cannot be bypassed by selecting an older success."""
        if not stage.get('logic_checks'):return False
        check=stage['logic_checks'][-1]
        selection=stage.get('logic_selection',{})
        report=check['report']
        try:
            return (check['origin']=='executed' and report['admitted'] is True and
                    check.get('verification_version',0)==stage.get('verification',{}).get('version',0) and
                    report.get('contract_sha256')==selection.get('sha256') and
                    report.get('checker_sha256')==selection.get('checker_sha256')==checker_version() and
                    self.snapshot(list(check['artifacts']))==check['artifacts'])
        except (ValueError,OSError):return False

    def materialize(self):
        state = self.status(scope='active')
        if not state['installed']:return
        # These are views, not a second writable memory. Repairable after a failed export.
        if (self.folder/'state.json').is_symlink():raise ValueError('Недопустимая ссылка представления состояния.')
        write_json(self.folder/'state.json',state)
        context = self._context(state)['text']
        path = self.folder/'STATE.md'
        if path.is_symlink():raise ValueError('Недопустимая ссылка представления состояния.')
        temporary=self.folder/('state-view-'+uuid.uuid4().hex+'.tmp')
        try:
            temporary.write_text('# Состояние рабочего проекта\n\n'+context+'\n',encoding='utf-8')
            temporary.replace(path)
        finally:temporary.unlink(missing_ok=True)

    def events(self, limit=100):
        if not self.path.is_file():return []
        with self.db(write=False) as db:
            return [{**dict(r),'details':json.loads(r['details'])} for r in db.execute('SELECT * FROM events ORDER BY seq DESC LIMIT ?', (limit,))]
