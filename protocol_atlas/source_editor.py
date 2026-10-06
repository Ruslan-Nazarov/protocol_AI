"""Edit registered Markdown sources with revision checks and original snapshots."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import threading

from protocol_atlas.catalog import _source_paths, digest, parse_document


class SourceConflict(ValueError):
    pass


class SourceEditor:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.lock = threading.RLock()

    def target(self, path):
        allowed=set(_source_paths(self.root))|{'README.md'}|{p.relative_to(self.root).as_posix() for p in (self.root/'docs').glob('*.md')}
        if not isinstance(path, str) or path not in allowed or not path.endswith('.md') or not (self.root/path).is_file():
            raise ValueError('Редактировать можно только Markdown-документы из каталога.')
        target = self.root / path
        if target.is_symlink() or not target.resolve().is_relative_to(self.root):
            raise ValueError('Недопустимый путь документа.')
        return target

    def read(self,path):
        return parse_document(path,self.target(path).read_bytes())

    def preview(self, payload):
        path, text = payload.get('path'), payload.get('text')
        self.target(path)
        if not isinstance(text, str) or len(text) > 80000 or '\0' in text:
            raise ValueError('Документ должен содержать до 80 000 символов без нулевых байтов.')
        return parse_document(path, text.encode('utf-8'))

    def save(self, payload):
        self.preview(payload)
        target = self.target(payload['path'])
        with self.lock:
            raw = target.read_bytes()
            sha = digest(raw)
            if payload.get('expected_sha256') != sha:
                raise SourceConflict('Документ изменился после открытия редактора. Ваш черновик сохранён на экране; перечитайте актуальный файл перед заменой.')
            text = payload['text'].replace('\r\n', '\n')
            if b'\r\n' in raw and b'\n' not in raw.replace(b'\r\n', b''):
                text = text.replace('\n', '\r\n')
            updated = text.encode('utf-8')
            if updated == raw:
                return {'document': parse_document(payload['path'], raw), 'changed': False}
            archive = self.root / 'data/source-history'
            if not archive.resolve().is_relative_to(self.root):
                raise ValueError('Каталог резервных копий выходит за пределы проекта.')
            archive.mkdir(parents=True, exist_ok=True)
            backup = archive / (sha + '.md')
            if backup.is_symlink():
                raise ValueError('Недопустимая ссылка резервной копии.')
            try:
                with backup.open('xb') as stream:
                    stream.write(raw)
            except FileExistsError:
                if backup.read_bytes() != raw:
                    raise ValueError('Резервная копия повреждена. Сохранение остановлено.')
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
                    temp_path = Path(stream.name)
                    stream.write(updated)
                    stream.flush()
                    os.fsync(stream.fileno())
                if digest(target.read_bytes()) != sha:
                    raise SourceConflict('Документ изменился во время сохранения. Ваш черновик остаётся в редакторе.')
                os.replace(temp_path, target)
            finally:
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)
            return {'document': parse_document(payload['path'], updated), 'changed': True,
                    'backup': backup.relative_to(self.root).as_posix()}
