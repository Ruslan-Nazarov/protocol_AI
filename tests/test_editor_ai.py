import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

from protocol_atlas.catalog import REQUIRED_SOURCES, digest
from protocol_atlas.editor_ai import AIEditor, model_call, DEFAULT_SETTINGS
from protocol_atlas.source_editor import SourceConflict


class AIEditorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in REQUIRED_SOURCES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# Document\n\nOriginal rule.\n', encoding='utf-8')
        (self.root / 'docs/RELATED.md').write_text('# Related\n\nAlways report tokens.\n', encoding='utf-8')
        self.editor = AIEditor(self.root, call=self.fake_call)
        self.editor.configure({'provider': 'custom', 'endpoint': 'http://127.0.0.1:9999/v1',
                               'model': 'test-model', 'api_key': 'sk-private-test', 'expected_revision': 'new'})
        self.response = {'summary': 'Scope clarified.', 'patches': [{'path': 'docs/RELATED.md',
                         'before': 'Always report tokens.', 'after': 'Report tokens in research.',
                         'reason': 'Same requirement.', 'relation': 'direct'}], 'unresolved': ['Check translation.']}

    def fake_call(self, settings, messages):
        return {'text': json.dumps(self.response), 'model': 'test-model', 'input_tokens': 100, 'output_tokens': 50}

    def payload(self):
        path = self.root / 'PROTOCOL.md'
        return {'path': 'PROTOCOL.md', 'text': '# Document\n\nResearch rule.\n',
                'expected_sha256': digest(path.read_bytes()), 'intent': 'Clarify scope.',
                'paths': ['PROTOCOL.md', 'docs/RELATED.md'], 'language': 'en'}

    def ready_job(self):
        result = self.editor.start(self.payload())
        for _ in range(200):
            result = self.editor.get(result['id'])
            if result['status'] != 'running':
                return result
            time.sleep(.01)
        self.fail('Worker did not finish')

    def test_preview_is_local_and_does_not_call_model_or_write_sources(self):
        with patch.object(self.editor, 'call', side_effect=AssertionError('Unexpected model call')):
            preview = self.editor.preview(self.payload())
        self.assertEqual(preview['coverage'][0]['mode'], 'full')
        self.assertIn('Original rule.', (self.root / 'PROTOCOL.md').read_text())

    def test_adaptive_human_adjustment_is_in_actual_editor_call(self):
        store = self.editor.adaptive
        store.configure(dict(expected_revision=0,purpose='Edit protocol',requirements='Keep principles',starting_point='Draft',character_budget=30000))
        task = store.prepare(dict(goal='Edit section',task_type='Редактирование документов',volume='One section',complexity='New structure',criteria='Preserve references'))
        task.update(id='reviewed-task',revision=2,status='awaiting_review',review=None)
        store.save(task)
        store.review(dict(id=task['id'],expected_revision=2,outcome='accepted',evidence='Compared references',next_method='Verify every reference before proposing changes'))
        with patch.object(self.editor,'call',wraps=self.fake_call) as call:
            job = self.ready_job()
        self.assertEqual(job['status'],'ready')
        self.assertIn('Verify every reference before proposing changes', call.call_args.args[1][0]['content'])

    def test_adaptive_budget_blocks_editor_before_call(self):
        self.editor.adaptive.configure(dict(expected_revision=0,purpose='Edit protocol',requirements='Preserve content',starting_point='Draft',character_budget=1000))
        with patch.object(self.editor,'call') as call:
            with self.assertRaises(ValueError):
                self.editor.start(self.payload())
        call.assert_not_called()

    def test_settings_and_public_jobs_never_return_api_key(self):
        settings = self.editor.settings()
        self.assertTrue(settings['key_configured'])
        self.assertNotIn('api_key', settings)
        job = self.ready_job()
        self.assertNotIn('sk-private-test', json.dumps(job))
        self.assertNotIn('snapshots', job)
        self.assertEqual(job['status'], 'ready')

    def test_exact_proposals_apply_only_selected_edits_and_undo(self):
        job = self.ready_job()
        self.assertIn('Original rule.', (self.root / 'PROTOCOL.md').read_text())
        result = self.editor.apply({'id': job['id'], 'selected': ['human', 'ai-0']})
        self.assertEqual(result['status'], 'applied')
        self.assertIn('Research rule.', (self.root / 'PROTOCOL.md').read_text())
        self.assertIn('Report tokens in research.', (self.root / 'docs/RELATED.md').read_text())
        self.editor.undo({'id': job['id']})
        self.assertIn('Original rule.', (self.root / 'PROTOCOL.md').read_text())
        self.assertIn('Always report tokens.', (self.root / 'docs/RELATED.md').read_text())

    def test_partial_selection_preserves_remaining_proposals(self):
        job = self.ready_job()
        result = self.editor.apply({'id': job['id'], 'selected': ['human']})
        self.assertEqual(result['remaining'], ['ai-0'])
        self.assertIn('Always report tokens.', (self.root / 'docs/RELATED.md').read_text())

    def test_ai_can_propose_primary_edit_from_intent_without_human_text_change(self):
        self.response['patches'] = [{'path': 'PROTOCOL.md', 'before': 'Original rule.', 'after': 'Research rule.',
                                    'reason': 'Human requested a narrower scope.', 'relation': 'direct'}]
        payload = self.payload()
        payload['text'] = (self.root / 'PROTOCOL.md').read_text(encoding='utf-8')
        with patch.object(self.editor, 'prepare', return_value=self.editor.prepare(payload)):
            job = self.ready_job()
        self.assertEqual([p['id'] for p in job['patches']], ['ai-0'])
        self.editor.apply({'id': job['id'], 'selected': ['ai-0']})
        self.assertIn('Research rule.', (self.root / 'PROTOCOL.md').read_text())

    def test_related_edits_cannot_apply_without_changed_primary(self):
        job = self.ready_job()
        with self.assertRaises(ValueError):
            self.editor.apply({'id': job['id'], 'selected': ['ai-0']})

    def test_secret_echo_is_redacted_from_proposal_history(self):
        self.response['summary'] = 'sk-private-test'
        job = self.ready_job()
        self.assertNotIn('sk-private-test', json.dumps(job))
        self.assertEqual(job['summary'], '[REDACTED]')

    def test_changed_source_blocks_whole_batch_before_writes(self):
        job = self.ready_job()
        (self.root / 'docs/RELATED.md').write_text('Another author edited this.', encoding='utf-8')
        with self.assertRaises(SourceConflict):
            self.editor.apply({'id': job['id'], 'selected': ['human', 'ai-0']})
        self.assertIn('Original rule.', (self.root / 'PROTOCOL.md').read_text())

    def test_undo_cannot_overwrite_newer_changes(self):
        job = self.ready_job()
        self.editor.apply({'id': job['id'], 'selected': ['human']})
        (self.root / 'PROTOCOL.md').write_text('A later change.', encoding='utf-8')
        with self.assertRaises(SourceConflict):
            self.editor.undo({'id': job['id']})
        self.assertEqual((self.root / 'PROTOCOL.md').read_text(), 'A later change.')

    def test_fake_quote_or_unknown_path_is_rejected_without_writing(self):
        for key, value in (('before', 'Not in the source.'), ('path', '../outside.md')):
            self.response['patches'][0][key] = value
            result = self.ready_job()
            self.assertEqual(result['status'], 'failed')
            self.assertIn('Original rule.', (self.root / 'PROTOCOL.md').read_text())

    def test_old_history_is_review_only_unless_append_preserves_quote(self):
        self.response['patches'] = [{'path': 'memory/DECISIONS.md', 'before': 'Original rule.',
                                    'after': 'Rewritten past.', 'reason': 'History.', 'relation': 'possible'}]
        payload = self.payload()
        payload['paths'].append('memory/DECISIONS.md')
        with patch.object(self.editor, 'prepare', return_value=self.editor.prepare(payload)):
            job = self.ready_job()
        self.assertFalse(job['patches'][1]['applicable'])
        with self.assertRaises(ValueError):
            self.editor.apply({'id': job['id'], 'selected': ['human', 'ai-0']})

    def test_failure_during_batch_restores_already_saved_documents(self):
        job = self.ready_job()
        original_save = self.editor.sources.save
        calls = []
        def save(payload):
            calls.append(payload['path'])
            if len(calls) == 2:
                raise RuntimeError('Disk failure')
            return original_save(payload)
        with patch.object(self.editor.sources, 'save', side_effect=save):
            with self.assertRaises(RuntimeError):
                self.editor.apply({'id': job['id'], 'selected': ['human', 'ai-0']})
        self.assertIn('Original rule.', (self.root / 'PROTOCOL.md').read_text())

    def test_settings_conflict_and_remote_plain_http_are_rejected(self):
        with self.assertRaises(SourceConflict):
            self.editor.configure({'expected_revision': 'new'})
        with self.assertRaises(ValueError):
            self.editor.configure({'provider': 'custom', 'endpoint': 'http://example.com/v1',
                                   'model': 'test', 'expected_revision': self.editor.settings()['revision']})

    def test_missing_source_revision_and_invalid_scope_block_analysis(self):
        payload = self.payload()
        payload['expected_sha256'] = 'wrong'
        with self.assertRaises(SourceConflict):
            self.editor.preview(payload)
        payload = self.payload()
        payload['paths'] = ['.env']
        with self.assertRaises(ValueError):
            self.editor.start(payload)


class EditorModelAPITests(unittest.TestCase):
    def test_chat_completions_request_and_response_redaction(self):
        received = []
        class ModelHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append((self.path, self.headers.get('Authorization'), json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                body = json.dumps({'model': 'test', 'choices': [{'message': {'content': '{"summary":"secret-key"}'}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 3}}).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), ModelHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = model_call({**DEFAULT_SETTINGS, 'endpoint': f'http://127.0.0.1:{server.server_port}/v1', 'api_key': 'secret-key', 'model': 'test'}, [{'role': 'user', 'content': 'Return JSON.'}])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertEqual(received[0][0], '/v1/chat/completions')
        self.assertEqual(received[0][1], 'Bearer secret-key')
        self.assertNotIn('response_format', received[0][2])
        self.assertEqual(result['input_tokens'], 10)
        self.assertNotIn('secret-key', result['text'])
