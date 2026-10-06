import io
import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
from unittest.mock import patch
import zipfile

from protocol_atlas.catalog import digest
from protocol_atlas.project_runtime import ProjectRuntime, canonical
from protocol_atlas.runtime_cli import mcp, handler
from protocol_atlas.runtime_install import install, hook, bundle
from protocol_atlas.source_editor import SourceConflict

ROOT=Path(__file__).resolve().parents[1]


def stage(ident='data',requires=None,gate='automatic',kind='command'):
    return {'id':ident,'title':ident,'requires':requires or [],'type':'analysis',
            'volume':'Один воспроизводимый результат','complexity':'Проверить источники и численные итоги',
            'criteria':[{'id':'valid','text':'Итоги сходятся с исходными строками','kind':kind}],'gate':gate}


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.runtime=ProjectRuntime(self.root)
        self.runtime.dispatch('init')
        (self.root/'data.json').write_text('[1,2,3]',encoding='utf-8')

    def tearDown(self):self.temp.cleanup()

    def write(self,action,**payload):
        return self.runtime.dispatch(action,{'expected_revision':self.runtime.status()['revision'],**payload})

    def start(self,stages=None):return self.write('start',goal='Получить проверенную статистику',stages=stages or [stage()])

    def check(self,ident='data',argv=None,**extra):
        return self.write('check',stage_id=ident,criterion_id='valid',artifacts=['data.json'],
                          argv=argv or [sys.executable,'-c','import json;assert sum(json.load(open("data.json")))==6'],**extra)

    def finish(self,ident='data'):return self.write('complete_stage',stage_id=ident,artifacts=['data.json'],summary='Сумма 6')

    def test_workspace_state_contains_no_atlas_memory(self):
        state=self.runtime.status()
        self.assertEqual([],state['tasks'])
        self.assertEqual([],state['connections'])
        self.assertFalse((self.root/'memory').exists())
        self.assertTrue((self.root/'.protocol/state.json').is_file())

    def test_goal_does_not_require_user_classification(self):
        result=self.write('start',goal='Хочу приложение. Есть два API, кода нет.')
        self.assertTrue(result['operation']['requires_agent_plan'])
        self.assertEqual('planning',result['state']['tasks'][0]['status'])

    def test_dependency_advances_after_execution_without_human_button(self):
        self.start([stage(),stage('graphic',['data'])])
        with self.assertRaises(ValueError):self.write('begin_stage',stage_id='graphic')
        self.check();result=self.finish()
        self.assertFalse(result['operation']['human_accepted'])
        self.assertEqual('ready',result['state']['tasks'][0]['stages'][1]['status'])
        self.write('begin_stage',stage_id='graphic')

    def test_human_gate_requires_actual_review(self):
        self.start([stage(gate='human'),stage('graphic',['data'])])
        self.check();self.finish()
        with self.assertRaises(ValueError):self.write('begin_stage',stage_id='graphic')
        self.write('review',outcome='accepted',stage_ids=['data'],human_message='Числа принимаю, продолжай.')
        self.write('begin_stage',stage_id='graphic')

    def test_failed_command_is_evidence_and_blocks_completion(self):
        self.start();result=self.check(argv=[sys.executable,'-c','raise SystemExit(2)'])
        check=result['operation']['check']
        self.assertFalse(check['passed']);self.assertEqual(2,check['evidence']['exit_code'])
        self.assertEqual('executed',check['origin'])
        with self.assertRaises(ValueError):self.finish()

    def test_timeout_and_unavailable_command_are_saved(self):
        self.start()
        result=self.check(argv=[sys.executable,'-c','import time;time.sleep(10)'],timeout=1)
        self.assertFalse(result['operation']['check']['passed'])
        self.assertIn('таймаут',result['operation']['check']['evidence']['error'])
        result=self.check(argv=['protocol-test-command-does-not-exist'])
        self.assertFalse(result['operation']['check']['passed'])

    def test_command_cannot_validate_an_artifact_it_changed(self):
        self.start();result=self.check(argv=[sys.executable,'-c','open("data.json","w").write("[2]")'])
        self.assertTrue(result['operation']['check']['evidence']['changed_during_check'])
        with self.assertRaises(ValueError):self.finish()

    def test_changing_input_invalidates_dependent_result(self):
        self.start([stage(),stage('graphic',['data'])])
        self.check();self.finish();self.check('graphic');self.finish('graphic')
        self.write('review',outcome='accepted',human_message='Принимаю оба результата.')
        (self.root/'data.json').write_text('[1,2,4]',encoding='utf-8')
        state=self.runtime.status()
        self.assertEqual(['needs_recheck','needs_recheck'],[s['status'] for s in state['tasks'][0]['stages']])
        with self.assertRaises(ValueError):self.write('review',outcome='accepted',human_message='Принимаю.')

    def test_rechecking_same_bytes_changes_input_version(self):
        self.start([stage(),stage('graphic',['data'])])
        self.check();self.finish();self.check('graphic');self.finish('graphic')
        self.check();self.finish()
        self.assertEqual('needs_recheck',self.runtime.status()['tasks'][0]['stages'][1]['status'])

    def test_feedback_scope_does_not_discard_unrelated_valid_data(self):
        self.start([stage(),stage('graphic',['data'])])
        self.check();self.finish();self.check('graphic');self.finish('graphic')
        self.write('review',outcome='revise',stage_ids=['graphic'],human_message='Подписи мелкие. Увеличь.')
        task=self.runtime.status()['tasks'][0]
        self.assertEqual('verified',task['stages'][0]['status'])
        self.assertEqual('needs_recheck',task['stages'][1]['status'])
        self.assertEqual('Подписи мелкие. Увеличь.',task['feedback'][-1]['message'])

    def test_replanning_design_preserves_unchanged_data_and_its_checks(self):
        self.start([stage(),stage('graphic',['data'])])
        self.check();self.finish()
        before=self.runtime.status()['tasks'][0]['stages'][0]
        result=self.write('plan',stages=[stage(),{**stage('graphic',['data']),'volume':'Увеличить подписи; прежние числа сохранить.'}])
        after=result['state']['tasks'][0]['stages'][0]
        self.assertEqual('verified',after['status']);self.assertEqual(before['checks'],after['checks'])
        self.assertEqual(['data'],result['operation']['preserved_stage_ids'])

    def test_concurrent_clients_get_conflict_instead_of_overwrite(self):
        old=self.runtime.status()['revision'];self.start()
        with self.assertRaises(SourceConflict):self.runtime.dispatch('start',{'expected_revision':old,'goal':'Другая цель'})
        self.assertEqual(1,len(self.runtime.status()['tasks']))

    def test_retry_is_idempotent_even_after_other_client_writes(self):
        payload={'expected_revision':self.runtime.status()['revision'],'goal':'Цель','request_id':'same'}
        first=self.runtime.dispatch('start',payload)
        self.write('interrupt',reason='Закрыли чат.')
        second=self.runtime.dispatch('start',payload)
        self.assertEqual(first['applied_revision'],second['applied_revision'])
        self.assertEqual(1,len(second['state']['tasks']))
        with self.assertRaises(SourceConflict):self.runtime.dispatch('start',{**payload,'goal':'Другая цель'})

    def test_retry_repairs_views_after_committed_write(self):
        payload={'expected_revision':self.runtime.status()['revision'],'goal':'Цель','request_id':'repair'}
        with patch.object(self.runtime,'materialize',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.runtime.dispatch('start',payload)
        self.assertEqual(1,len(self.runtime.status()['tasks']))
        self.runtime.dispatch('start',payload)
        exported=json.loads((self.root/'.protocol/state.json').read_text(encoding='utf-8'))
        self.assertEqual(1,len(exported['tasks']))

    def test_agent_review_is_labelled_and_cannot_satisfy_command(self):
        self.start()
        with self.assertRaises(ValueError):self.write('check',stage_id='data',criterion_id='valid',passed=True,evidence='Я думаю, всё верно.')
        self.write('plan',stages=[stage(kind='agent_review')])
        result=self.write('check',stage_id='data',criterion_id='valid',passed=True,evidence='Сравнил три строки.',artifacts=['data.json'])
        self.assertEqual('agent_report',result['operation']['check']['origin'])

    def test_paths_cannot_escape_or_snapshot_credentials(self):
        for name in ('../outside','.env','.env.local','.protocol/state.json','C:/Windows/a','a\\b','/tmp/a'):
            with self.subTest(name=name),self.assertRaises(ValueError):self.runtime.file(name)

    def test_invalid_stage_is_validation_error(self):
        for stages in ([None],[stage('a',['b']),stage('b',['a'])],[{**stage(),'criteria':[]}],[{**stage(),'type':''}]):
            with self.subTest(stages=stages),self.assertRaises(ValueError):self.write('start',goal='Цель',stages=stages)

    def test_import_does_not_turn_reports_into_executed_checks(self):
        self.start();self.check();self.finish()
        package=self.runtime.dispatch('export')
        self.write('import',package=package)
        current=self.runtime.status()['tasks'][0]['stages'][0]
        self.assertEqual('imported',current['checks'][0]['origin'])
        with self.assertRaises(ValueError):self.finish()
        self.check();self.finish()

    def test_file_operations_resume_same_state(self):
        self.start()
        package=self.runtime.dispatch('export')
        package['operations']=[{'action':'interrupt','payload':{'reason':'Обычный чат закончил сеанс.'}}]
        package['sha256']=digest(canonical({k:v for k,v in package.items() if k!='sha256'}).encode())
        result=self.write('import',package=package)
        self.assertEqual('file_operations_applied',result['operation']['kind'])
        self.assertEqual('interrupted',result['state']['tasks'][0]['status'])
        with self.assertRaises(SourceConflict):self.write('import',package=package)

    def test_text_only_file_reply_needs_no_checksum_and_preserves_version_gate(self):
        self.start();package=self.runtime.dispatch('export')
        payload=package['reply_template']
        payload['reply']['operations']=[{'action':'interrupt','payload':{'reason':'Текстовый чат вернул продолжение.'}}]
        result=self.runtime.dispatch('import',payload)
        self.assertEqual('interrupted',result['state']['tasks'][0]['status'])
        with self.assertRaises(SourceConflict):self.runtime.dispatch('import',payload)

    def test_file_import_never_runs_embedded_command(self):
        self.start();package=self.runtime.dispatch('export')
        package['operations']=[{'action':'check','payload':{'stage_id':'data','criterion_id':'valid','argv':[sys.executable,'-c','open("bad","w").write("x")']}}]
        package['sha256']=digest(canonical({k:v for k,v in package.items() if k!='sha256'}).encode())
        with self.assertRaises(ValueError):self.write('import',package=package)
        self.assertFalse((self.root/'bad').exists())

    def test_mcp_and_direct_client_share_versions(self):
        incoming=io.StringIO('\n'.join(json.dumps(value) for value in [
            {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18'}},
            {'jsonrpc':'2.0','id':2,'method':'tools/list'},
            {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'protocol_start','arguments':{'expected_revision':1,'goal':'Через MCP'}}}
        ])+'\n')
        outgoing=io.StringIO();mcp(self.runtime,incoming,outgoing)
        replies=[json.loads(line) for line in outgoing.getvalue().splitlines()]
        self.assertEqual('2025-06-18',replies[0]['result']['protocolVersion'])
        self.assertGreater(len(replies[1]['result']['tools']),10)
        self.assertFalse(replies[2]['result']['isError'])
        self.assertEqual('Через MCP',self.runtime.status()['tasks'][0]['goal'])

    def test_http_uses_same_revision_and_rejects_cross_origin(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.runtime))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        url='http://127.0.0.1:'+str(server.server_address[1])+'/protocol/'
        try:
            payload=json.dumps({'expected_revision':1,'goal':'Через API'}).encode()
            request=Request(url+'start',data=payload,headers={'Content-Type':'application/json'})
            with urlopen(request) as response:self.assertEqual(2,json.load(response)['applied_revision'])
            with self.assertRaises(HTTPError) as error:urlopen(request)
            self.assertEqual(409,error.exception.code)
            bad=Request(url+'status',headers={'Origin':'https://outside.example'})
            with self.assertRaises(HTTPError) as error:urlopen(bad)
            self.assertEqual(403,error.exception.code)
        finally:server.shutdown();server.server_close();thread.join()

    def test_history_stores_deltas_without_recopying_all_tasks(self):
        self.start();self.write('interrupt',reason='Перерыв')
        event=self.runtime.events()[0]
        with self.runtime.db() as db:
            after=json.loads(db.execute('SELECT body FROM objects WHERE sha=?',(event['after_sha'],)).fetchone()[0])
        self.assertNotIn('/tasks',after)
        self.assertIn('/tasks/0/status',after)

    def test_storage_limits_preserve_current_work_and_reject_expired_retry(self):
        self.start()
        self.write('storage',host_event_limit=0,workflow_event_limit=100,command_output='none')
        old={'expected_revision':self.runtime.status()['revision'],'reason':'old','request_id':'old'}
        self.runtime.dispatch('interrupt',old)
        for i in range(101):self.write('interrupt',reason=str(i))
        self.assertEqual(100,self.runtime.status()['diagnostics']['workflow_events'])
        self.assertEqual(1,len(self.runtime.status()['tasks']))
        with self.assertRaises(SourceConflict):self.runtime.dispatch('interrupt',old)

    def test_successful_command_output_is_optional_and_hashed(self):
        self.start()
        result=self.check(argv=[sys.executable,'-c','print("verbose passing output")'])
        evidence=result['operation']['check']['evidence']
        self.assertEqual('',evidence['output']);self.assertGreater(evidence['output_bytes'],0)
        self.write('storage',host_event_limit=2000,command_output='all')
        result=self.check(argv=[sys.executable,'-c','print("verbose passing output")'])
        self.assertIn('verbose passing',result['operation']['check']['evidence']['output'])

    def test_experience_is_scoped_and_changes_next_context_after_actual_failure(self):
        self.write('start',goal='Счёт',stages=[stage()],executor={'client':'api','model':'model-one'})
        self.check(argv=[sys.executable,'-c','raise SystemExit(2)'])
        self.assertIn('Уменьшить объём',self.runtime.dispatch('context')['text'])
        self.write('start',goal='Другой исполнитель',stages=[stage()],executor={'client':'api','model':'model-two'})
        current=self.runtime.dispatch('context')['text']
        self.assertNotIn('Уменьшить объём',current)
        self.assertEqual(0,self.runtime.status()['experience'][1]['failed_checks'])

    def test_imported_accepted_status_without_checks_is_not_trusted(self):
        self.start();package=self.runtime.dispatch('export')
        package['state']['tasks'][0]['stages'][0]['status']='accepted'
        package['sha256']=digest(canonical({k:v for k,v in package.items() if k!='sha256'}).encode())
        self.write('import',package=package)
        self.assertEqual('ready',self.runtime.status()['tasks'][0]['stages'][0]['status'])

    def test_normal_context_does_not_rehash_or_recopy_inactive_tasks(self):
        self.start();self.check();self.finish()
        self.write('start',goal='Новая цель')
        (self.root/'data.json').unlink()
        with patch.object(self.runtime,'file',side_effect=AssertionError('Не сканировать старый артефакт в каждом обычном ходе')):
            context=self.runtime.dispatch('context')
        self.assertEqual(2,context['state']['task_count'])
        self.assertEqual(1,len(context['state']['tasks']))
        self.assertEqual('needs_recheck',self.runtime.status()['tasks'][0]['stages'][0]['status'])

    def test_interruption_preserves_failed_evidence_and_a_resumable_stage(self):
        self.start();self.check(argv=[sys.executable,'-c','raise SystemExit(2)'])
        self.write('interrupt',reason='Нет разрешённого клиентского окружения.')
        task=self.runtime.dispatch('context')['state']['tasks'][0]
        self.assertEqual('interrupted',task['stages'][0]['status'])
        self.assertEqual('data',task['next_stage'])
        self.assertFalse(task['stages'][0]['checks'][-1]['passed'])
        self.write('begin_stage',stage_id='data')
        self.assertEqual('running',self.runtime.status()['tasks'][0]['stages'][0]['status'])


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)

    def tearDown(self):self.temp.cleanup()

    def test_installed_engine_runs_without_atlas_or_python_dependencies(self):
        result=install(self.root,'generic',ROOT)
        process=subprocess.run([sys.executable,result['runner'],'context','--project',str(self.root)],
                               cwd=self.root,capture_output=True,encoding='utf-8')
        self.assertEqual(0,process.returncode,process.stderr)
        self.assertTrue(json.loads(process.stdout)['state']['installed'])
        self.assertFalse((self.root/'data').exists())
        exported=ProjectRuntime(self.root).dispatch('export')
        self.assertIn('The user',exported['agent_instructions'])
        self.assertIn('Project operation contract',exported['agent_instructions'])

    def test_real_stdio_mcp_process_initializes_and_records_task(self):
        result=install(self.root,'api',ROOT)
        requests=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18'}},
                  {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'protocol_start','arguments':{'expected_revision':2,'goal':'Задача по stdio'}}}]
        process=subprocess.run([sys.executable,result['runner'],'mcp','--project',str(self.root)],
             input=''.join(json.dumps(r)+'\n' for r in requests),capture_output=True,encoding='utf-8',cwd=self.root)
        self.assertEqual(0,process.returncode,process.stderr)
        replies=[json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual('2025-06-18',replies[0]['result']['protocolVersion'])
        self.assertFalse(replies[1]['result']['isError'])
        self.assertEqual('Задача по stdio',ProjectRuntime(self.root).status()['tasks'][0]['goal'])

    def test_install_preserves_user_instructions_and_hooks_and_is_repeatable(self):
        (self.root/'AGENTS.md').write_text('Правила проекта\n',encoding='utf-8')
        (self.root/'.codex').mkdir()
        (self.root/'.codex/hooks.json').write_text(json.dumps({'hooks':{'Stop':[{'hooks':[{'type':'command','command':'user-command'}]}]}}),encoding='utf-8')
        (self.root/'.codex/config.toml').write_text('model_reasoning_effort = "xhigh"\n',encoding='utf-8')
        first=install(self.root,'codex',ROOT);second=install(self.root,'codex',ROOT)
        self.assertEqual(first['project_id'],second['project_id'])
        text=(self.root/'AGENTS.md').read_text(encoding='utf-8')
        self.assertTrue(text.startswith('Правила проекта'))
        self.assertEqual(1,text.count('<!-- protocol-ai:start -->'))
        hooks=json.loads((self.root/'.codex/hooks.json').read_text(encoding='utf-8'))['hooks']['Stop']
        self.assertEqual(2,len(hooks));self.assertEqual('user-command',hooks[0]['hooks'][0]['command'])
        self.assertIn('model_reasoning_effort = "xhigh"',(self.root/'.codex/config.toml').read_text())

    @unittest.skipUnless(sys.platform == 'win32', 'Windows Codex command-hook launch')
    def test_installed_hooks_execute_in_cmd(self):
        project=self.root/"Проект с пробелами $literal's"
        project.mkdir()
        install(project,'codex',ROOT)
        hooks=json.loads((project/'.codex/hooks.json').read_text(encoding='utf-8'))['hooks']
        for event,groups in hooks.items():
            with self.subTest(event=event):
                command=groups[0]['hooks'][0]['command']
                payload={'hook_event_name':event,'session_id':'shell-test','turn_id':event}
                # Match the Codex hook runner's COMSPEC /C + raw quoted command,
                # rather than the PowerShell used for ordinary agent tools.
                line='"'+os.environ.get('COMSPEC','cmd.exe')+'" /C "'+command+'"'
                process=subprocess.run(line,
                    input=json.dumps(payload).encode('utf-8'),capture_output=True,timeout=15)
                self.assertEqual(0,process.returncode,process.stderr.decode('utf-8',errors='replace'))
                json.loads(process.stdout)
        self.assertEqual(set(hooks),set(ProjectRuntime(project).status()['diagnostics']['observed_host_events']))

    def test_declared_hooks_do_not_appear_as_observed(self):
        install(self.root,'codex',ROOT);runtime=ProjectRuntime(self.root)
        self.assertEqual({},runtime.status()['diagnostics']['observed_host_events'])
        payload={'hook_event_name':'UserPromptSubmit','session_id':'s','turn_id':'t','prompt':'SECRET: human text'}
        output=hook(runtime,payload)
        self.assertIn('additionalContext',output['hookSpecificOutput'])
        hook(runtime,payload)
        self.assertEqual({'UserPromptSubmit':1},runtime.status()['diagnostics']['observed_host_events'])
        self.assertNotIn(b'SECRET',runtime.path.read_bytes())

    def test_hook_retention_and_bounded_stop(self):
        install(self.root,'codex',ROOT);runtime=ProjectRuntime(self.root)
        runtime.dispatch('storage',{'expected_revision':runtime.status()['revision'],'host_event_limit':2})
        runtime.dispatch('start',{'expected_revision':runtime.status()['revision'],'goal':'Цель'})
        output=hook(runtime,{'hook_event_name':'Stop','session_id':'s','turn_id':'1'})
        self.assertEqual('block',output['decision'])
        self.assertEqual({},hook(runtime,{'hook_event_name':'Stop','session_id':'s','turn_id':'2','stop_hook_active':True}))
        hook(runtime,{'hook_event_name':'Interrupt','session_id':'s','turn_id':'3'})
        self.assertEqual(2,sum(runtime.status()['diagnostics']['observed_host_events'].values()))
        self.assertEqual('interrupted',runtime.status()['tasks'][0]['status'])

    def test_portable_installation_has_no_project_state(self):
        raw=bundle(ROOT)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertFalse(any(n.endswith('.sqlite3') or n.endswith('PACKAGE.json') or n.endswith('.env') for n in archive.namelist()))
            archive.extractall(self.root)
        process=subprocess.run([sys.executable,'install_protocol.py','install','--client','claude','--project','.'],
                               cwd=self.root,capture_output=True,encoding='utf-8')
        self.assertEqual(0,process.returncode,process.stderr)
        self.assertTrue((self.root/'CLAUDE.md').is_file())


if __name__=='__main__':unittest.main()
