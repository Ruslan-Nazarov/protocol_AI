"""Local atlas server. Only explicitly registered files and endpoints are served."""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit, parse_qs

from protocol_atlas.catalog import build_catalog, digest, parse_document
from protocol_atlas.laboratory import Laboratory, episode, episode_options
from protocol_atlas.providers import public_providers
from protocol_atlas.memory import MemoryStore
from protocol_atlas.regulator import simulate, POLICIES, RECOMMENDED
from protocol_atlas.requirements import inventory
from protocol_atlas.comments import CommentStore
from protocol_atlas.source_editor import SourceEditor, SourceConflict
from protocol_atlas.translations import TranslationStore
from protocol_atlas.connection_files import connection_download, instruction_download
from protocol_atlas.editor_ai import AIEditor
from protocol_atlas.adaptive import AdaptiveTasks
from protocol_atlas.onboarding import Onboarding
from protocol_atlas.reader import markdown as reader_markdown
from protocol_atlas.configuration import current_configuration
from protocol_atlas.project_runtime import ProjectRuntime
from protocol_atlas.runtime_install import bundle as runtime_bundle


STATIC = {"/": ("index.html", "text/html"),
          "/app.js": ("app.js", "text/javascript"),
          "/source_editor.js": ("source_editor.js", "text/javascript"),
          "/editor_ai.js": ("editor_ai.js", "text/javascript"),
          "/onboarding.js": ("onboarding.js", "text/javascript"),
          "/reader.js": ("reader.js", "text/javascript"),
          "/project.js": ("project.js", "text/javascript"),
          "/portal.js": ("portal.js", "text/javascript"),
          "/runtime_dashboard.js": ("runtime_dashboard.js", "text/javascript"),
          "/runtime_dashboard.css": ("runtime_dashboard.css", "text/css"),
          "/i18n.js": ("i18n.js", "text/javascript"),
          "/lab.js": ("lab.js", "text/javascript"),
          "/workspace.js": ("workspace.js", "text/javascript"),
          "/comments.js": ("comments.js", "text/javascript"),
          "/styles.css": ("styles.css", "text/css")}
MAX_BODY = 120_000


def check_answer(root: Path, payload: dict) -> dict:
    text = payload.get("text")
    terms = payload.get("terms", [])
    language = payload.get("language", "ru")
    if language not in ("ru", "en"):
        raise ValueError("Выберите язык проверки: ru или en.")
    require_tokens = payload.get("require_tokens", True)
    if not isinstance(text, str) or not text.strip() or len(text) > 80_000:
        raise ValueError("Введите текст ответа: от 1 до 80 000 символов.")
    if not isinstance(terms, list) or len(terms) > 30 or any(
            not isinstance(t, str) or not t.strip() or len(t) > 100 for t in terms):
        raise ValueError("Допускается до 30 терминов длиной до 100 символов.")
    if not isinstance(require_tokens, bool):
        raise ValueError("Параметр отчёта о токенах должен быть логическим.")
    # Terms are literal text. Users do not need to write regular expressions.
    if any(";" in term for term in terms):
        raise ValueError("Термин не должен содержать точку с запятой.")
    with tempfile.TemporaryDirectory(prefix="protocol-answer-") as temp:
        draft = Path(temp) / "answer.txt"
        draft.write_text(text, encoding="utf-8")
        command = [sys.executable, str(root / "check_answer.py"), str(draft)]
        if language == "en":
            command += ["--language", "en"]
        if terms:
            command += ["--terms", ";".join(re.escape(term.strip()) for term in terms)]
        if require_tokens:
            command.append("--require-tokens")
        result = subprocess.run(command, capture_output=True, encoding="utf-8", timeout=10,
                                env={**os.environ, "PYTHONUTF8": "1"})
    if result.returncode not in (0, 1):
        raise RuntimeError("Проверка ответа завершилась с технической ошибкой.")
    lines = result.stdout.splitlines()
    count_match = re.search(r"(?:Замечаний|Warnings): (\d+)", result.stdout)
    count = int(count_match[1]) if count_match else None
    messages = [line for line in lines if not line.startswith(("Замечаний:", "Warnings:"))]
    for term in terms:
        messages = [message.replace(re.escape(term.strip()), term.strip()) for message in messages]
    return {"status": "completed", "exit_code": result.returncode, "warning_count": count,
            "messages": messages,
            "checker_sha256": digest((root / "check_answer.py").read_bytes()),
            "limits": "Это эвристические предупреждения. Отсутствие замечаний не подтверждает понятность, полноту или правильность ответа."}


def handler_for(root: Path, laboratory=None, ai_editor=None):
    root = root.resolve()
    static_root = Path(__file__).resolve().parent / "web"
    lab = laboratory or Laboratory(root)
    memory = MemoryStore(root)
    comments = CommentStore(root)
    source_editor = SourceEditor(root)
    translations = TranslationStore(root)
    editor_ai = ai_editor or AIEditor(root, source_editor)
    adaptive = getattr(editor_ai, 'adaptive', None) or AdaptiveTasks(root, editor_ai, memory)
    onboarding = Onboarding(editor_ai, adaptive)
    runtime = ProjectRuntime(root)

    class Handler(BaseHTTPRequestHandler):
        def send_data(self, status: int, data: bytes, media_type: str, etag: str | None = None, filename: str | None = None):
            self.send_response(status)
            self.send_header("Content-Type", media_type + ("; charset=utf-8" if media_type != 'application/zip' else ''))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if etag:
                self.send_header("ETag", '"' + etag + '"')
            if filename:
                self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(data)

        def send_json(self, status: int, value: dict, etag: str | None = None):
            self.send_data(status, json.dumps(value, ensure_ascii=False).encode("utf-8"),
                           "application/json", etag)

        def local_host(self):
            port = self.server.server_address[1]
            if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
                self.send_json(403, {"error": "Сервер доступен только через локальный адрес."})
                return False
            return True

        def do_GET(self):
            if not self.local_host():
                return
            path = urlsplit(self.path).path
            try:
                if path in STATIC:
                    name, media_type = STATIC[path]
                    self.send_data(200, (static_root / name).read_bytes(), media_type)
                elif path == "/api/catalog":
                    catalog = build_catalog(root, strict_annotations=False)
                    self.send_json(200, catalog, catalog["catalog_revision"])
                elif path == '/api/runtime-installation':
                    command='py -3 "'+str(root/'protocol_atlas/runtime_bootstrap.py')+'" install --project . --client '
                    configuration=current_configuration(root)
                    sha=digest(json.dumps(configuration,ensure_ascii=False,sort_keys=True).encode('utf-8'))
                    self.send_json(200,{'commands':{client:command+client for client in ('codex','claude','gemini','generic','api','files')},
                                        'configuration':configuration, 'configuration_sha256':sha})
                elif path == '/api/runtime-bundle':
                    expected=parse_qs(urlsplit(self.path).query).get('configuration_sha256',[None])[0]
                    if expected and expected != digest(json.dumps(current_configuration(root),ensure_ascii=False,sort_keys=True).encode('utf-8')):
                        self.send_json(409,{'error':'Настройка изменилась. Подготовьте сообщение и архив заново.'})
                        return
                    self.send_data(200,runtime_bundle(root),'application/zip',filename='protocol-runtime.zip')
                elif path.startswith('/api/project-runtime/'):
                    runtime_action=path.rsplit('/',1)[1]
                    if runtime_action not in ('status','context','export','events'):
                        self.send_json(404,{'error':'Неизвестная операция чтения.'})
                    else:self.send_json(200,{'events':runtime.events()} if runtime_action=='events' else runtime.dispatch(runtime_action))
                elif path == "/api/source/document":
                    query = parse_qs(urlsplit(self.path).query)
                    self.send_json(200, source_editor.read(query['path'][0]))
                elif path == "/api/translations/history":
                    query = parse_qs(urlsplit(self.path).query)
                    self.send_json(200, translations.history(query.get('path',[''])[0], query.get('unit_id',[''])[0]))
                elif path == "/api/translations/history/file":
                    query = parse_qs(urlsplit(self.path).query)
                    filename, raw = translations.history_store.export_legacy(query.get('sha',[''])[0])
                    self.send_data(200, raw, 'application/json', filename=filename)
                elif path == "/api/translations":
                    query = parse_qs(urlsplit(self.path).query)
                    self.send_json(200, translations.read(query['path'][0]) if 'path' in query else translations.bundle())
                elif path == "/api/lab-plan":
                    plan = (root / "docs/EXPERIMENT_MEMORY.md").read_bytes()
                    self.send_json(200, {"text": plan.decode("utf-8"), "sha256": digest(plan),
                                         "status": "specification"})
                elif path == "/api/connections":
                    guide = "docs/CONNECTING_AI.md"
                    self.send_json(200, parse_document(guide, (root / guide).read_bytes()))
                elif path == "/api/connection-files":
                    query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                    try:
                        data, filename, media_type = connection_download(root, query.get('language', ['ru'])[0], query.get('path', [None])[0], query.get('bundle', ['basic'])[0])
                    except SourceConflict as exc:
                        self.send_json(409, {'error': str(exc)})
                    except ValueError as exc:
                        self.send_json(400, {'error': str(exc)})
                    else:
                        self.send_data(200, data, media_type, filename=filename)
                elif path == "/api/connection-instruction":
                    query = parse_qs(urlsplit(self.path).query)
                    try:
                        data, filename, media_type = instruction_download(query.get('text', [''])[0], query.get('filename', [''])[0])
                    except ValueError as exc:
                        self.send_json(400, {'error': str(exc)})
                    else:
                        self.send_data(200, data, media_type, filename=filename)
                elif path == '/api/editor/settings':
                    self.send_json(200, editor_ai.settings())
                elif path == '/api/onboarding':
                    self.send_json(200, onboarding.read())
                elif path == '/api/reader':
                    self.send_json(200, adaptive.reader.read())
                elif path == '/api/reader/file':
                    self.send_data(200, reader_markdown(adaptive.reader.profile()).encode('utf-8'), 'text/markdown', filename='READER.md')
                elif path == '/api/adaptive':
                    self.send_json(200, {'profile': adaptive.profile(), 'tasks': adaptive.tasks(), 'plans': adaptive.plans(), 'program_checks': adaptive.program_checks(),
                                        'memory_records': [{k:r[k] for k in ('id','title','status','effective_status','revision')}
                                                           for r in memory.list()['records']]})
                elif path == '/api/adaptive/diagnostics':
                    self.send_json(200, adaptive.diagnostics())
                elif path == '/api/memory/search':
                    from protocol_atlas.retrieval import retrieve
                    query = parse_qs(urlsplit(self.path).query)
                    self.send_json(200, retrieve(root, memory, query.get('q',[''])[0]))
                elif path == '/api/editor/sources':
                    self.send_json(200, {'sources': editor_ai.inventory()})
                elif path == '/api/editor/changes':
                    query = parse_qs(urlsplit(self.path).query)
                    self.send_json(200, {'changes': editor_ai.history(query.get('path', [None])[0])})
                elif re.fullmatch(r'/api/editor/changes/[a-f0-9]{32}', path):
                    self.send_json(200, editor_ai.get(path.rsplit('/', 1)[1]))
                elif path == "/api/health":
                    self.send_json(200, {"status": "ok", "app": "protocol-atlas"})
                elif path == "/api/lab-options":
                    self.send_json(200, {"providers": public_providers(root), "episode": episode(root), "episodes": episode_options(root), "reader_profile":adaptive.reader.profile()})
                elif path == "/api/comparison":
                    self.send_json(200, lab.comparison())
                elif path == "/api/runs":
                    self.send_json(200, {"runs": lab.list_runs()})
                elif path == "/api/requirements":
                    self.send_json(200, inventory(root))
                elif path == '/api/runtime-rules':
                    from protocol_atlas.runtime_rules import compile_rules
                    query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                    packs = [p for p in query['packs'][0].split(',') if p] if 'packs' in query else None
                    try:
                        self.send_json(200, compile_rules(root, packs))
                    except SourceConflict as exc:
                        self.send_json(409, {'error': str(exc)})
                elif path == "/api/memory":
                    self.send_json(200, memory.list())
                elif path == "/api/comments":
                    self.send_json(200, comments.list())
                elif path == "/api/memory/source":
                    query = parse_qs(urlsplit(self.path).query)
                    self.send_json(200, memory.source(query['path'][0], query['sha'][0]))
                elif re.fullmatch(r"/api/memory/[a-zA-Z0-9_.:-]{1,100}", path):
                    query = parse_qs(urlsplit(self.path).query)
                    revision = int(query['revision'][0]) if 'revision' in query else None
                    self.send_json(200, memory.get(path.rsplit('/', 1)[1], revision))
                elif path == "/api/regulator":
                    self.send_json(200, {"policies": POLICIES, "recommended": RECOMMENDED})
                elif re.fullmatch(r"/api/runs/[a-f0-9]{32}", path):
                    self.send_json(200, lab.get(path.rsplit("/", 1)[1]))
                else:
                    self.send_json(404, {"error": "Такой страницы или файла нет в атласе."})
            except FileNotFoundError as exc:
                self.send_json(404, {"error": str(exc)})
            except (ValueError, KeyError, UnicodeError) as exc:
                self.send_json(503, {"error": "Не удалось прочитать актуальные источники.",
                                     "detail": str(exc)})

        def do_POST(self):
            if not self.local_host():
                return
            path = urlsplit(self.path).path
            action = re.fullmatch(r"/api/runs/([a-f0-9]{32})/(cancel|review)", path)
            runtime_action=path.removeprefix('/api/project-runtime/') if path.startswith('/api/project-runtime/') else None
            if path not in ("/api/check-answer", "/api/memory-run", "/api/memory/import", "/api/memory/save", "/api/memory/recheck", "/api/memory/assemble", "/api/memory/check-response", "/api/regulator", "/api/comments/save", "/api/source/preview", "/api/source/save", "/api/translations/save", "/api/translations/ui/save", "/api/translations/restore", '/api/editor/settings', '/api/editor/test-connection', '/api/editor/preview', '/api/editor/analyze', '/api/editor/apply', '/api/editor/undo', '/api/onboarding/message', '/api/onboarding/accept', '/api/reader/message', '/api/reader/accept', '/api/reader/defer', '/api/adaptive/profile', '/api/adaptive/prepare', '/api/adaptive/start', '/api/adaptive/review', '/api/adaptive/intake', '/api/adaptive/plan', '/api/adaptive/critique', '/api/adaptive/check-program') and not action and runtime_action not in ProjectRuntime.actions:
                self.send_json(404, {"error": "Такого действия нет в атласе."})
                return
            origin = self.headers.get("Origin")
            host = self.headers.get("Host")
            if origin and origin != f"http://{host}":
                # Drain a bounded request body before closing HTTP/1.0 so Windows
                # does not reset the connection before the caller receives 403.
                try:
                    rejected_length = int(self.headers.get("Content-Length", "0"))
                    if 0 < rejected_length <= MAX_BODY:
                        self.rfile.read(rejected_length)
                except ValueError:
                    pass
                self.send_json(403, {"error": "Запрос разрешён только из локального атласа."})
                return
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                self.send_json(415, {"error": "Ожидается JSON."})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    self.send_json(413, {"error": "Текст запроса слишком большой или пустой."})
                    return
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("Ожидается объект с текстом ответа.")
                if runtime_action:
                    result=runtime.dispatch(runtime_action,payload)
                elif path == "/api/check-answer":
                    result = check_answer(root, payload)
                elif path == '/api/onboarding/message':
                    result = onboarding.converse(payload)
                elif path == '/api/onboarding/accept':
                    result = onboarding.accept(payload)
                elif path == '/api/reader/message':
                    result = adaptive.reader.converse(payload)
                elif path == '/api/reader/accept':
                    result = adaptive.reader.accept(payload)
                elif path == '/api/reader/defer':
                    result = adaptive.reader.defer(payload)
                elif path == '/api/adaptive/profile':
                    result = adaptive.configure(payload)
                elif path == '/api/adaptive/prepare':
                    result = adaptive.prepare(payload)
                elif path == '/api/adaptive/intake':
                    result = adaptive.intake(payload)
                elif path == '/api/adaptive/start':
                    result = adaptive.start(payload)
                elif path == '/api/adaptive/review':
                    result = adaptive.review(payload)
                elif path == '/api/adaptive/plan':
                    result = adaptive.save_plan(payload)
                elif path == '/api/adaptive/critique':
                    result = adaptive.critique(payload)
                elif path == '/api/adaptive/check-program':
                    result = adaptive.check_program()
                elif path == "/api/memory-run":
                    result = lab.start(payload)
                elif path == "/api/memory/import":
                    result = memory.import_sources()
                elif path == "/api/memory/save":
                    result = memory.save(payload)
                elif path == "/api/comments/save":
                    result = comments.save(payload)
                elif path == "/api/source/preview":
                    result = source_editor.preview(payload)
                elif path == "/api/source/save":
                    result = source_editor.save(payload)
                elif path == '/api/editor/settings':
                    result = editor_ai.configure(payload)
                elif path == '/api/editor/test-connection':
                    result = editor_ai.test_connection(payload)
                elif path == '/api/editor/preview':
                    result = editor_ai.preview(payload)
                elif path == '/api/editor/analyze':
                    result = editor_ai.start(payload)
                elif path == '/api/editor/apply':
                    result = editor_ai.apply(payload)
                elif path == '/api/editor/undo':
                    result = editor_ai.undo(payload)
                elif path == "/api/translations/restore":
                    result = translations.restore(payload)
                elif path == "/api/translations/ui/save":
                    result = translations.save_ui(payload)
                elif path == "/api/translations/save":
                    result = translations.save(payload)
                elif path == "/api/memory/recheck":
                    if not isinstance(payload.get('id'), str):
                        raise ValueError('Нужно имя записи.')
                    result = memory.acknowledge(payload['id'], payload)
                elif path == "/api/memory/assemble":
                    result = memory.assemble(payload)
                elif path == "/api/memory/check-response":
                    result = memory.check_response(payload)
                elif path == "/api/regulator":
                    result = simulate(payload)
                elif action[2] == "cancel":
                    result = lab.cancel(action[1])
                else:
                    result = lab.review(action[1], payload)
                self.send_json(200, result)
            except SourceConflict as exc:
                self.send_json(409, {"error": str(exc)})
            except FileNotFoundError as exc:
                self.send_json(404, {"error": str(exc)})
            except (ValueError, UnicodeError) as exc:
                self.send_json(400, {"error": str(exc)})
            except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
                self.send_json(503, {"error": str(exc)})

        def log_message(self, format, *args):
            # Do not log user drafts or request bodies.
            print(format % args)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(args.root))
    print(f"Protocol atlas: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
