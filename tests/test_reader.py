import json
from io import BytesIO
from pathlib import Path
import shutil
import subprocess
import sys
import time
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

from protocol_atlas.adaptive import AdaptiveTasks
from protocol_atlas.editor_ai import AIEditor
from protocol_atlas.onboarding import Onboarding
from protocol_atlas.reader import ReaderStore
from protocol_atlas.runtime_install import bundle, install
from protocol_atlas.project_runtime import ProjectRuntime
from protocol_atlas.source_editor import SourceConflict
from protocol_atlas.laboratory import Laboratory
from protocol_atlas.episodes import synthetic

ROOT = Path(__file__).resolve().parents[1]


class ReaderTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ('PROTOCOL.md', 'check_answer.py', 'memory/GLOSSARY.md', 'atlas/rule_runtime.json'):
            target = self.root/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT/name, target)
        (self.root/'memory/READER.md').write_text('AUTHOR PRIVATE PROFILE', encoding='utf-8')
        self.call = Mock()
        self.editor = AIEditor(self.root, call=self.call)
        with patch('protocol_atlas.providers.credentials', return_value={}):
            self.editor.configure(dict(expected_revision=self.editor.settings()['revision'], provider='custom', endpoint='http://127.0.0.1:9999/v1', model='mock', api_key='test-private-key'))
        self.reader = self.editor.adaptive.reader
        self.answer = 'Промпт понимаю. API пока не понимаю.'
        self.proposal = dict(message='Профиль предложен; проверьте записи.', areas='Работа с текстами', language='Русский', preferences='Примеры из задачи', questions=[],
            terms=[dict(term='Промпт', status='known', evidence=dict(message=0, quote='Промпт понимаю.')),
                   dict(term='API', status='unknown', evidence=dict(message=0, quote='API пока не понимаю.'))])
        self.respond()

    def respond(self, proposal=None):
        self.call.return_value = dict(text=json.dumps(proposal or self.proposal, ensure_ascii=False), model='mock', input_tokens=12, output_tokens=None)

    def converse(self):
        return self.reader.converse(dict(answer=self.answer, expected_revision=self.reader.conversation()['revision'], expected_profile_revision=self.reader.profile()['revision']))

    def accepted(self):
        response = self.converse()
        return self.reader.accept(dict(expected_revision=response['conversation']['revision'], expected_profile_revision=0))

    def test_initial_profile_does_not_import_author_memory(self):
        self.assertFalse(self.reader.profile()['configured'])
        self.assertEqual(self.reader.profile()['terms'], [])
        self.assertIn('не установлено', self.reader.profile()['policy'])
        self.assertFalse(self.call.called)

    def test_grounded_proposal_is_not_used_until_explicit_human_confirmation(self):
        response = self.converse()
        self.assertFalse(response['profile']['configured'])
        conversation = response['conversation']
        self.assertEqual(conversation['checks']['status'], 'completed')
        self.assertEqual(conversation['calls'][0]['messages'], self.call.call_args.args[1])
        self.assertIsNone(conversation['usage']['output_tokens'])
        saved = self.reader.accept(dict(expected_revision=1, expected_profile_revision=0, statuses={'Промпт': 'doubted'}))
        self.assertEqual([t['status'] for t in saved['profile']['terms']], ['doubted','unknown'])
        self.assertEqual(ReaderStore(self.root).profile(), saved['profile'])
        self.assertIn('под сомнением', (self.root/'data/configuration/memory/READER.md').read_text(encoding='utf-8'))
        self.assertEqual((self.root/'memory/READER.md').read_text(), 'AUTHOR PRIVATE PROFILE')

    def test_fabricated_quote_or_ai_explanation_cannot_prove_known(self):
        self.proposal['terms'][0]['evidence']['quote'] = 'Несуществующая цитата'
        self.respond()
        with self.assertRaises(ValueError):
            self.converse()
        self.assertEqual(self.reader.conversation()['revision'], 0)
        self.proposal['terms'] = [dict(term='API', status='known', evidence=dict(message=1, quote='Профиль предложен'))]
        self.respond()
        with self.assertRaises(ValueError):
            self.converse()
        self.proposal['terms'][0]['status'] = 'introduced'
        self.respond()
        result = self.converse()
        self.assertEqual(result['conversation']['proposal']['terms'][0]['status'], 'introduced')
        self.assertFalse(result['profile']['configured'])

    def test_silence_and_later_reply_do_not_confirm_earlier_proposal(self):
        self.converse()
        self.answer = 'Продолжим'
        self.converse()
        self.assertFalse(self.reader.profile()['configured'])
        with self.assertRaises(SourceConflict):
            self.reader.accept(dict(expected_revision=1, expected_profile_revision=0))

    def test_defer_records_actual_choice_and_blocks_stale_proposal(self):
        self.converse()
        result = self.reader.defer(dict(expected_profile_revision=0))
        self.assertFalse(result['profile']['assessed'])
        self.assertEqual(result['profile']['terms'], [])
        with self.assertRaises(SourceConflict):
            self.reader.accept(dict(expected_revision=1, expected_profile_revision=1))
        with self.assertRaises(SourceConflict):
            self.reader.defer(dict(expected_profile_revision=0))

    def test_change_during_model_call_does_not_commit_old_basis(self):
        def change(*args):
            self.reader.defer(dict(expected_profile_revision=0))
            return dict(text=json.dumps(self.proposal))
        self.call.side_effect = change
        with self.assertRaises(SourceConflict):
            self.converse()
        self.assertEqual(self.reader.conversation()['revision'], 0)

    def test_bad_reference_or_checker_failure_blocks_profile_confirmation(self):
        self.proposal['message'] = 'Основание в §999.1.'
        self.respond()
        self.converse()
        with self.assertRaises(ValueError):
            self.reader.accept(dict(expected_revision=1, expected_profile_revision=0))
        self.proposal['message'] = 'Профиль предложен.'
        self.respond()
        (self.root/'check_answer.py').write_text('raise RuntimeError("bad checker")')
        self.converse()
        with self.assertRaises(ValueError):
            self.reader.accept(dict(expected_revision=2, expected_profile_revision=0))

    def test_confirmation_requires_current_protocol_basis(self):
        self.converse()
        path = self.root/'PROTOCOL.md'
        source = path.read_text(encoding='utf-8')
        changed = source.replace('### 1.3 Установить исходное понимание читателя', '### 1.3 Установить понимание пользователя')
        self.assertNotEqual(source, changed)
        path.write_text(changed,encoding='utf-8')
        with self.assertRaises(ValueError):
            self.reader.accept(dict(expected_revision=1, expected_profile_revision=0))

    def test_current_profile_enters_real_configuration_and_task_requests(self):
        self.accepted()
        onboarding = Onboarding(self.editor, self.editor.adaptive)
        self.call.return_value = {'text':json.dumps(dict(message='Настройка предложена.', purpose='Настройка текстов',requirements='Проверять', starting_point='Есть текст', questions=[]))}
        conversation = onboarding.converse(dict(expected_revision=0,answer='Настроить протокол'))
        messages = self.call.call_args.args[1]
        self.assertIn('Промпт', messages[0]['content'])
        self.assertIn('unknown', messages[0]['content'])
        self.assertEqual(conversation['calls'][0]['messages'],messages)
        onboarding.accept(dict(expected_revision=1,expected_profile_revision=0))
        task = self.editor.adaptive.prepare(dict(goal='Объяснить API', task_type='Объяснение',volume='Одно понятие',complexity='Новый термин',criteria='Пример',rule_packs=[]))
        user = json.loads(task['messages'][1]['content'])
        self.assertEqual(user['reader_profile']['revision'],1)
        self.assertEqual(user['reader_profile']['terms'][1]['status'],'unknown')
        self.reader.defer(dict(expected_profile_revision=1))
        self.assertIn('Профиль читателя изменился после подготовки запроса.', self.editor.adaptive.context_changes(task))
        with self.assertRaises(SourceConflict):
            onboarding.accept(dict(expected_revision=1,expected_profile_revision=1))

    def test_secrets_never_enter_trace_or_proposal(self):
        self.answer += ' test-private-key'
        self.proposal['message'] = 'test-private-key'
        self.respond()
        self.call.return_value.update(model='echo-test-private-key', input_tokens='test-private-key')
        result = self.converse()
        self.assertNotIn('test-private-key',json.dumps(result))
        self.assertNotIn('test-private-key',json.dumps(self.call.call_args.args[1]))

    def prepare_source(self):
        shutil.copytree(ROOT/'protocol_atlas',self.root/'protocol_atlas',ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(ROOT/'skills',self.root/'skills')
        self.accepted()
        self.editor.adaptive.configure(dict(expected_revision=0,purpose='Мои тексты',requirements='Проверять основания',starting_point='Начало'))

    def test_bundle_and_workspace_context_transfer_only_current_user_configuration(self):
        self.prepare_source()
        with ZipFile(BytesIO(bundle(self.root))) as archive:
            content='\n'.join(archive.read(n).decode('utf-8') for n in archive.namelist())
            self.assertNotIn('AUTHOR PRIVATE PROFILE',content)
            self.assertNotIn('test-private-key',content)
            config=json.loads(archive.read('.protocol/configuration.json'))
            self.assertEqual(config['reader']['terms'][1]['status'],'unknown')
            with TemporaryDirectory() as destination:
                project=Path(destination)
                archive.extractall(project)
                subprocess.run([sys.executable,'-X','utf8',str(project/'install_protocol.py'),'install','--client','files','--project',str(project)],capture_output=True,check=True)
                context=ProjectRuntime(project).dispatch('context')
                self.assertIn('Мои тексты',context['text'])
                self.assertIn('Промпт понимаю.',context['text'])
                package=ProjectRuntime(project).dispatch('export')
                self.assertIn('Промпт',package['context'])
                self.assertTrue((project/'memory/READER.md').is_file())

    def test_install_preserves_existing_working_profile_and_rejects_config_replacement(self):
        self.prepare_source()
        with TemporaryDirectory() as destination:
            project=Path(destination)
            (project/'memory').mkdir()
            (project/'memory/READER.md').write_text('WORKING PROFILE',encoding='utf-8')
            install(project,client='generic',source=self.root)
            self.assertEqual((project/'memory/READER.md').read_text(), 'WORKING PROFILE')
            self.assertIn('WORKING PROFILE', ProjectRuntime(project).dispatch('context')['text'])
            previous=(project/'.protocol/configuration.json').read_bytes()
            self.reader.defer(dict(expected_profile_revision=1))
            with self.assertRaises(ValueError):
                install(project,client='generic',source=self.root)
            self.assertEqual((project/'.protocol/configuration.json').read_bytes(),previous)

    def test_lab_preview_revision_and_replay_preserve_reader_basis(self):
        self.accepted()
        material = synthetic('attention-start')
        calls = []
        def model(root, provider, name, messages, max_output):
            calls.append(messages)
            return {'text':json.dumps({'answers':[{'task_id':t['id'],'answer':'Тестовый ответ.', 'source_paths':[material['sources'][0]['path']]} for t in material['tasks']]}), 'actual_model':name, 'finish_reason':'stop'}
        lab = Laboratory(self.root,model)
        payload = dict(provider='saved',model='mock',episode_id=material['id'],catalog_revision=material['catalog_revision'],conditions=['full'],expected_reader_revision=0)
        with self.assertRaises(ValueError):
            lab.start(payload)
        self.assertFalse(calls)
        payload['expected_reader_revision']=1
        first = lab.start(payload)
        for _ in range(150):
            first = lab.get(first['id'])
            if first['status'] not in ('prepared','running'):break
            time.sleep(.01)
        self.assertEqual(first['status'],'completed')
        self.assertIn('Промпт понимаю',calls[0][0]['content'])
        self.reader.defer(dict(expected_profile_revision=1))
        replay = lab.start({**payload,'snapshot_run_id':first['id']})
        for _ in range(150):
            replay=lab.get(replay['id'])
            if replay['status'] not in ('prepared','running'):break
            time.sleep(.01)
        self.assertEqual(replay['reader_profile']['revision'],1)
        self.assertEqual(calls[0],calls[1])
        current=lab.start({**payload,'expected_reader_revision':2})
        for _ in range(150):
            current=lab.get(current['id'])
            if current['status'] not in ('prepared','running'):break
            time.sleep(.01)
        self.assertEqual(len(lab.comparison()['groups']),2)
