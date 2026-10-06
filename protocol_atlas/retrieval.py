"""Local lexical retrieval with whole sections and pinned dependency closure."""
import json
import re
import sqlite3
from pathlib import Path

from protocol_atlas.catalog import _source_paths, parse_document, digest

STOP_WORDS = set('как что это для при или чтобы нужно надо работа задача сделать проверить раздел протокол'.split())


def search_items(items, query, limit=6):
    if not isinstance(query, str) or len(query) > 20000 or type(limit) is not int or not 1 <= limit <= 30:
        raise ValueError('Нужны поисковый текст и предел 1–30 результатов.')
    words = list(dict.fromkeys(w.lower() for w in re.findall(r'[^\W_]{3,}', query, re.UNICODE)
                               if w.lower() not in STOP_WORDS))[:24]
    if not words or not items:
        return []
    # An ephemeral index is rebuilt from the current snapshot, never an old cache.
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE VIRTUAL TABLE search USING fts5(title, body, tokenize="unicode61")')
        db.executemany('INSERT INTO search(rowid,title,body) VALUES (?,?,?)',
                       ((i+1, item.get('title', ''), item['text']) for i, item in enumerate(items)))
        match = ' OR '.join('"'+w+'"*' for w in words)
        rows = db.execute('SELECT rowid,bm25(search,3.0,1.0) score FROM search '
                          'WHERE search MATCH ? ORDER BY score,rowid LIMIT ?', (match, limit)).fetchall()
    return [{**items[i-1], 'score': score, 'reason': 'Совпадения слов; BM25. Смысловая достаточность не установлена.'}
            for i, score in rows]


def source_sections(root):
    items = []
    for path in _source_paths(Path(root)):
        doc = parse_document(path, (Path(root)/path).read_bytes())
        if not doc['path'].endswith('.md') or doc['path'].endswith('REGULATOR_PREVIOUS.md'):
            continue
        if doc['path'] in ('memory/DECISIONS.md', 'memory/ERRORS.md', 'memory/CALIBRATION.md'):
            # Historical documents are available explicitly in memory; a matching
            # archival passage must not silently become an active instruction.
            continue
        if doc['path'] == 'memory/STATE.md':
            items.append({'key': doc['path'], 'title': 'Исходная точка продолжения', 'path': doc['path'],
                          'sha256': doc['sha256'], 'start_line': 1, 'end_line': doc['line_count'],
                          'text': ''.join(b['text'] for b in doc['blocks'])})
            continue
        for section in doc['sections']:
            if any(s['parent_id'] == section['id'] for s in doc['sections']):
                continue
            parent = next((s for s in doc['sections'] if s['id'] == section['parent_id']), None)
            own = [b for b in doc['blocks'] if section['start_line'] <= b['start_line'] <= section['end_line']]
            ancestors = []
            if parent:
                introduction = [b for b in doc['blocks'] if b['section_id'] == parent['id']]
                if introduction:
                    ancestors.append({'type': 'source', 'path': doc['path'], 'sha256': doc['sha256'],
                                      'start_line': introduction[0]['start_line'],
                                      'end_line': introduction[-1]['end_line'],
                                      'quote': ''.join(b['text'] for b in introduction)})
            start, end = section['start_line'], section['end_line']
            lines = ''.join(b['text'] for b in doc['blocks']).splitlines(keepends=True)
            value = ''.join(lines[start-1:end])
            if own and value.strip():
                items.append({'key': doc['path']+':'+section['id'], 'title': section['title'],
                              'path': doc['path'], 'sha256': doc['sha256'], 'start_line': start,
                              'end_line': end, 'text': value, 'ancestors': ancestors})
    return items


def constraints_signature(records):
    return digest(json.dumps(sorted((r['id'], r['revision'], r['effective_status']) for r in records
                                   if r['kind'] == 'constraint' and r['status'] == 'accepted'),
                             ensure_ascii=False).encode())


def retrieve(root, memory, query, ids=None, limit=5, budget=16000):
    ids = [] if ids is None else ids
    if not isinstance(ids, list) or len(ids) > 30 or any(not isinstance(i, str) for i in ids):
        raise ValueError('Выберите до 30 идентификаторов памяти.')
    if type(budget) is not int or not 500 <= budget <= 100000:
        raise ValueError('Бюджет памяти: 500–100000 символов.')
    records = memory.list()['records']
    mandatory = [r['id'] for r in records if r['kind'] == 'constraint' and r['status'] == 'accepted']
    candidates = [{'key': r['id'], 'title': r['title'], 'text': r['statement'] or ''}
                  for r in records if r['effective_status'] != 'needs_recheck'
                  and r['status'] not in ('rejected', 'superseded')]
    matches = search_items(candidates, query, limit)
    selected = list(dict.fromkeys([*mandatory, *ids, *(r['key'] for r in matches)]))
    if len(selected) > 30:
        raise ValueError('Обязательные ограничения и выбранная память превышают 30 записей; уточните организацию.')
    assembly = memory.assemble({'ids': selected, 'goal': query, 'budget': budget}) if selected else None
    if assembly and assembly['status'] != 'ready':
        raise ValueError('Память заблокирована: '+assembly['need']['reason'])
    refs = assembly['references'] if assembly else {}
    documents = source_sections(root)
    source_matches = search_items(documents, query, limit)
    state = next((d for d in documents if d['path'] == 'memory/STATE.md'), None)
    selected_sources = ([{**state, 'reason': 'Исходная точка продолжения; включается независимо от поиска.'}]
                        if state else []) + source_matches
    included, omitted, used, seen = [], [], len(assembly['context']) if assembly else 0, set()
    for item in selected_sources:
        if item['key'] in seen:
            continue
        seen.add(item['key'])
        ref = {'type': 'source', 'path': item['path'], 'sha256': item['sha256'],
               'start_line': item['start_line'], 'end_line': item['end_line'], 'quote': item['text']}
        ancestor_refs = item.get('ancestors', [])
        size = len(json.dumps([ref, *ancestor_refs], ensure_ascii=False))
        if used + size > budget:
            if state and item['key'] == state['key']:
                raise ValueError('Исходная точка и основания не помещаются в бюджет памяти.')
            omitted.append({'title': item['title'], 'reason': 'Целый пункт не помещается; текст не обрезан.'})
            continue
        name = 'd'+str(len(included)+1)
        refs[name] = ref
        for i, ancestor in enumerate(ancestor_refs, 1):
            refs[name+'p'+str(i)] = ancestor
        used += size
        included.append({'ref_id': name, 'title': item['title'], 'reason': item['reason']})
    return {'references': refs, 'memory': assembly, 'included': included, 'omitted': omitted,
            'memory_matches': matches, 'mandatory_ids': mandatory,
            'constraints_signature': constraints_signature(records),
            'characters': used, 'budget': budget, 'method': 'SQLite FTS5 / BM25 + точные зависимости',
            'limits': 'Поиск не устанавливает достаточность и истинность. История не становится действующим решением.'}


def changed_context(root, memory, context):
    if not context:
        return []
    changed = []
    records = {r['id']: r for r in memory.list()['records']}
    if context.get('constraints_signature') != constraints_signature(records.values()):
        changed.append('Изменились действующие ограничения памяти.')
    for ref in context['references'].values():
        if ref['type'] == 'source':
            if ref['path'].startswith('task:'):
                continue
            path = Path(root)/ref['path']
            if path.is_symlink() or not path.resolve().is_relative_to(Path(root).resolve()) or not path.is_file() or digest(path.read_bytes()) != ref['sha256']:
                changed.append('Изменён или недоступен источник '+ref['path'])
        elif ref['type'] == 'record':
            current = records.get(ref['id'])
            if not current or current['revision'] != ref['revision'] or current['effective_status'] == 'needs_recheck':
                changed.append('Изменено основание памяти '+ref['id'])
    return list(dict.fromkeys(changed))
