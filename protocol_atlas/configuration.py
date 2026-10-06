"""Explicitly selected current settings; no author memory, keys or run history."""
import json
from pathlib import Path
import sqlite3


def latest(root, filename, table):
    root = Path(root).resolve()
    path = root/'data'/filename
    if not path.is_file():
        return None
    if path.is_symlink() or path.parent.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError('Недопустимое хранилище настройки.')
    db = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)
    try:
        exists = db.execute('SELECT 1 FROM sqlite_master WHERE type="table" AND name=?', (table,)).fetchone()
        row = db.execute('SELECT body FROM '+table+' ORDER BY revision DESC LIMIT 1').fetchone() if exists else None
        return json.loads(row[0]) if row else None
    finally:
        db.close()


def current_configuration(root):
    root = Path(root)
    settings = latest(root, 'adaptive.sqlite3', 'profile')
    reader = latest(root, 'reader.sqlite3', 'profiles')
    if not settings and not reader:
        path = root/'.protocol/configuration.json'
        if path.is_file():
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError('Недопустимая настройка подключения.')
            value = json.loads(path.read_text(encoding='utf-8'))
            if value.get('schema_version') != 1:
                raise ValueError('Неизвестная версия настройки.')
            return value
        return None
    return {'schema_version': 1,
            'settings': {k: settings[k] for k in ('revision', 'purpose', 'requirements', 'starting_point', 'character_budget', 'known_terms') if k in settings} if settings else None,
            'reader': {k: reader[k] for k in ('revision', 'areas', 'language', 'preferences', 'terms', 'policy', 'decision', 'assessed') if k in reader} if reader else None,
            'scope': 'Текущие подтверждённые настройки пользователя. Память рабочих задач принадлежит рабочему проекту.'}
