from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest

from protocol_atlas.comments import CommentStore
from protocol_atlas.server import handler_for


class CommentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = CommentStore(self.root)
        self.payload = {'quote': 'Точный текст <не HTML>\nи ещё строка.', 'text': 'Объяснить понятнее.',
                        'page': '#source?path=PROTOCOL.md&sha=' + 'a' * 64, 'page_title': 'Правило',
                        'source': {'path': 'PROTOCOL.md', 'sha256': 'a' * 64, 'line': 17},
                        'anchor': {'offset': 20, 'prefix': 'Начало: ', 'suffix': ' Конец'}, 'kind': 'wording'}

    def test_persistence_preserves_quote_location_and_unicode(self):
        record = self.store.save(self.payload)
        loaded = CommentStore(self.root).list()['comments'][0]
        self.assertEqual(record, loaded)
        self.assertEqual(loaded['quote'], self.payload['quote'])
        self.assertEqual(loaded['source'], self.payload['source'])
        self.assertEqual(loaded['status'], 'open')

    def test_edit_and_complete_keep_original_anchor(self):
        record = self.store.save(self.payload)
        done = self.store.save({**record, 'text': 'Новая формулировка.', 'status': 'done',
                                'quote': 'Попытка заменить цитату', 'page': '#home'})
        self.assertEqual(done['quote'], record['quote'])
        self.assertEqual(done['page'], record['page'])
        self.assertEqual(done['anchor'], record['anchor'])
        self.assertEqual(done['revision'], 2)
        reopened = self.store.save({**done, 'status': 'open'})
        self.assertEqual(reopened['status'], 'open')
        with self.assertRaises(ValueError):
            self.store.save({**record, 'text': 'Устаревшее изменение'})
        self.assertEqual(self.store.list()['comments'][0]['revision'], 3)

    def test_concurrent_edits_do_not_lose_a_comment(self):
        record = self.store.save(self.payload)
        def update(index):
            try:
                self.store.save({**record, 'text': str(index)})
                return 'saved'
            except ValueError:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(update, (1, 2))), ['saved', 'conflict'])

    def test_invalid_input_never_creates_a_record(self):
        for changes in ({'text': ''}, {'quote': ''}, {'text': 'x' * 12001},
                        {'page': 'https://example.org'}, {'page': '#unknown'},
                        {'kind': 'invalid'}, {'status': 'invalid'},
                        {'anchor': {'offset': -1}}, {'source': {'path': '../.env', 'sha256': 'a'*64}},
                        {'source': {'path': 'PROTOCOL.md', 'sha256': 'invalid'}},
                        {'id': []}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.store.save({**self.payload, **changes})
        self.assertEqual(self.store.list(), {'comments': []})

    def test_api_is_local_and_changes_persist(self):
        handler = handler_for(self.root)
        handler.log_message = lambda *args: None
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(method, path, payload=None, origin=None):
            conn = HTTPConnection('127.0.0.1', server.server_port, timeout=10)
            headers = {'Content-Type': 'application/json'}
            if origin:
                headers['Origin'] = origin
            conn.request(method, path, json.dumps(payload).encode() if payload else None, headers)
            response = conn.getresponse()
            status, body = response.status, response.read()
            conn.close()
            return status, body
        try:
            self.assertEqual(request('POST', '/api/comments/save', self.payload,
                                     'https://example.org')[0], 403)
            self.assertEqual(request('POST', '/api/comments/save', {**self.payload, 'quote': ''})[0], 400)
            status, body = request('POST', '/api/comments/save', self.payload)
            self.assertEqual(status, 200)
            created = json.loads(body)
            self.assertEqual(json.loads(request('GET', '/api/comments')[1])['comments'][0], created)
            self.assertEqual(request('GET', '/comments.js')[0], 200)
            self.assertEqual(request('POST', '/api/comments/save', {**created, 'id': 'missing'})[0], 404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
