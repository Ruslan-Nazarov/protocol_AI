"""Persistent reader comments anchored to a quote and the viewed page."""
from __future__ import annotations

from datetime import datetime, timezone
from contextlib import contextmanager
import json
from pathlib import Path
import re
import sqlite3
import uuid


KINDS = ('fix', 'change', 'wording', 'question')
PAGES = {'translate', 'home', 'rules', 'workflow', 'memory', 'records', 'requirements',
         'regulator', 'history', 'labs', 'source', 'search', 'lab-plan', 'comments', 'connections', 'edit'}


class CommentStore:
    def __init__(self, root: Path):
        directory = root.resolve() / 'data'
        if not directory.resolve().is_relative_to(root.resolve()):
            raise ValueError('Хранилище выходит за пределы проекта.')
        directory.mkdir(exist_ok=True)
        self.path = directory / 'comments.sqlite3'
        if self.path.is_symlink():
            raise ValueError('Недопустимая ссылка хранилища.')
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS comments '
                       '(id TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def text(payload, key, limit, required=True):
        value = payload.get(key, '')
        if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
            raise ValueError(f'Некорректное поле {key}: до {limit} символов.')
        return value

    def list(self):
        with self.connect() as db:
            rows = db.execute('SELECT payload FROM comments ORDER BY rowid DESC').fetchall()
        return {'comments': [json.loads(row[0]) for row in rows]}

    def save(self, payload):
        text = self.text(payload, 'text', 12000).strip()
        kind = payload.get('kind', 'change')
        status = payload.get('status', 'open')
        if kind not in KINDS or status not in ('open', 'done'):
            raise ValueError('Неизвестный тип или статус замечания.')
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            # Read and update under the same write lock: simultaneous edits cannot overwrite one another.
            db.execute('BEGIN IMMEDIATE')
            record_id = payload.get('id')
            if record_id is not None:
                if not isinstance(record_id, str):
                    raise ValueError('Некорректное имя замечания.')
                row = db.execute('SELECT payload FROM comments WHERE id=?', (record_id,)).fetchone()
                if not row:
                    raise FileNotFoundError('Замечание не найдено.')
                record = json.loads(row[0])
                if type(payload.get('revision')) is not int or payload['revision'] != record['revision']:
                    raise ValueError('Замечание изменилось. Обновите список перед сохранением.')
                record.update(text=text, kind=kind, status=status, updated_at=now,
                              revision=record['revision'] + 1)
                db.execute('UPDATE comments SET revision=?,payload=? WHERE id=?',
                           (record['revision'], json.dumps(record, ensure_ascii=False), record_id))
            else:
                quote = self.text(payload, 'quote', 12000)
                page = self.text(payload, 'page', 4000)
                if not page.startswith('#') or page[1:].split('?', 1)[0] not in PAGES:
                    raise ValueError('Нужна ссылка на раздел атласа.')
                anchor = payload.get('anchor', {})
                if not isinstance(anchor, dict):
                    raise ValueError('Некорректное место выделения.')
                offset = anchor.get('offset', 0)
                if type(offset) is not int or not 0 <= offset <= 10_000_000:
                    raise ValueError('Некорректное положение цитаты.')
                anchor = {'offset': offset,
                          'prefix': self.text(anchor, 'prefix', 160, False),
                          'suffix': self.text(anchor, 'suffix', 160, False),
                          'element_id': self.text(anchor, 'element_id', 160, False),
                          'field': bool(anchor.get('field', False))}
                source = payload.get('source')
                if source is not None:
                    if not isinstance(source, dict):
                        raise ValueError('Некорректный источник.')
                    path = self.text(source, 'path', 300)
                    sha = self.text(source, 'sha256', 64)
                    line = source.get('line', 1)
                    if (not re.fullmatch(r'[0-9a-f]{64}', sha) or type(line) is not int or line < 1
                            or path.startswith(('/', '\\')) or '..' in path.replace('\\', '/').split('/')):
                        raise ValueError('Некорректная версия или строка источника.')
                    source = {'path': path, 'sha256': sha, 'line': line}
                record = {'id': uuid.uuid4().hex, 'revision': 1, 'quote': quote,
                          'text': text, 'kind': kind, 'status': status, 'page': page,
                          'page_title': self.text(payload, 'page_title', 500),
                          'language': 'en' if payload.get('language') == 'en' else 'ru',
                          'catalog_revision': self.text(payload, 'catalog_revision', 64, False),
                          'anchor': anchor, 'source': source, 'created_at': now, 'updated_at': now}
                db.execute('INSERT INTO comments VALUES (?,?,?)',
                           (record['id'], 1, json.dumps(record, ensure_ascii=False)))
        return record
