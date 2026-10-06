"""Compact translation changes and lossless legacy backup migration."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid
import zlib

from protocol_atlas.catalog import digest


UI_PATH = '@ui'


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def fragment(value):
    return {key: value.get(key) for key in (
        'source', 'translation', 'translated_source', 'translated_source_sha256', 'source_sha256')}


def fragments(document, ui=False):
    return {u['id' if ui else 'unit_id']: fragment(u)
            for u in document.get('entries' if ui else 'units', [])}


class TranslationHistory:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.folder = self.root / 'data/translation-history'
        self.path = self.folder / 'history.sqlite3'

    @contextmanager
    def db(self):
        if self.folder.is_symlink() or self.path.is_symlink() or not self.path.resolve().is_relative_to(self.root):
            raise ValueError('Недопустимый путь истории переводов.')
        self.folder.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS objects (sha TEXT PRIMARY KEY, body BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY, path TEXT NOT NULL, at TEXT NOT NULL, kind TEXT NOT NULL,
                    before_revision TEXT NOT NULL, after_revision TEXT NOT NULL, status TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS changes (
                    event_id TEXT NOT NULL, unit_id TEXT NOT NULL, before_sha TEXT, after_sha TEXT,
                    PRIMARY KEY(event_id, unit_id));
                CREATE TABLE IF NOT EXISTS legacy_files (
                    sha TEXT PRIMARY KEY, filename TEXT UNIQUE NOT NULL, path TEXT NOT NULL,
                    at TEXT NOT NULL, body BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS legacy_versions (
                    path TEXT NOT NULL, unit_id TEXT NOT NULL, object_sha TEXT NOT NULL,
                    file_sha TEXT NOT NULL, at TEXT NOT NULL,
                    PRIMARY KEY(path, unit_id, object_sha));
                CREATE INDEX IF NOT EXISTS events_path ON events(path);
                CREATE INDEX IF NOT EXISTS changes_unit ON changes(unit_id);
            ''')
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def put(db, value):
        if value is None:
            return None
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
        sha = digest(raw)
        if db.execute('SELECT 1 FROM objects WHERE sha=?', (sha,)).fetchone() is None:
            db.execute('INSERT INTO objects VALUES (?,?)', (sha, zlib.compress(raw, 9)))
        return sha

    @staticmethod
    def get(db, sha):
        if sha is None:
            return None
        row = db.execute('SELECT body FROM objects WHERE sha=?', (sha,)).fetchone()
        if row is None:
            raise FileNotFoundError('Фрагмент истории не найден.')
        raw = zlib.decompress(row[0])
        if digest(raw) != sha:
            raise ValueError('Повреждён фрагмент истории переводов.')
        return json.loads(raw)

    def record(self, path, before, after, before_revision, after_revision, batch_id=None):
        old, new = fragments(before, path == UI_PATH), fragments(after, path == UI_PATH)
        changed = [key for key in sorted(old.keys() | new.keys()) if old.get(key) != new.get(key)]
        if not changed:
            return None
        ident = (batch_id + ':' + path) if batch_id else uuid.uuid4().hex
        with self.db() as db:
            existing = db.execute('SELECT * FROM events WHERE id=?', (ident,)).fetchone()
            if existing and (existing['status'] != 'applied' or existing['after_revision'] != before_revision):
                raise ValueError('Пакетная операция прервана или перевод изменён другим автором.')
            db.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                       'after_revision=excluded.after_revision,status=excluded.status',
                       (ident, path, timestamp(), 'batch' if batch_id else 'edit', before_revision, after_revision, 'pending'))
            for key in changed:
                db.execute('INSERT INTO changes VALUES (?,?,?,?) ON CONFLICT(event_id,unit_id) '
                           'DO UPDATE SET after_sha=excluded.after_sha',
                           (ident, key, self.put(db, old.get(key)), self.put(db, new.get(key))))
        return ident

    def checkpoint(self, path, batch_id):
        if not batch_id or not self.path.is_file():
            return None
        with self.db() as db:
            ident=batch_id+':'+path
            event=db.execute('SELECT * FROM events WHERE id=?',(ident,)).fetchone()
            if event is None:return None
            changes=list(db.execute('SELECT * FROM changes WHERE event_id=?',(ident,)))
            return (tuple(event),[tuple(row) for row in changes])

    def revert_checkpoint(self, ident, checkpoint):
        with self.db() as db:
            db.execute('DELETE FROM changes WHERE event_id=?',(ident,))
            db.execute('DELETE FROM events WHERE id=?',(ident,))
            db.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?)',checkpoint[0])
            db.executemany('INSERT INTO changes VALUES (?,?,?,?)',checkpoint[1])

    def mark(self, ident, status):
        if ident:
            with self.db() as db:
                db.execute('UPDATE events SET status=? WHERE id=?', (status, ident))

    def recover(self, path, current_revision):
        if not self.path.is_file():
            return
        with self.db() as db:
            db.execute("UPDATE events SET status='applied' WHERE path=? AND status='pending' AND after_revision=?",
                       (path, current_revision))

    def versions(self, path, unit_id):
        if not self.path.is_file():
            return []
        with self.db() as db:
            result = []
            for row in db.execute("SELECT e.*,c.before_sha,c.after_sha FROM changes c JOIN events e ON e.id=c.event_id "
                                  "WHERE e.path=? AND c.unit_id=? AND e.status='applied' ORDER BY e.at DESC", (path, unit_id)):
                for side in ('after', 'before'):
                    sha = row[side + '_sha']
                    if sha is not None:
                        result.append({'version': row['id'] + ':' + side, 'at': row['at'], 'kind': row['kind'],
                                       'side': side, 'value': self.get(db, sha)})
            for row in db.execute('SELECT * FROM legacy_versions WHERE path=? AND unit_id=? ORDER BY at DESC', (path, unit_id)):
                result.append({'version': 'legacy:' + row['object_sha'], 'at': row['at'], 'kind': 'legacy',
                               'side': 'before', 'archive_sha':row['file_sha'], 'value': self.get(db, row['object_sha'])})
            # Identical fragment contents need one selectable version, even if present in many runs.
            seen, unique = set(), []
            for item in result:
                key = json.dumps(item['value'], sort_keys=True, ensure_ascii=False)
                if key not in seen:
                    seen.add(key)
                    unique.append(item)
            return unique

    def migration(self, remove=False, before_remove=None):
        report = {'files': 0, 'original_bytes': 0, 'verified_files': 0, 'removed_files': 0}
        originals = []
        if not self.folder.is_dir():
            return report
        for path in sorted(self.folder.glob('*.json')):
            if path.is_symlink() or not path.resolve().is_relative_to(self.folder.resolve()):
                raise ValueError('Недопустимая ссылка в старой истории переводов.')
            raw = path.read_bytes()
            document = json.loads(raw)
            key = document.get('path') or (UI_PATH if 'entries' in document else None)
            if not isinstance(key, str) or not isinstance(document.get('entries' if key == UI_PATH else 'units'), list):
                raise ValueError('Неизвестный формат старой копии: ' + path.name)
            sha, at = digest(raw), datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
            with self.db() as db:
                db.execute('INSERT OR IGNORE INTO legacy_files VALUES (?,?,?,?,?)',
                           (sha, path.name, key, at, zlib.compress(raw, 9)))
                rows = document.get('entries' if key == UI_PATH else 'units', []) + document.get('archived', [])
                for value in rows:
                    unit_id = value.get('id' if key == UI_PATH else 'unit_id')
                    if not isinstance(unit_id, str):
                        raise ValueError('Старая копия содержит фрагмент без идентификатора.')
                    obj = self.put(db, fragment(value))
                    db.execute('INSERT OR IGNORE INTO legacy_versions VALUES (?,?,?,?,?)', (key, unit_id, obj, sha, at))
            originals.append((path, sha))
            report['files'] += 1
            report['original_bytes'] += len(raw)
        # Verify every archived byte before removing even the first original.
        with self.db() as db:
            for path, sha in originals:
                row = db.execute('SELECT body,filename FROM legacy_files WHERE sha=?', (sha,)).fetchone()
                if row is None or row['filename'] != path.name or digest(zlib.decompress(row['body'])) != sha:
                    raise ValueError('Архивная копия не прошла проверку: ' + path.name)
                if digest(path.read_bytes()) != sha:
                    raise ValueError('Старая копия изменилась во время переноса: ' + path.name)
                report['verified_files'] += 1
        if remove:
            if before_remove:
                before_remove()
            for path, sha in originals:
                if digest(path.read_bytes()) != sha:
                    raise ValueError('Старая копия изменилась перед удалением: ' + path.name)
                path.unlink()
                report['removed_files'] += 1
        report['database_bytes'] = self.path.stat().st_size if self.path.is_file() else 0
        return report

    def statistics(self):
        if not self.path.is_file():
            return {'bytes':0,'edits':0,'legacy_files':0}
        with self.db() as db:
            return {'bytes':self.path.stat().st_size,
                    'edits':db.execute("SELECT count(*) FROM events WHERE status='applied'").fetchone()[0],
                    'legacy_files':db.execute('SELECT count(*) FROM legacy_files').fetchone()[0]}

    def export_legacy(self, sha):
        with self.db() as db:
            row = db.execute('SELECT filename,body FROM legacy_files WHERE sha=?', (sha,)).fetchone()
            if row is None:
                raise FileNotFoundError('Архивная копия не найдена.')
            raw = zlib.decompress(row['body'])
            if digest(raw) != sha:
                raise ValueError('Архивная копия повреждена.')
            return row['filename'], raw
