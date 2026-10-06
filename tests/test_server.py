from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import threading
import unittest
from zipfile import ZipFile

from protocol_atlas.server import handler_for
from protocol_atlas.connection_files import CONNECTION_FILES
from protocol_atlas.translations import TranslationStore


ROOT = Path(__file__).resolve().parents[1]


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = handler_for(ROOT)
        handler.log_message = lambda *args: None
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, method, path, data=None, headers=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=15)
        body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
        defaults = {"Content-Type": "application/json"} if body else {}
        conn.request(method, path, body, {**defaults, **(headers or {})})
        response = conn.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return result

    def test_static_and_catalog_are_utf8_and_versioned(self):
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("Протокол · Подключение и развитие", body.decode("utf-8"))
        self.assertIn('/portal.js', body.decode('utf-8'))
        script_status, _, script = self.request('GET', '/portal.js')
        self.assertEqual(script_status, 200)
        self.assertIn('function renderImprovement', script.decode('utf-8'))
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
        status, headers, body = self.request("GET", "/api/catalog")
        catalog = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(headers["ETag"], '"' + catalog["catalog_revision"] + '"')
        self.assertTrue(catalog["coverage"]["source_text_complete"])

    def test_english_checker_recognizes_report_and_definition(self):
        status,_,body=self.request('POST','/api/check-answer',{'language':'en','text':'A prime number is a natural number greater than one with exactly two divisors.\n\nTokens: 10.','terms':['prime number'],'require_tokens':True})
        result=json.loads(body)
        self.assertEqual(status,200)
        self.assertEqual(result['warning_count'],0)
        self.assertEqual(result['messages'],[])

    def test_english_checker_reports_vague_word_without_changing_quote(self):
        status,_,body=self.request('POST','/api/check-answer',{'language':'en','text':'This is obvious.\n\nTokens: 10.','require_tokens':True})
        result=json.loads(body)
        self.assertEqual(status,200)
        self.assertEqual(result['warning_count'],1)
        self.assertIn('[VAGUE WORD WITHOUT EXPLANATION?]',result['messages'][0])
        self.assertIn('This is obvious.',result['messages'][0])

    def test_arbitrary_files_are_not_served(self):
        for path in ("/PROTOCOL.md", "/.env", "/../memory/STATE.md", "/api/source?path=.env"):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 404)

    def test_page_scripts_are_served_and_adaptive_renderer_is_in_workspace(self):
        import re
        status, _, body = self.request('GET', '/')
        self.assertEqual(status, 200)
        scripts = re.findall(r'<script[^>]+src="([^"]+)"', body.decode('utf-8'))
        self.assertNotIn('/adaptive.js', scripts)
        for script in scripts:
            status, headers, source = self.request('GET', script)
            self.assertEqual(status, 200, script)
            self.assertIn('text/javascript', headers['Content-Type'])
            if script == '/workspace.js':
                self.assertIn('async function renderAdaptive()', source.decode('utf-8'))

    def test_connection_downloads_preserve_current_files_and_folders(self):
        status, headers, body = self.request('GET', '/api/connection-files')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'application/zip')
        self.assertIn('attachment;', headers['Content-Disposition'])
        with ZipFile(BytesIO(body)) as archive:
            self.assertEqual(archive.namelist(), list(CONNECTION_FILES))
            for path in CONNECTION_FILES:
                self.assertEqual(archive.read(path), (ROOT / path).read_bytes())
                status, headers, content = self.request('GET', '/api/connection-files?path=' + path)
                self.assertEqual(status, 200)
                self.assertEqual(content, archive.read(path))
                self.assertIn(path.rsplit('/', 1)[-1], headers['Content-Disposition'])

    def test_connection_downloads_use_current_english_translations(self):
        status, _, body = self.request('GET', '/api/connection-files?language=en')
        self.assertEqual(status, 200)
        store = TranslationStore(ROOT)
        with ZipFile(BytesIO(body)) as archive:
            for path in CONNECTION_FILES:
                expected = ''.join(u['translation'] for u in store.read(path)['units']).encode('utf-8')
                self.assertEqual(archive.read(path), expected)

    def test_connection_downloads_reject_unlisted_paths_and_languages(self):
        for query in ('path=.env', 'path=../PROTOCOL.md', 'path=data/memory.sqlite3', 'path=', 'language=xx', 'bundle=unknown'):
            with self.subTest(query=query):
                self.assertEqual(self.request('GET', '/api/connection-files?' + query)[0], 400)

    def test_downloads_include_other_documents_code_and_complete_app(self):
        for path in ('memory/GLOSSARY.md', 'docs/CONNECTING_AI.md', 'check_answer.py', 'protocol_atlas/memory.py'):
            status, _, body = self.request('GET', '/api/connection-files?path=' + path)
            self.assertEqual(status, 200)
            self.assertEqual(body, (ROOT / path).read_bytes())
        status, _, body = self.request('GET', '/api/connection-files?bundle=project')
        self.assertEqual(status, 200)
        with ZipFile(BytesIO(body)) as archive:
            self.assertIn('protocol_atlas/server.py', archive.namelist())
            self.assertIn('locales/en/ui.json', archive.namelist())
            self.assertIn('atlas/annotations.json', archive.namelist())
            self.assertNotIn('.env', archive.namelist())
            self.assertFalse(any(p.startswith(('data/', 'runs/')) or '__pycache__' in p for p in archive.namelist()))
            import tempfile
            from protocol_atlas.catalog import build_catalog
            with tempfile.TemporaryDirectory() as folder:
                archive.extractall(folder)
                self.assertTrue(build_catalog(Path(folder), strict_annotations=False)['coverage']['source_text_complete'])

    def test_instruction_download_is_text_and_cannot_choose_arbitrary_filename(self):
        from urllib.parse import urlencode
        query = urlencode({'filename': 'AGENTS.protocol.md', 'text': 'Прочитай протокол из C:/project.'})
        status, headers, body = self.request('GET', '/api/connection-instruction?' + query)
        self.assertEqual(status, 200)
        self.assertEqual(body.decode('utf-8'), 'Прочитай протокол из C:/project.\n')
        self.assertIn('AGENTS.protocol.md', headers['Content-Disposition'])
        self.assertEqual(self.request('GET', '/api/connection-instruction?filename=../.env&text=test')[0], 400)

    def test_new_memory_requirements_regulator_and_episodes_are_exposed(self):
        for path in ('/api/memory', '/api/requirements', '/api/regulator', '/api/comparison', '/workspace.js'):
            self.assertEqual(self.request('GET', path)[0], 200)
        options = json.loads(self.request('GET', '/api/lab-options')[2])
        self.assertEqual(len(options['episodes']), 8)
        self.assertTrue(next(e for e in options['episodes'] if e['id']=='revision')['synthetic'])
        self.assertEqual(self.request('POST', '/api/memory/save', {'basis': [], 'statement': ''})[0], 400)
        self.assertEqual(self.request('POST', '/api/regulator', {'policy': {}})[0], 400)
        for path in ('/api/memory/import', '/api/memory/save', '/api/regulator'):
            self.assertEqual(self.request('POST', path, {}, {'Origin':'https://example.org'})[0], 403)

    def test_checker_uses_real_script_and_does_not_mutate_sources(self):
        checker = ROOT / "check_answer.py"
        before = checker.read_bytes()
        status, _, body = self.request("POST", "/api/check-answer", {
            "text": "Очевидно, объяснение будет ниже.", "require_tokens": True, "terms": []})
        result = json.loads(body)
        self.assertEqual(status, 200)
        self.assertGreaterEqual(result["warning_count"], 3)
        self.assertTrue(any("ССЫЛКА ВПЕРЁД" in message for message in result["messages"]))
        self.assertEqual(checker.read_bytes(), before)

    def test_terms_are_literal_not_user_regex(self):
        status, _, body = self.request("POST", "/api/check-answer", {
            "text": "а+б. Расход токенов недоступен.", "terms": ["а+б"], "require_tokens": True})
        self.assertEqual(status, 200)
        result = json.loads(body)
        self.assertTrue(any("ТЕРМИН БЕЗ ОПРЕДЕЛЕНИЯ" in message for message in result["messages"]))

    def test_bad_input_and_external_origin_rejected(self):
        for payload in ({"text": ""}, {"text": "ok", "terms": "bad"},
                        {"text": "ok", "require_tokens": "yes"}):
            self.assertEqual(self.request("POST", "/api/check-answer", payload)[0], 400)
        self.assertEqual(self.request("POST", "/api/check-answer", {"text": "ok"},
                                     {"Origin": "https://example.org"})[0], 403)
        self.assertEqual(self.request('GET', '/api/catalog', headers={'Host': 'other.example'})[0], 403)
        for path in ('/api/editor/settings', '/api/editor/analyze', '/api/editor/apply', '/api/editor/undo'):
            self.assertEqual(self.request('POST', path, {}, {'Origin': 'https://example.org'})[0], 403)

    def test_editor_endpoints_are_available_and_do_not_expose_credentials(self):
        for path in ('/editor_ai.js', '/api/editor/sources', '/api/editor/changes'):
            self.assertEqual(self.request('GET', path)[0], 200)
        status, _, body = self.request('GET', '/api/editor/settings')
        self.assertEqual(status, 200)
        self.assertNotIn('api_key', json.loads(body))

    def test_lab_plan_identifies_its_status(self):
        status, _, body = self.request("GET", "/api/lab-plan")
        self.assertEqual(status, 200)
        result = json.loads(body)
        self.assertEqual(result["status"], "specification")
        self.assertIn("ожидаемого результата", result["text"])

    def test_lab_preview_contains_sources_but_no_keys_or_criteria(self):
        status, _, body = self.request("GET", "/api/lab-options")
        self.assertEqual(status, 200)
        result = json.loads(body)
        self.assertTrue(result['episode']['sources'])
        self.assertNotIn('criteria', result)
        self.assertNotIn('API_KEY', body.decode('utf-8'))
        self.assertTrue(all('configured' in item for item in result['providers']))
        self.assertEqual(self.request('GET', '/api/runs/' + '0' * 32)[0], 404)
        self.assertEqual(self.request('POST', '/api/memory-run', {'provider': []})[0], 400)
        self.assertEqual(self.request('POST', '/api/memory-run', {}, {'Origin': 'https://example.org'})[0], 403)


if __name__ == "__main__":
    unittest.main()
