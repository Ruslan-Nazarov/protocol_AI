"""Linked English translations; source changes never silently approve old text."""
from __future__ import annotations

from difflib import SequenceMatcher
import json
import re
import os
from pathlib import Path
import tempfile
import threading

from protocol_atlas.catalog import digest, parse_document
from protocol_atlas.source_editor import SourceConflict
from protocol_atlas.ui_messages import ui_sources
from protocol_atlas.translation_history import TranslationHistory, UI_PATH


def normalize(text):
    return text.replace('\r\n', '\n')


def fingerprint(text):
    return digest(normalize(text).encode('utf-8'))


def preserve_identifiers(source, translated):
    """Rule codes are opaque references to the Russian source, in either language."""
    letters={'А':'A','К':'K','Ф':'F','Л':'L','П':'P','Р':'R'}
    identifiers=sorted(set(re.findall(r'(?<!\w)[А-ЯЁ]\.\d+(?:\.\d+)*[а-я]?',source)),key=len,reverse=True)
    for identifier in identifiers:
        latin=letters.get(identifier[0],identifier[0])+identifier[1:].translate(str.maketrans({'а':'a','б':'b','в':'v'}))
        translated=re.sub(r'(?<!\w)'+re.escape(latin)+r'(?!\w|\.\d)',lambda _:identifier,translated)
    for letter,latin in letters.items():
        if re.search(r'(?<!\w)'+letter+r'(?!\w)',source):
            translated=re.sub(r'(?i)\b(form|section|architecture)\s+'+re.escape(latin)+r'\b',lambda m:m[1]+' '+letter,translated)
    heading=re.match(r'^(\ufeff?#{1,6}\s+)([А-ЯЁ])\.\s',source)
    if heading:
        letter=heading[2];latin=letters.get(letter,letter)
        translated=re.sub(r'^(#{1,6}\s+)'+re.escape(latin)+r'\.\s',lambda m:m[1]+letter+'. ',translated)
    for letter,latin in letters.items():
        if '('+letter+')' in source:translated=translated.replace('('+latin+')','('+letter+')')
    # A batch response may omit the unit's final newline. Keep document assembly lossless.
    suffix=len(source)-len(source.rstrip('\n'))
    return translated.rstrip('\n')+'\n'*suffix


def document_paths(root):
    return sorted({'PROTOCOL.md', 'README.md'} | {
        p.relative_to(root).as_posix() for folder in ('memory', 'docs')
        for p in (root / folder).glob('*.md')})


def align_units(old, blocks):
    """Keep identities across insertions; changed text keeps an explicit old basis."""
    result = []
    matcher = SequenceMatcher(a=[normalize(u['source']) for u in old],
                              b=[normalize(b['text']) for b in blocks], autojunk=False)
    for kind, a, b, c, d in matcher.get_opcodes():
        for offset, block in enumerate(blocks[c:d]):
            prior = old[a + offset] if kind == 'equal' or (kind == 'replace' and b-a == d-c) else None
            source = normalize(block['text'])
            unit = {**block, 'source': source, 'source_sha256': fingerprint(source),
                    'unit_id': prior['unit_id'] if prior else f"u-{block['start_line']}-{fingerprint(source)[:14]}",
                    'translation': prior.get('translation', '') if prior else '',
                    'translated_source': prior.get('translated_source', prior['source']) if prior else '',
                    'translated_source_sha256': prior.get('translated_source_sha256') if prior else None}
            if not source.strip() or block['kind'] == 'separator':
                unit.update(translation=source, translated_source=source,
                            translated_source_sha256=unit['source_sha256'])
            unit['status'] = ('current' if unit['translated_source_sha256'] == unit['source_sha256']
                              else 'stale' if unit['translation'] else 'missing')
            result.append(unit)
    return result


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write((json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


class TranslationStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.lock = threading.RLock()
        self.history_store = TranslationHistory(self.root)

    def target(self, path):
        if not isinstance(path, str) or path not in document_paths(self.root):
            raise ValueError('Документ отсутствует в списке переводов.')
        source = self.root / path
        translated = self.root / 'locales/en/documents' / (path + '.json')
        if source.is_symlink() or translated.is_symlink() or not source.resolve().is_relative_to(self.root) or not translated.resolve().is_relative_to(self.root):
            raise ValueError('Недопустимый путь перевода.')
        return source, translated

    def read(self, path):
        source, target = self.target(path)
        document = parse_document(path, source.read_bytes())
        raw = target.read_bytes() if target.is_file() else None
        old = json.loads(raw.decode('utf-8')) if raw is not None else {'units': []}
        units = align_units(old['units'], document['blocks'])
        return {'path': path, 'source_sha256': document['sha256'],
                'revision': digest(raw) if raw is not None else 'new',
                'units': units, 'pending': sum(u['status'] != 'current' for u in units),
                'archived': old.get('archived', [])}

    def save(self, payload):
        with self.lock:
            current = self.read(payload.get('path'))
            if payload.get('revision') != current['revision'] or payload.get('source_sha256') != current['source_sha256']:
                raise SourceConflict('Оригинал или перевод изменился. Обновите список фрагментов; черновик перевода остаётся в редакторе.')
            unit = next((u for u in current['units'] if u['unit_id'] == payload.get('unit_id')), None)
            text = payload.get('translation')
            if not unit or not isinstance(text, str) or not text.strip() or len(text) > 80000 or '\0' in text:
                raise ValueError('Выберите фрагмент и введите английский перевод.')
            # Translation is data, never an instruction; no source file is rewritten.
            unit.update(translation=normalize(text), translated_source=unit['source'],
                        translated_source_sha256=unit['source_sha256'], status='current')
            source, target = self.target(current['path'])
            latest = target.read_bytes() if target.is_file() else None
            if digest(source.read_bytes()) != current['source_sha256'] or (digest(latest) if latest is not None else 'new') != current['revision']:
                raise SourceConflict('Оригинал или перевод изменился во время сохранения. Обновите фрагменты.')
            if normalize(text) == next((u.get('translation') for u in json.loads(latest or b'{}').get('units', []) if u['unit_id'] == unit['unit_id']), None) and next((u.get('translated_source_sha256') for u in json.loads(latest or b'{}').get('units', []) if u['unit_id'] == unit['unit_id']), None) == unit['source_sha256']:
                return self.read(current['path'])
            self.save_document(current)
            return self.read(current['path'])

    def ui(self):
        target=self.root/'locales/en/ui.json'
        raw=target.read_bytes() if target.is_file() else None
        old=json.loads(raw.decode('utf-8')) if raw is not None else {'entries': []}
        known={e['source']:e for e in old['entries']}
        entries=[{**known.get(source, {'id':fingerprint(source),'source':source,'translation':'','source_sha256':fingerprint(source)}),
                  'status':'current' if known.get(source,{}).get('translation') else 'missing'} for source in ui_sources(self.root)]
        return {'entries':entries,'pending':sum(e['status']!='current' for e in entries),
                'revision':digest(raw) if raw is not None else 'new'}

    def save_ui(self,payload):
        with self.lock:
            current=self.ui()
            if payload.get('revision')!=current['revision']:
                raise SourceConflict('Словарь изменился. Обновите список; черновик остаётся в редакторе.')
            entry=next((e for e in current['entries'] if e['id']==payload.get('id')),None)
            text=payload.get('translation')
            if not entry or not isinstance(text,str) or not text.strip() or len(text)>80000 or '\0' in text:
                raise ValueError('Выберите текст интерфейса и введите перевод.')
            entry.update(translation=normalize(text),status='current')
            target=self.root/'locales/en/ui.json'
            if target.is_symlink() or not target.resolve().is_relative_to(self.root):raise ValueError('Недопустимый путь словаря.')
            if target.is_file() and normalize(text) == next((e.get('translation') for e in json.loads(target.read_bytes()).get('entries', []) if e['id']==entry['id']), None):
                return self.ui()
            self.save_ui_batch(current)
            return self.ui()

    def _commit(self, path, target, value, revision, batch_id=None):
        if target.is_symlink() or not target.resolve().is_relative_to(self.root):
            raise ValueError('Недопустимый путь перевода.')
        raw = target.read_bytes() if target.is_file() else None
        actual = digest(raw) if raw is not None else 'new'
        if actual != revision:
            raise SourceConflict('Перевод изменился во время сохранения.')
        after = (json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode()
        if raw == after:
            return
        self.history_store.recover(path, actual)
        checkpoint = self.history_store.checkpoint(path, batch_id)
        event = self.history_store.record(path, json.loads(raw) if raw else {}, value, actual, digest(after), batch_id)
        try:
            write_json(target, value)
        except Exception:
            if checkpoint and event:
                self.history_store.revert_checkpoint(event, checkpoint)
            else:
                self.history_store.mark(event, 'failed')
            raise
        self.history_store.mark(event, 'applied')

    def save_document(self, document, batch_id=None):
        with self.lock:
            current = self.read(document['path'])
            if current['revision'] != document['revision'] or current['source_sha256'] != document['source_sha256']:
                raise SourceConflict('Оригинал или перевод изменился во время пакетной работы.')
            source, target = self.target(document['path'])
            old = json.loads(target.read_bytes()) if target.is_file() else {'units': []}
            retained = {u['unit_id'] for u in document['units']}
            archived = {u['unit_id']:u for u in document.get('archived', [])}
            archived.update({u['unit_id']:u for u in old['units'] if u['unit_id'] not in retained})
            value = {'schema_version':1, 'path':document['path'], 'units':document['units'], 'archived':list(archived.values())}
            if digest(source.read_bytes()) != document['source_sha256']:
                raise SourceConflict('Оригинал изменился во время сохранения.')
            self._commit(document['path'], target, value, document['revision'], batch_id)
            return self.read(document['path'])

    def save_ui_batch(self, current, batch_id=None):
        with self.lock:
            self._commit(UI_PATH, self.root/'locales/en/ui.json', {'schema_version':1,'entries':current['entries']}, current['revision'], batch_id)
            return self.ui()

    def history(self, path, unit_id):
        current = self.ui() if path == UI_PATH else self.read(path)
        units = current['entries'] if path == UI_PATH else current['units']
        if not any(u.get('id' if path == UI_PATH else 'unit_id') == unit_id for u in units):
            raise ValueError('Фрагмент не найден.')
        self.history_store.recover(path, current['revision'])
        return {'versions':self.history_store.versions(path, unit_id)}

    def restore(self, payload):
        with self.lock:
            path, unit_id = payload.get('path'), payload.get('unit_id')
            current = self.ui() if path == UI_PATH else self.read(path)
            if payload.get('revision') != current['revision'] or (path != UI_PATH and payload.get('source_sha256') != current['source_sha256']):
                raise SourceConflict('Оригинал или перевод изменился. Обновите историю.')
            versions = self.history(path, unit_id)['versions']
            selected = next((v['value'] for v in versions if v['version'] == payload.get('version')), None)
            if selected is None:
                raise ValueError('Версия не найдена.')
            unit = next(u for u in current['entries' if path == UI_PATH else 'units'] if u['id' if path == UI_PATH else 'unit_id'] == unit_id)
            if path == UI_PATH:
                if selected['source'] != unit['source']:
                    raise ValueError('Версия относится к другой подписи.')
                unit['translation'] = selected['translation'] or ''
                return self.save_ui_batch(current)
            unit.update(translation=selected['translation'] or '', translated_source=selected['translated_source'] or selected['source'], translated_source_sha256=selected['translated_source_sha256'])
            return self.save_document(current)

    def bundle(self):
        docs = [self.read(path) for path in document_paths(self.root)]
        return {'ui': self.ui(), 'documents': docs, 'history':self.history_store.statistics()}
