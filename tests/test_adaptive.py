import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import threading

from protocol_atlas.adaptive import AdaptiveTasks
from protocol_atlas.source_editor import SourceConflict


class AdaptiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'PROTOCOL.md').write_text('Human decides.', encoding='utf-8')
        self.settings = dict(configured=True, provider='custom', endpoint='http://localhost/v1', model='one', api_key='secret')
        self.editor = Mock()
        self.editor.settings.side_effect = lambda **kw: self.settings
        self.editor.call.return_value = {'text': 'Result secret', 'input_tokens': 123, 'output_tokens': 45}
        self.store = AdaptiveTasks(self.root, self.editor)
        self.profile = dict(expected_revision=0, purpose='Edit protocol', requirements='Preserve intent', starting_point='Current draft', character_budget=30000)
        self.payload = dict(goal='Edit section', task_type='Редактирование документов', volume='One section and its links', complexity='New structure', criteria='All principles preserved', materials='Full source')

    def ready(self):
        task = self.store.start(self.payload)
        for _ in range(100):
            task = self.store.get(task['id'])
            if task['status'] != 'running':
                return task
            time.sleep(.01)
        self.fail('Worker timeout')

    def test_profile_version_conflict_and_persistence(self):
        with self.assertRaises(ValueError):
            self.store.prepare(self.payload)
        self.store.configure(self.profile)
        with self.assertRaises(SourceConflict):
            self.store.configure(self.profile)
        other = AdaptiveTasks(self.root, self.editor)
        self.assertEqual(other.profile()['starting_point'], 'Current draft')
        self.assertEqual(other.profile()['revision'], 1)

    def test_human_review_changes_actual_next_request_and_editor_guidance(self):
        self.store.configure(self.profile)
        task = self.ready()
        self.assertEqual(task['status'], 'awaiting_review')
        self.assertNotIn('secret', task['answer'])
        self.assertEqual(task['usage']['input_tokens'], 123)
        self.assertIn('Full source', self.editor.call.call_args.args[1][1]['content'])
        review = dict(id=task['id'], expected_revision=task['revision'], outcome='revise', evidence='Compared all principles', error='Lost a link', next_method='Check each cross-reference before editing')
        self.store.review(review)
        next_task = self.ready()
        self.assertEqual(next_task['experience_ids'], [task['id']])
        self.assertIn(review['next_method'], self.editor.call.call_args.args[1][1]['content'])
        self.assertEqual(self.store.editor_guidance(self.settings)['method_for_this_task'], review['next_method'])
        other = AdaptiveTasks(self.root, self.editor)
        self.assertEqual(other.prepare(self.payload)['method'], review['next_method'])

    def test_no_transfer_between_models_or_types_and_unreviewed_results(self):
        self.store.configure(self.profile)
        task = self.ready()
        self.assertEqual(self.store.prepare(self.payload)['experience_ids'], [])
        self.store.review(dict(id=task['id'],expected_revision=2,outcome='accepted',evidence='Compared source',next_method='Verify links'))
        self.settings['model'] = 'two'
        self.assertEqual(self.store.prepare(self.payload)['method'], '')
        self.settings['model'] = 'one'
        self.assertEqual(self.store.prepare({**self.payload,'task_type':'Calculation'})['method'], '')

    def test_overflow_blocks_call_without_truncating(self):
        self.store.configure({**self.profile,'character_budget':1000})
        payload = {**self.payload,'materials':'X'*5000}
        prepared = self.store.prepare(payload)
        self.assertEqual(prepared['gate'], 'blocked')
        self.assertIn('X'*5000, prepared['messages'][1]['content'])
        with self.assertRaises(ValueError):
            self.store.start(payload)
        self.editor.call.assert_not_called()

    def test_review_conflict_and_manual_cancellation_keep_history(self):
        self.store.configure(self.profile)
        task = self.ready()
        review = dict(id=task['id'],expected_revision=2,outcome='accepted',evidence='Verified source',next_method='Check links')
        self.store.review(review)
        with self.assertRaises(SourceConflict):
            self.store.review(review)
        task = self.store.review({**review,'expected_revision':3,'next_method':''})
        self.assertEqual(len(task['review_history']), 2)
        self.assertEqual(self.store.prepare(self.payload)['method'], '')

    def test_intake_proposes_without_executing_task(self):
        self.store.configure(self.profile)
        proposal = {k:'Proposed '+k for k in ('task_type','starting_point','volume','complexity','criteria')}
        self.editor.call.return_value = {'text':json.dumps(proposal)}
        result = self.store.intake({'goal':'Edit section','materials':'Source'})
        self.assertEqual(result['proposal'], proposal)
        self.assertEqual(self.store.tasks(), [])
        self.assertTrue(self.editor.call.call_args.args[0]['json_mode'])

    def test_interrupted_task_not_retried_and_failure_not_calibrated(self):
        self.store.configure(self.profile)
        task = {**self.store.prepare(self.payload),'id':'interrupted','revision':1,'status':'running','review':None}
        self.store.save(task)
        other = AdaptiveTasks(self.root,self.editor)
        self.assertEqual(other.get('interrupted')['status'], 'failed')
        self.assertEqual(other.prepare(self.payload)['experience_ids'], [])
        self.editor.call.assert_not_called()

    def test_http_onboarding_prepare_start_review_cycle(self):
        from protocol_atlas.editor_ai import AIEditor
        from protocol_atlas.server import handler_for
        editor = AIEditor(self.root, call=lambda settings,messages: {'text':'Checked result','input_tokens':12,'output_tokens':5})
        editor.configure({'expected_revision':'new','provider':'custom','endpoint':'http://localhost:9999/v1','model':'test'})
        handler = handler_for(self.root, ai_editor=editor)
        handler.log_message = lambda *args: None
        server = ThreadingHTTPServer(('127.0.0.1',0),handler)
        worker = threading.Thread(target=server.serve_forever,daemon=True)
        worker.start()
        def request(path, payload=None):
            conn = HTTPConnection('127.0.0.1',server.server_address[1],timeout=10)
            conn.request('POST' if payload is not None else 'GET',path,
                         json.dumps(payload) if payload is not None else None,
                         {'Content-Type':'application/json'} if payload is not None else {})
            response=conn.getresponse()
            status=response.status
            result=json.loads(response.read())
            conn.close()
            self.assertEqual(status,200,result)
            return result
        try:
            self.assertFalse(request('/api/adaptive')['profile']['configured'])
            request('/api/adaptive/profile',self.profile)
            self.assertEqual(request('/api/adaptive/prepare',self.payload)['gate'],'ready')
            task=request('/api/adaptive/start',self.payload)
            for _ in range(100):
                task=request('/api/adaptive')['tasks'][0]
                if task['status']!='running':break
                time.sleep(.01)
            request('/api/adaptive/review',dict(id=task['id'],expected_revision=2,outcome='accepted',evidence='Compared requirements',next_method='Check relationships',next_complexity='Moderate: structure is known',next_volume='One section'))
            prepared=request('/api/adaptive/prepare',self.payload)
            self.assertEqual(prepared['method'],'Check relationships')
            self.assertIn('Moderate: structure is known',prepared['messages'][1]['content'])
        finally:
            server.shutdown();server.server_close();worker.join()
