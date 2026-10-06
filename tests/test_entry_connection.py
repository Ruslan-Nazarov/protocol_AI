import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
import shutil
from unittest.mock import Mock, patch

from protocol_atlas.catalog import REQUIRED_SOURCES
from protocol_atlas.editor_ai import AIEditor
from protocol_atlas.providers import call_model, public_providers
from protocol_atlas.server import handler_for
from protocol_atlas.source_editor import SourceConflict


class EntryConnectionTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in REQUIRED_SOURCES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# Document\n\nTest rule.\n', encoding='utf-8')
        shutil.copytree(Path(__file__).resolve().parents[1] / 'atlas', self.root / 'atlas')
        (self.root / 'memory/REGULATOR_PREVIOUS.md').write_text('# Previous regulator\n', encoding='utf-8')
        self.credentials = patch('protocol_atlas.providers.credentials', return_value={})
        self.credentials.start()
        self.addCleanup(self.credentials.stop)
        self.call = Mock(return_value={'text': 'работает', 'model': 'local-model',
                                       'input_tokens': 8, 'output_tokens': 2})
        self.editor = AIEditor(self.root, call=self.call)
        handler = handler_for(self.root, ai_editor=self.editor)
        handler.log_message = lambda *args: None
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, path, payload=None):
        connection = HTTPConnection('127.0.0.1', self.server.server_address[1], timeout=10)
        body = json.dumps(payload) if payload is not None else None
        connection.request(method, path, body, {'Content-Type': 'application/json'} if body else {})
        response = connection.getresponse()
        status, data = response.status, json.loads(response.read())
        connection.close()
        return status, data

    def configure(self, **overrides):
        return self.editor.configure({'expected_revision': self.editor.settings()['revision'],
            'provider': 'custom', 'endpoint': 'http://127.0.0.1:9999/v1',
            'model': 'local-model', 'api_key': 'local-test-secret', **overrides})

    def test_save_is_local_and_explicit_check_opens_next_step(self):
        _, initial = self.request('GET', '/api/editor/settings')
        self.assertFalse(initial['configured'])
        self.assertFalse(initial['connection_verified'])
        saved = self.configure()
        self.call.assert_not_called()
        self.assertFalse(saved['connection_verified'])
        status, result = self.request('POST', '/api/editor/test-connection',
                                      {'expected_revision': saved['revision']})
        self.assertEqual(status, 200)
        self.assertTrue(result['settings']['connection_verified'])
        self.assertNotIn('local-test-secret', json.dumps(result))
        self.assertLessEqual(self.call.call_args.args[0]['max_output'], 1000)
        self.assertEqual(len(self.call.call_args.args[1]), 1)
        self.assertTrue(AIEditor(self.root).settings()['connection_verified'])
        self.assertFalse(self.configure(model='another-model')['connection_verified'])

    def test_reader_choice_and_stale_configuration_download_use_same_http_state(self):
        _, initial = self.request('GET', '/api/reader')
        self.assertFalse(initial['profile']['configured'])
        status, saved = self.request('POST', '/api/reader/defer', {'expected_profile_revision': 0})
        self.assertEqual(status, 200)
        self.assertEqual(saved['profile']['revision'], 1)
        self.call.assert_not_called()
        _, setup = self.request('GET', '/api/runtime-installation')
        self.assertEqual(setup['configuration']['reader']['revision'], 1)
        status, _ = self.request('GET', '/api/runtime-bundle?configuration_sha256=stale')
        self.assertEqual(status, 409)
        connection = HTTPConnection('127.0.0.1', self.server.server_address[1], timeout=10)
        connection.request('GET', '/api/reader/file')
        response = connection.getresponse()
        self.assertEqual(response.status,200)
        self.assertIn('работу без оценки', response.read().decode('utf-8'))
        connection.close()

    def test_stale_or_missing_settings_cannot_send(self):
        status, _ = self.request('POST', '/api/editor/test-connection', {'expected_revision': 'new'})
        self.assertEqual(status, 400)
        self.call.assert_not_called()
        previous = self.configure()
        self.configure(model='another-model')
        status, _ = self.request('POST', '/api/editor/test-connection',
                                 {'expected_revision': previous['revision']})
        self.assertEqual(status, 409)
        self.call.assert_not_called()

    def test_failed_check_does_not_leave_success_or_expose_key(self):
        saved = self.configure()
        payload = {'expected_revision': saved['revision']}
        self.editor.test_connection(payload)
        self.call.side_effect = RuntimeError('provider echoed local-test-secret')
        status, result = self.request('POST', '/api/editor/test-connection', payload)
        self.assertEqual(status, 503)
        self.assertNotIn('local-test-secret', json.dumps(result))
        self.assertFalse(self.editor.settings()['connection_verified'])

    def test_changed_connection_during_request_does_not_verify_new_connection(self):
        saved = self.configure()
        def change_connection(*args):
            self.configure(model='changed-model')
            return {'text': 'works'}
        self.call.side_effect = change_connection
        with self.assertRaises(SourceConflict):
            self.editor.test_connection({'expected_revision': saved['revision']})
        self.assertFalse(self.editor.settings()['connection_verified'])

    def test_lab_uses_same_saved_connection_without_disclosing_credential(self):
        self.configure()
        providers = public_providers(self.root)
        saved = next(p for p in providers if p['id'] == 'saved')
        self.assertEqual(saved['label'], 'Мой ИИ')
        self.assertEqual(saved['model'], 'local-model')
        self.assertNotIn('local-test-secret', json.dumps(providers))
        with patch('protocol_atlas.editor_ai.model_call', return_value=self.call.return_value) as adapter:
            response = call_model(self.root, 'saved', 'local-model', [{'role': 'user', 'content': 'example'}], 4500, True)
            self.assertEqual(adapter.call_args.args[0]['api_key'], 'local-test-secret')
            self.assertTrue(adapter.call_args.args[0]['json_mode'])
            self.assertEqual(response['actual_model'], 'local-model')
            with self.assertRaises(ValueError):
                call_model(self.root, 'saved', 'stale-model', [], 4500)
        status, options = self.request('GET', '/api/lab-options')
        self.assertEqual(status, 200, options)
        self.assertIn('saved', [p['id'] for p in options['providers']])
        self.assertNotIn('local-test-secret', json.dumps(options))


if __name__ == '__main__':
    unittest.main()
