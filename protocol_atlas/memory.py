"""Versioned local memory: immutable revisions, pinned evidence and recheck queues."""
from __future__ import annotations

from protocol_atlas.context import compile_context, context_need, validate_response, RESPONSE_INSTRUCTION

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import threading
import uuid

from protocol_atlas.catalog import build_catalog, digest

KINDS = ('fact', 'decision', 'hypothesis', 'constraint', 'question', 'observation', 'goal')
STATUSES = ('proposed', 'accepted', 'rejected', 'superseded', 'imported')


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class MemoryStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.directory = self.root / 'data'
        if not self.directory.resolve().is_relative_to(self.root):
            raise ValueError('Хранилище выходит за пределы проекта.')
        self.directory.mkdir(exist_ok=True)
        self.path = self.directory / 'memory.sqlite3'
        if self.path.is_symlink():
            raise ValueError('Недопустимая ссылка хранилища.')
        self.lock = threading.RLock()
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS revisions (
                    id TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL,
                    created_at TEXT NOT NULL, PRIMARY KEY(id, revision));
                CREATE TABLE IF NOT EXISTS sources (
                    path TEXT NOT NULL, sha TEXT NOT NULL, text TEXT NOT NULL,
                    PRIMARY KEY(path, sha));
                CREATE TABLE IF NOT EXISTS rechecks (
                    id TEXT PRIMARY KEY, reasons TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, event TEXT NOT NULL);
            ''')

    @contextmanager
    def connection(self):
        with self.lock:
            db = sqlite3.connect(self.path, timeout=10)
            db.row_factory = sqlite3.Row
            try:
                db.execute('BEGIN IMMEDIATE')
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

    @staticmethod
    def _latest(db):
        return {row['id']: json.loads(row['payload']) for row in db.execute(
            'SELECT r.* FROM revisions r JOIN (SELECT id, MAX(revision) rev FROM revisions GROUP BY id) l ON r.id=l.id AND r.revision=l.rev')}

    @staticmethod
    def _load(db, record_id, revision=None):
        row = db.execute('SELECT payload FROM revisions WHERE id=?' +
                         (' AND revision=?' if revision is not None else ' ORDER BY revision DESC LIMIT 1'),
                         (record_id, revision) if revision is not None else (record_id,)).fetchone()
        if row is None:
            raise FileNotFoundError('Запись или версия памяти не найдена.')
        return json.loads(row['payload'])

    def get(self, record_id, revision=None):
        with self.connection() as db:
            record = self._load(db, record_id, revision)
            row = db.execute('SELECT reasons FROM rechecks WHERE id=?', (record_id,)).fetchone()
            record['recheck_reasons'] = json.loads(row[0]) if row else []
            record['effective_status'] = 'needs_recheck' if row else record['status']
            record['history'] = [dict(item) for item in db.execute(
                'SELECT revision,created_at FROM revisions WHERE id=? ORDER BY revision', (record_id,))]
            return record

    def source(self, path, sha, start=1, end=None):
        with self.connection() as db:
            return self._source(db, path, sha, start, end)

    @staticmethod
    def _source(db, path, sha, start=1, end=None):
        if type(start) is not int or start < 1 or (end is not None and (type(end) is not int or end < start)):
            raise ValueError('Некорректный диапазон источника.')
        row = db.execute('SELECT text FROM sources WHERE path=? AND sha=?', (path, sha)).fetchone()
        if row is None:
            raise FileNotFoundError('Такого снимка источника нет в памяти.')
        lines = row[0].splitlines(keepends=True)
        if start > len(lines) or (end is not None and end > len(lines)):
            raise ValueError('Диапазон выходит за пределы снимка.')
        return {'path': path, 'sha256': sha, 'start_line': start, 'end_line': end or len(lines),
                'text': ''.join(lines[start - 1:end])}

    @staticmethod
    def _dependents(records, changed):
        affected = set(changed)
        while True:
            more = {key for key, record in records.items() if any(
                ref.get('type') == 'record' and ref['id'] in affected for ref in record['basis'])}
            if more <= affected:
                return affected - set(changed)
            affected.update(more)

    @staticmethod
    def _mark(db, record_id, reason):
        row = db.execute('SELECT reasons FROM rechecks WHERE id=?', (record_id,)).fetchone()
        reasons = json.loads(row[0]) if row else []
        if reason not in reasons:
            reasons.append(reason)
        db.execute('INSERT OR REPLACE INTO rechecks VALUES (?,?)', (record_id, json.dumps(reasons, ensure_ascii=False)))

    def save(self, payload, *, source_import=False):
        record_id = payload.get('id') or 'mem-' + uuid.uuid4().hex[:20]
        if not isinstance(record_id, str) or not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,100}', record_id):
            raise ValueError('Недопустимое имя записи.')
        kind, status = payload.get('kind', 'fact'), payload.get('status', 'proposed')
        if kind not in KINDS or status not in STATUSES:
            raise ValueError('Неизвестный тип или статус записи.')
        if status == 'imported' and not source_import:
            status = 'proposed'
        record = {'id': record_id, 'kind': kind, 'status': status}
        for field in ('title', 'statement', 'need', 'transition', 'scope', 'verification'):
            value = payload.get(field)
            if value is not None and (not isinstance(value, str) or len(value) > 20000):
                raise ValueError('Поле записи слишком длинное или имеет неверный тип.')
            record[field] = value
        if not record['title'] or not record['statement'] or not record['statement'].strip():
            raise ValueError('Нужны название и содержание записи.')
        basis = payload.get('basis', [])
        expected = payload.get('expected_revision')
        if expected is not None and (type(expected) is not int or expected < 1):
            raise ValueError('Нужна точная положительная версия перед правкой.')
        if not isinstance(basis, list) or len(basis) > 40 or any(not isinstance(ref, dict) for ref in basis):
            raise ValueError('Основания должны быть списком до 40 ссылок.')
        with self.connection() as db:
            old = db.execute('SELECT MAX(revision) FROM revisions WHERE id=?', (record_id,)).fetchone()[0]
            if payload.get('expected_revision') != old:
                raise ValueError('Версия записи изменилась. Откройте её заново перед сохранением.')
            normalized = []
            for ref in basis:
                if ref.get('type') == 'source':
                    path, sha, quote = ref.get('path'), ref.get('sha256'), ref.get('quote')
                    if not isinstance(path, str) or not isinstance(sha, str):
                        raise ValueError('Нужны путь и SHA снимка источника.')
                    snapshot = self._source(db, path, sha, ref.get('start_line', 1), ref.get('end_line'))
                    if not isinstance(quote, str) or not quote.strip() or quote not in snapshot['text']:
                        raise ValueError('Цитата основания отсутствует в указанном фрагменте снимка.')
                    normalized.append({'type': 'source', **snapshot, 'quote': quote})
                    normalized[-1].pop('text')
                elif ref.get('type') == 'record':
                    if not isinstance(ref.get('id'), str) or ref.get('id') == record_id or type(ref.get('revision')) is not int:
                        raise ValueError('Запись не может обосновывать саму себя; нужна точная версия основания.')
                    self._load(db, ref.get('id'), ref['revision'])
                    normalized.append({'type': 'record', 'id': ref['id'], 'revision': ref['revision']})
                else:
                    raise ValueError('Основание: снимок источника или версия другой записи.')
            record.update(basis=normalized, revision=(old or 0) + 1, parent_revision=old,
                          created_at=timestamp(), origin='manual')
            if source_import:
                record['origin'] = 'source_import'
            records = self._latest(db)
            records[record_id] = record
            visited = set()
            def visit(key, trail):
                if key in trail:
                    raise ValueError('Цикл оснований: ' + ' → '.join([*trail, key]))
                if key in visited:
                    return
                for ref in records[key]['basis']:
                    if ref['type'] == 'record' and ref['id'] in records:
                        visit(ref['id'], [*trail, key])
                visited.add(key)
            visit(record_id, [])
            db.execute('INSERT INTO revisions VALUES (?,?,?,?)',
                       (record_id, record['revision'], json.dumps(record, ensure_ascii=False), record['created_at']))
            # A changed record is a new revision; history and dependent conclusions stay intact.
            if old is not None:
                for dependent in self._dependents(records, {record_id}):
                    self._mark(db, dependent, f'Основание {record_id} изменено: версия {old} → {record["revision"]}.')
            for ref in normalized:
                if ref['type'] == 'record':
                    current = records[ref['id']]['revision']
                    if current != ref['revision'] or db.execute('SELECT 1 FROM rechecks WHERE id=?', (ref['id'],)).fetchone():
                        self._mark(db, record_id, f'Основание {ref["id"]} требует проверки или имеет другую текущую версию.')
            db.execute('INSERT INTO events(at,event) VALUES (?,?)', (timestamp(), json.dumps(
                {'type': 'revision', 'id': record_id, 'revision': record['revision']}, ensure_ascii=False)))
        return self.get(record_id)

    def import_sources(self):
        catalog = build_catalog(self.root, strict_annotations=False)
        with self.connection() as db:
            for doc in catalog['documents']:
                db.execute('INSERT OR IGNORE INTO sources VALUES (?,?,?)',
                           (doc['path'], doc['sha256'], ''.join(block['text'] for block in doc['blocks'])))
        imported = 0
        preserved = []
        for doc in catalog['documents']:
            if not (doc['path'].startswith('memory/') or doc['path'] in ('PROTOCOL.md', 'docs/LAB_CONTRACT.md')):
                continue
            sections = doc['sections']
            for section in sections:
                blocks = [block for block in doc['blocks'] if block['section_id'] == section['id']
                          and block['kind'] not in ('heading', 'blank', 'separator')]
                content = ''.join(block['text'] for block in blocks).strip()
                if not content:
                    continue
                start, end = blocks[0]['start_line'], blocks[-1]['end_line']
                text = ''.join(block['text'] for block in doc['blocks'] if start <= block['start_line'] <= end)
                heading_key = section['title']
                duplicates = [item for item in doc['sections'] if item['title'] == section['title']]
                if len(duplicates) > 1:
                    heading_key += '\noccurrence:' + str(next(i for i, item in enumerate(duplicates) if item['id'] == section['id']))
                record_id = 'src-' + digest((doc['path'] + '\n' + heading_key).encode())[:20]
                try:
                    previous = self.get(record_id)
                    if previous.get('origin') != 'source_import':
                        preserved.append(record_id)
                        continue
                    if any(ref['type'] == 'source' and ref['path'] == doc['path'] and ref['sha256'] == doc['sha256'] for ref in previous['basis']):
                        continue
                except FileNotFoundError:
                    previous = None
                kind = ('decision' if doc['path'].endswith('DECISIONS.md') else 'observation'
                        if doc['path'].endswith('ERRORS.md') else 'question' if doc['path'].endswith('OPEN_QUESTIONS.md')
                        else 'constraint' if doc['path'] in ('PROTOCOL.md', 'docs/LAB_CONTRACT.md') else 'fact')
                self.save({'id': record_id, 'expected_revision': previous['revision'] if previous else None,
                           'title': section['title'], 'statement': content, 'kind': kind, 'status': 'imported',
                           'need': None, 'transition': None, 'scope': f'Исходный раздел {doc["path"]}; смысловая оценка отдельно.',
                           'verification': 'Точный текст и цитата проверены программой; применение правила не оценено.',
                           'origin': 'source_import', 'basis': [{'type': 'source', 'path': doc['path'],
                           'sha256': doc['sha256'], 'start_line': start, 'end_line': end, 'quote': text}]}, source_import=True)
                imported += 1
        return {'imported_revisions': imported, 'manual_records_preserved': preserved,
                'catalog_revision': catalog['catalog_revision'], **self.list()}

    def audit(self):
        with self.connection() as db:
            records = self._latest(db)
            affected = set()
            for key, record in records.items():
                for ref in record['basis']:
                    if ref['type'] != 'source':
                        continue
                    path = self.root / ref['path']
                    valid = path.resolve().is_relative_to(self.root) and path.is_file()
                    if not valid or digest(path.read_bytes()) != ref['sha256']:
                        reason = f'Источник {ref["path"]} изменился.' if valid else f'Источник {ref["path"]} недоступен.'
                        self._mark(db, key, reason)
                        affected.add(key)
            for key in self._dependents(records, affected):
                self._mark(db, key, 'Изменилось транзитивное основание; требуется повторная проверка.')
            return {'affected': sorted(affected), 'dependent': sorted(self._dependents(records, affected))}

    def acknowledge(self, record_id, payload):
        with self.connection() as db:
            record = self._load(db, record_id)
            if type(payload.get('revision')) is not int or payload['revision'] != record['revision'] or not isinstance(payload.get('evidence'), str) or not payload['evidence'].strip():
                raise ValueError('Нужны текущая версия и свидетельство повторной проверки.')
            # Cannot clear stale evidence by checking a box. Repair pinned references first.
            for ref in record['basis']:
                if ref['type'] == 'source':
                    path = self.root / ref['path']
                    if not path.resolve().is_relative_to(self.root) or not path.is_file() or digest(path.read_bytes()) != ref['sha256']:
                        raise ValueError('Сначала обновите версию источника в новой редакции записи.')
                elif self._load(db, ref['id'])['revision'] != ref['revision'] or db.execute('SELECT 1 FROM rechecks WHERE id=?', (ref['id'],)).fetchone():
                    raise ValueError('Основание ещё требует проверки или ссылка относится к старой версии.')
            db.execute('DELETE FROM rechecks WHERE id=?', (record_id,))
            db.execute('INSERT INTO events(at,event) VALUES (?,?)', (timestamp(), json.dumps(
                {'type': 'recheck', 'id': record_id, 'revision': record['revision'], 'evidence': payload['evidence']}, ensure_ascii=False)))
        return self.get(record_id)

    def list(self):
        self.audit()
        with self.connection() as db:
            records = self._latest(db)
            flags = {row['id']: json.loads(row['reasons']) for row in db.execute('SELECT * FROM rechecks')}
            for key, record in records.items():
                record['recheck_reasons'] = flags.get(key, [])
                record['effective_status'] = 'needs_recheck' if key in flags else record['status']
            return {'records': list(records.values()), 'rechecks': flags,
                    'events': [json.loads(row[0]) for row in db.execute('SELECT event FROM events ORDER BY seq DESC LIMIT 100')]}

    def assemble(self, payload):
        ids, goal, budget = payload.get('ids'), payload.get('goal'), payload.get('budget', 12000)
        if not isinstance(ids, list) or not 1 <= len(ids) <= 30 or any(not isinstance(key, str) for key in ids) or not isinstance(goal, str) or not goal.strip() or len(goal) > 3000 or type(budget) is not int or not 500 <= budget <= 100000:
            raise ValueError('Выберите 1–30 записей, цель и бюджет 500–100000 символов.')
        self.audit()
        included, visited, missing, flags = [], set(), [], []
        with self.connection() as db:
            def include(key, revision=None):
                try:
                    record = self._load(db, key, revision)
                except FileNotFoundError:
                    missing.append(key)
                    return
                marker = (key, record['revision'])
                if marker in visited:
                    return
                visited.add(marker)
                for ref in record['basis']:
                    if ref['type'] == 'record':
                        include(ref['id'], ref['revision'])
                if db.execute('SELECT 1 FROM rechecks WHERE id=?', (key,)).fetchone():
                    flags.append(key)
                record['current'] = self._load(db, key)['revision'] == record['revision']
                included.append(record)
            for key in ids:
                include(key)
        compiled = compile_context(included, goal)
        context = compiled['context']
        status = 'blocked' if missing or flags or len(context) > budget else 'ready'
        return {**compiled, 'status': status,
                'context': context, 'characters': len(context), 'budget': budget, 'included': [
                    {'id': record['id'], 'revision': record['revision']} for record in included],
                'missing': missing, 'requires_recheck': flags, 'overflow': len(context) > budget,
                'excluded': [], 'need': context_need(status, len(context) > budget, missing, flags),
                'response_instruction': RESPONSE_INSTRUCTION,
                'limits': 'Основания включены по зависимостям. Это проверка сборки, а не доказательство достаточности контекста.'}

    def check_response(self, payload):
        assembly = self.assemble(payload)
        if assembly['status'] != 'ready':
            raise ValueError('Контекст заблокирован: сначала устраните переполнение или пересмотрите основания.')
        if payload.get('assembly_id') != assembly['assembly_id']:
            raise ValueError('Снимок контекста изменился. Соберите его заново перед проверкой ответа.')
        return {'assembly_id': assembly['assembly_id'], **validate_response(payload.get('text'), assembly['references'])}
