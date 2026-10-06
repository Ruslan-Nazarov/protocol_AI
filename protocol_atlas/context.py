"""Exact, versioned context and typed references. Validation does not prove meaning."""
import hashlib
import json

RESPONSE_INSTRUCTION = '''Верни JSON с claims. Каждый элемент имеет один из типов:
record: {"type":"record","ref_id":"r1"} — выбрать существующую запись, без нового текста или статуса.
source: {"type":"source","ref_id":"s1","quote":"точная непустая цитата из quote"}.
inference: {"type":"inference","text":"вывод","basis_refs":["r1"],"scope":null,"uncertainties":null}.
proposal: {"type":"proposal","text":"предложение","basis_refs":[],"need":null}.
unknown: {"type":"unknown","text":"что неизвестно"}.
Ссылки выбирай только из references. Не переписывай пути, версии или статус записи.
Неизвестную область/потребность оставь null. Новое предложение не становится принятым решением.
Проверка ссылок не доказывает истинность вывода. Корневой ответ: {"claims":[...]}.
'''


def compile_context(records, goal):
    record_refs = {(r['id'], r['revision']): f'r{i+1}' for i, r in enumerate(records)}
    refs, source_refs = {}, {}
    for record in records:
        key = record_refs[(record['id'], record['revision'])]
        basis = []
        for ref in record.get('basis', []):
            if ref['type'] == 'record':
                target = record_refs.get((ref['id'], ref['revision']))
                if target:
                    basis.append(target)
            else:
                signature = (ref['path'], ref['sha256'], ref['start_line'], ref['end_line'], ref['quote'])
                if signature not in source_refs:
                    name = f's{len(source_refs)+1}'
                    source_refs[signature] = name
                    refs[name] = {**ref, 'type': 'source'}
                basis.append(source_refs[signature])
        item = {field: record.get(field) for field in ('id', 'revision', 'title', 'kind', 'status', 'statement', 'need', 'transition', 'scope', 'verification')}
        item.update(type='record', basis_refs=basis, current=record.get('current', True))
        # Imported text often equals its source quote. Transmit it once, losslessly.
        for name in basis:
            if refs.get(name, {}).get('type') == 'source' and item['statement'] == refs[name]['quote'].strip():
                item.pop('statement')
                item.update(statement_from_source=name, strip_source=True)
                break
        refs[key] = item
    groups = {'accepted': [], 'source_material': [], 'proposals_and_hypotheses': [], 'historical_or_rejected': []}
    for name, item in refs.items():
        if item['type'] != 'record':
            continue
        if item['current'] is False or item['status'] in ('rejected', 'superseded'):
            group = 'historical_or_rejected'
        elif item['kind'] == 'hypothesis' or item['status'] in ('proposed', 'hypothesis'):
            group = 'proposals_and_hypotheses'
        elif item['status'] == 'accepted':
            group = 'accepted'
        else:
            group = 'source_material'
        groups[group].append(name)
    value = {'goal': goal, 'groups': groups, 'references': refs,
             'limits': 'accepted — сохранённый статус записи, не новая проверка истины. Материалы источников не означают одобрение. Гипотезы и предложения не заменяют решения. История не стирается; неизвестные поля остаются null.'}
    context = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    return {'context': context, 'references': refs, 'groups': groups,
            'assembly_id': hashlib.sha256(context.encode()).hexdigest()}


def episode_context(material, records):
    """Compile only the explicitly authored selection; no rubric-based retrieval."""
    selected = []
    for i, record in enumerate(records):
        basis = record['basis']
        quote = record['statement']
        src = next((s for s in material['sources'] if s['path'] == basis['path'] and s['sha256'] == basis['sha256'] and quote in s['text']), None)
        if src is None:
            raise ValueError('Учебная запись должна быть точной выдержкой снимка.')
        start = src.get('start_line', 1) + src['text'][:src['text'].index(quote)].count('\n')
        selected.append({**record, 'id': record.get('id', f'episode-record-{i+1}'), 'revision': 1,
            'kind': record.get('kind', 'observation'), 'status': record.get('status', 'imported'), 'current': None,
            'basis': [{'type':'source','path':src['path'],'sha256':src['sha256'],
                       'start_line':start,'end_line':start+len(quote.splitlines())-1,'quote':quote}]})
    return compile_context(selected, 'Ответить на задания продолжения только по сохранённым данным.')


def evidence_references(updates):
    return {f'u{i+1}': {'type':'source','path':s['path'],'sha256':s['sha256'],
                       'start_line':s.get('start_line',1),'end_line':s.get('end_line',len(s['text'].splitlines())),
                       'quote':s['text']} for i,s in enumerate(updates)}


def context_need(status, overflow, missing, flags):
    if missing or flags:
        action, reason = 'revise_basis', 'Есть отсутствующее или устаревшее основание. Сначала восстановить источник или пересмотреть зависимые записи.'
    elif overflow:
        action, reason = 'reduce_selection', 'Точная память превышает бюджет. Уточнить нужные записи или увеличить бюджет; основания и условия не обрезаются.'
    else:
        action, reason = 'use_exact', 'Точная память помещается в бюджет. По размеру вызов модели для сжатия не требуется; смысловую достаточность проверяют отдельно.'
    return {'action': action, 'reason': reason, 'compression_needed_by_size': overflow,
            'automatic_model_calls': 0, 'status': status}


def validate_response(text, references, tasks=None):
    if not isinstance(text, str) or not 0 < len(text) <= 80000:
        raise ValueError('Ожидается ответ JSON длиной 1–80000 символов.')
    try:
        value = json.loads(text)
    except ValueError:
        raise ValueError('Ответ должен быть JSON без Markdown.') from None
    if not isinstance(value, dict):
        raise ValueError('Ответ должен быть объектом.')

    def reference(name, expected=None):
        if not isinstance(name, str) or name not in references:
            raise ValueError('Неизвестный идентификатор ссылки.')
        ref = references[name]
        if expected and ref['type'] != expected:
            raise ValueError('Тип ссылки не соответствует утверждению.')
        return ref

    def bases(names, required=False):
        if not isinstance(names, list) or len(names) > 30 or (required and not names):
            raise ValueError('Для вывода нужен непустой список оснований; максимум 30 ссылок.')
        for name in names:
            reference(name)
        return names

    def claims(items):
        if not isinstance(items, list) or not 1 <= len(items) <= 40:
            raise ValueError('Нужно 1–40 утверждений.')
        output = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError('Утверждение должно быть объектом.')
            kind = item.get('type')
            allowed = {'record': {'type','ref_id'}, 'source': {'type','ref_id','quote'},
                       'inference': {'type','text','basis_refs','scope','uncertainties'},
                       'proposal': {'type','text','basis_refs','need'}, 'unknown': {'type','text'}}
            if not isinstance(kind, str) or kind not in allowed or set(item) != allowed[kind]:
                raise ValueError('Неверные поля утверждения: статус и пути не задаются моделью.')
            if kind == 'record':
                ref = dict(reference(item['ref_id'], 'record'))
                if 'statement_from_source' in ref:
                    source = reference(ref['statement_from_source'], 'source')
                    ref['statement'] = source['quote'].strip() if ref.get('strip_source') else source['quote']
                output.append({'type': kind, 'ref_id': item['ref_id'], 'record': ref})
            elif kind == 'source':
                ref = reference(item['ref_id'], 'source')
                quote = item['quote']
                if not isinstance(quote, str) or not quote.strip() or quote not in ref['quote']:
                    raise ValueError('Цитата должна точно входить в сохранённый фрагмент.')
                output.append({'type': kind, 'ref_id': item['ref_id'], 'quote': quote,
                               'source': {k: ref[k] for k in ('path','sha256','start_line','end_line')},
                               'status': 'source_excerpt'})
            else:
                if not isinstance(item['text'], str) or not item['text'].strip() or len(item['text']) > 12000:
                    raise ValueError('Новый текст должен быть непустым и не длиннее 12000 символов.')
                result = dict(item)
                if kind in ('inference', 'proposal'):
                    bases(item['basis_refs'], required=kind == 'inference')
                    for field in ('scope','uncertainties') if kind == 'inference' else ('need',):
                        if item[field] is not None and (not isinstance(item[field], str) or len(item[field]) > 12000):
                            raise ValueError('Неизвестное поле должно быть null или текстом.')
                result['status'] = {'inference':'unverified','proposal':'proposed','unknown':'unknown'}[kind]
                output.append(result)
        return output

    if tasks is None:
        if set(value) != {'claims'}:
            raise ValueError('Ожидается объект только с claims.')
        result = {'claims': claims(value['claims'])}
    else:
        if set(value) != {'answers'} or not isinstance(value['answers'], list):
            raise ValueError('Ожидается answers со списком ответов.')
        expected = {task['id'] for task in tasks}
        ids = [a.get('task_id') if isinstance(a, dict) else None for a in value['answers']]
        if any(not isinstance(i, str) for i in ids) or len(ids) != len(expected) or set(ids) != expected:
            raise ValueError('Ответы должны соответствовать всем заданиям без повторов.')
        result = {'answers': []}
        for answer in value['answers']:
            if set(answer) != {'task_id','claims','uncertainties'} or (answer['uncertainties'] is not None and not isinstance(answer['uncertainties'], str)):
                raise ValueError('В ответе нужны task_id, claims и uncertainties.')
            result['answers'].append({**answer, 'claims': claims(answer['claims'])})
    return {**result, 'reference_validation': 'pass', 'meaning': 'unknown',
            'limits': 'Проверены идентификаторы, версии, цитаты и разделение статусов. Следование вывода из оснований и понятность автоматически не установлены.'}
