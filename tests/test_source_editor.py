from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest

from protocol_atlas.catalog import REQUIRED_SOURCES, build_catalog, digest
from protocol_atlas.server import handler_for
from protocol_atlas.source_editor import SourceEditor, SourceConflict


class SourceEditorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for path in REQUIRED_SOURCES:
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes('# Заголовок\r\n\r\nИсходный текст.\r\n'.encode())
        (self.root / 'atlas').mkdir()
        (self.root / 'atlas/annotations.json').write_text('[]', encoding='utf-8')
        self.editor = SourceEditor(self.root)

    def payload(self, text):
        return {'path': 'PROTOCOL.md', 'text': text,
                'expected_sha256': digest((self.root / 'PROTOCOL.md').read_bytes())}

    def test_save_preserves_original_and_newlines_and_does_not_write_on_preview(self):
        target = self.root / 'PROTOCOL.md'
        raw = target.read_bytes()
        payload = self.payload('# Новый заголовок\n\nНовый текст.\n')
        preview = self.editor.preview(payload)
        self.assertEqual(preview['sections'][0]['title'], 'Новый заголовок')
        self.assertEqual(target.read_bytes(), raw)
        saved = self.editor.save(payload)
        self.assertEqual((self.root / saved['backup']).read_bytes(), raw)
        self.assertEqual(target.read_bytes(), '# Новый заголовок\r\n\r\nНовый текст.\r\n'.encode())
        self.assertEqual(saved['document']['sha256'], digest(target.read_bytes()))
        self.assertFalse(self.editor.save(self.payload(target.read_text(encoding='utf-8')))['changed'])

    def test_two_editors_cannot_overwrite_same_revision(self):
        first, second = self.payload('Первый'), self.payload('Второй')
        def save(payload):
            try:
                self.editor.save(payload)
                return 'saved'
            except SourceConflict:
                return 'conflict'
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(save, [first, second]))
        self.assertCountEqual(results, ['saved', 'conflict'])
        self.assertIn((self.root / 'PROTOCOL.md').read_text(encoding='utf-8'), ['Первый', 'Второй'])

    def test_auxiliary_guides_and_readme_share_the_versioned_editor(self):
        for path in ('README.md','docs/CONNECTING_AI.md'):
            target=self.root/path;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text('# Руководство\n',encoding='utf-8')
            doc=self.editor.read(path)
            result=self.editor.save({'path':path,'text':'# Новая редакция\n','expected_sha256':doc['sha256']})
            self.assertTrue(result['changed'])
            self.assertEqual((self.root/result['backup']).read_text(encoding='utf-8'),'# Руководство\n')

    def test_unknown_paths_code_and_invalid_text_are_rejected(self):
        original = (self.root / 'PROTOCOL.md').read_bytes()
        for path in ('../PROTOCOL.md', '.env', 'check_answer.py', 'docs/other.md', None):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.editor.save({**self.payload('Правка'), 'path': path})
        for text in (None, '\0', 'x' * 80001):
            with self.subTest(text_type=type(text)), self.assertRaises(ValueError):
                self.editor.preview(self.payload(text))
        self.assertEqual((self.root / 'PROTOCOL.md').read_bytes(), original)

    def test_changed_editorial_quotes_are_flagged_without_breaking_runtime_catalog(self):
        (self.root / 'atlas/annotations.json').write_text(json.dumps([
            {'id': 'example', 'body': 'Пояснение', 'sources': [
                {'path': 'PROTOCOL.md', 'quote': '# Заголовок'}]}]), encoding='utf-8')
        self.editor.save(self.payload('# Другое название\n'))
        with self.assertRaises(ValueError):
            build_catalog(self.root)
        catalog = build_catalog(self.root, strict_annotations=False)
        self.assertTrue(catalog['coverage']['source_text_complete'])
        self.assertEqual(catalog['annotations'][0]['sources'], [])
        self.assertEqual(catalog['annotations'][0]['source_warnings'], ['PROTOCOL.md'])

    def test_http_preview_save_conflict_and_external_origin(self):
        handler = handler_for(self.root)
        handler.log_message = lambda *args: None
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(path, payload, headers=None):
            conn = HTTPConnection('127.0.0.1', server.server_port)
            conn.request('POST', path, json.dumps(payload).encode(),
                         {'Content-Type': 'application/json', **(headers or {})})
            result = conn.getresponse()
            status, body = result.status, json.loads(result.read())
            conn.close()
            return status, body
        try:
            payload = self.payload('# Изменено\n')
            self.assertEqual(request('/api/source/preview', payload)[0], 200)
            self.assertEqual(request('/api/source/save', payload, {'Origin': 'https://other.example'})[0], 403)
            self.assertEqual(request('/api/source/save', payload)[0], 200)
            self.assertEqual(request('/api/source/save', payload)[0], 409)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
