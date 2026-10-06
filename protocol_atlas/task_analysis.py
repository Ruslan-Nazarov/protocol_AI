"""Check public explanations and typed evidence, never private model reasoning."""
import json
import re

from protocol_atlas.context import validate_response, RESPONSE_INSTRUCTION
from protocol_atlas.math_checks import check_equation, check_prose

TASK_RESPONSE_INSTRUCTION = RESPONSE_INSTRUCTION.replace('Корневой ответ: {"claims":[...]}.', '') + '''
Корневой JSON: {"claims":[...],"transitions":[],"calculations":[],"coverage":[]}.
Дополнительные типы claims:
verified: {"type":"verified","event_id":"e1"} — только выбрать реальное событие из evidence_events, без нового текста.
hypothesis: {"type":"hypothesis","text":"...","basis_refs":[],"test":null} — возможное объяснение; test — способ проверки или null.
model_memory: {"type":"model_memory","text":"..."} — сведения по памяти модели, без проверенного источника.
Утверждения получают ссылки c1, c2 и т.д. по порядку. Связное объяснение пиши в text выводов,
сохраняя существенные основания. Точный пересказ источника представляй выводом с соответствующей ссылкой.
Существенные переходы можно раскрыть в transitions:
{"id":"t1","inputs":["s1","c1"],"output":"результат перехода","change":"что меняется",
"reason":null,"conditions":null}. Для ссылки на прежний переход используй step:t1.
Не придумывай потребность ради поля: неизвестное оставляй null. Для простого ответа transitions может быть пустым.
calculations: [{"left":"120/3","right":"40","meaning":"равное распределение страниц","unit":"страниц в день"}].
Проверяются арифметика и многочлены, без вызовов функций. Условия применения объясни словами.
coverage: [{"criterion_id":"k1","state":"addressed","claim_ids":["c1"],"note":null}].
state: addressed / not_addressed / unknown. Учитывай каждый criterion_id из запроса.
Пути, версии, статусы и сведения о событиях восстанавливает приложение. Не выдавай свою оценку за проверку инструмента.
'''


def criteria_items(text):
    lines = [re.sub(r'^\s*(?:[-*]|\d+[.)])\s*', '', line).strip() for line in text.splitlines() if line.strip()]
    return [{'id': 'k'+str(i+1), 'text': line} for i, line in enumerate(lines)]


def transition_graph(steps, references):
    if not isinstance(steps, list) or len(steps) > 30:
        raise ValueError('Переходы: до 30 записей.')
    by_id, warnings = {}, []
    required = {'id', 'inputs', 'output', 'change', 'reason', 'conditions'}
    for step in steps:
        if not isinstance(step, dict) or set(step) != required or not isinstance(step['id'], str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,40}', step['id']) or step['id'] in by_id:
            raise ValueError('Переход должен иметь уникальный идентификатор и известные поля.')
        if not isinstance(step['inputs'], list) or not 1 <= len(step['inputs']) <= 40 or any(not isinstance(x, str) for x in step['inputs']):
            raise ValueError('Для перехода нужны явные входные основания.')
        for field in ('output', 'change'):
            if not isinstance(step[field], str) or not step[field].strip() or len(step[field]) > 12000:
                raise ValueError('Нужны содержание изменения и результат перехода.')
        for field in ('reason', 'conditions'):
            if step[field] is not None and (not isinstance(step[field], str) or not step[field].strip() or len(step[field]) > 12000):
                raise ValueError('Основание и условия: содержательный текст или null.')
            if step[field] is None:
                warnings.append({'transition': step['id'], 'field': field, 'message': 'Не указано; требуется оценка применимости человеком.'})
        by_id[step['id']] = step
    visited, order = set(), []
    def visit(ident, trail):
        if ident in trail:
            raise ValueError('Цикл переходов: '+' → '.join([*trail, ident]))
        if ident in visited:
            return
        for ref in by_id[ident]['inputs']:
            if ref.startswith('step:'):
                target = ref[5:]
                if target not in by_id:
                    raise ValueError('Отсутствует входной переход '+target)
                visit(target, [*trail, ident])
            elif ref not in references:
                raise ValueError('Неизвестное основание перехода '+ref)
        visited.add(ident)
        order.append(ident)
    for ident in by_id:
        visit(ident, [])
    return {'status': 'pass', 'order': order, 'steps': steps, 'warnings': warnings,
            'meaning': 'unknown', 'limits': 'Проверены ссылки и отсутствие циклов; необходимость перехода и достаточность оснований оценивает человек.'}


def term_checks(root, answer, known_terms=()):
    glossary = root/'memory/GLOSSARY.md'
    if not glossary.is_file():
        return []
    prose = re.sub(r'```.*?```', '', answer, flags=re.S)
    warnings = []
    known = {v.casefold().strip() for v in known_terms}
    for term in re.findall(r'^\*\*([^*\n]+?)\.?\*\*', glossary.read_text(encoding='utf-8'), re.M):
        term = term.rstrip('.')
        if term.casefold() in known:
            continue
        match = re.search(r'(?<!\w)'+re.escape(term)+r'(?!\w)', prose, re.I)
        if match:
            before = prose[max(0, match.start()-500):match.start()]
            after = prose[match.end():match.end()+300]
            if not re.search(r'потребност|затруднен|необходимост|возника|называ|понима|означа|переход', before+after, re.I):
                warnings.append({'term': term, 'start': match.start(), 'message': 'Первое употребление: проверьте, показано ли происхождение понятия. Запись в словаре не подтверждает понимание читателя.'})
    return warnings


def resolve_answer(raw, references, events, criteria):
    if not isinstance(raw, str) or not 0 < len(raw) <= 80000:
        raise ValueError('Ответ должен содержать 1–80000 символов.')
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != {'claims', 'transitions', 'calculations', 'coverage'}:
        raise ValueError('Ответ должен содержать claims, transitions, calculations и coverage.')
    if not isinstance(value['claims'], list) or not 1 <= len(value['claims']) <= 40:
        raise ValueError('Нужно 1–40 утверждений.')
    resolved, paragraphs = [], []
    event_map = {e['id']: e for e in events}
    for claim in value['claims']:
        if not isinstance(claim, dict):
            raise ValueError('Утверждение должно быть объектом.')
        kind = claim.get('type')
        if kind == 'verified':
            if set(claim) != {'type', 'event_id'} or not isinstance(claim['event_id'], str) or claim['event_id'] not in event_map:
                raise ValueError('Утверждение о проверке ссылается на отсутствующее событие.')
            event = event_map[claim['event_id']]
            item = {**claim, 'status': 'event_report', 'event': event}
            paragraph = '[ПРОВЕРЕНО] '+event['summary']+' ('+event['id']+'). '+event['scope']
        elif kind == 'hypothesis':
            if set(claim) != {'type','text','basis_refs','test'}:
                raise ValueError('Гипотеза: текст, основания и способ проверки или null.')
            surrogate = {'type': 'proposal', 'text': claim['text'], 'basis_refs': claim['basis_refs'], 'need': claim['test']}
            validate_response(json.dumps({'claims': [surrogate]}), references)
            item = {**claim, 'status': 'hypothesis'}
            paragraph = '[ГИПОТЕЗА] '+claim['text']+' Проверка: '+(claim['test'] or 'не установлена')
        elif kind == 'model_memory':
            if set(claim) != {'type', 'text'}:
                raise ValueError('Сведения по памяти модели: только тип и текст.')
            validate_response(json.dumps({'claims': [{'type':'unknown','text':claim['text']}]}), references)
            item = {**claim, 'status': 'model_memory'}
            paragraph = '[ПАМЯТЬ МОДЕЛИ] '+claim['text']+' Источник сейчас не проверен.'
        else:
            item = validate_response(json.dumps({'claims': [claim]}), references)['claims'][0]
            if kind == 'record':
                record = item['record']
                paragraph = '[ИЗ ИСТОЧНИКА] В записи памяти '+record['id']+' @'+str(record['revision'])+' сохранено: '+record['statement']+' Статус записи: '+record['status']+'.'
            elif kind == 'source':
                source = item['source']
                paragraph = '[ИЗ ИСТОЧНИКА] '+item['quote']+' — '+source['path']+', строки '+str(source['start_line'])+'–'+str(source['end_line'])+'.'
            else:
                label = {'inference':'[ВЫВОД]','proposal':'Предложение:','unknown':'Не установлено:'}[kind]
                paragraph = label+' '+item['text']
                if kind == 'inference':
                    paragraph += ' Основания: '+', '.join(item['basis_refs'])+'.'
                    if item.get('scope'):
                        paragraph += ' Условия: '+item['scope']
                    if item.get('uncertainties'):
                        paragraph += ' Неопределённость: '+item['uncertainties']
        resolved.append(item)
        paragraphs.append(paragraph)
    claim_ids = {'c'+str(i+1) for i in range(len(resolved))}
    transitions = transition_graph(value['transitions'], {*references, *claim_ids})
    if not isinstance(value['calculations'], list) or len(value['calculations']) > 30:
        raise ValueError('Вычисления: до 30 записей.')
    calculations = []
    for calc in value['calculations']:
        if not isinstance(calc, dict) or set(calc) != {'left','right','meaning','unit'} or any(not isinstance(calc[k], str) or len(calc[k]) > (300 if k in ('left','right') else 2000) for k in calc):
            raise ValueError('Вычисление: два выражения, смысл и единица измерения.')
        calculations.append({**calc, **check_equation(calc['left'], calc['right'])})
        paragraphs.append(calc['left']+' = '+calc['right']+'. '+calc['meaning']+' '+calc['unit'])
    if not isinstance(value['coverage'], list) or len(value['coverage']) != len(criteria):
        raise ValueError('Для каждого критерия нужен отдельный результат рассмотрения.')
    seen = set()
    for item in value['coverage']:
        if not isinstance(item, dict) or set(item) != {'criterion_id','state','claim_ids','note'} or not isinstance(item['criterion_id'], str) or item['criterion_id'] in seen or item['criterion_id'] not in {c['id'] for c in criteria}:
            raise ValueError('Неизвестный или повторный критерий.')
        if item['state'] not in ('addressed','not_addressed','unknown') or not isinstance(item['claim_ids'], list) or any(not isinstance(i, str) or i not in claim_ids for i in item['claim_ids']) or item['state']=='addressed' and not item['claim_ids']:
            raise ValueError('Рассмотренный критерий должен ссылаться на существующее утверждение.')
        if item['note'] is not None and (not isinstance(item['note'], str) or len(item['note']) > 4000):
            raise ValueError('Пояснение критерия: текст или null.')
        seen.add(item['criterion_id'])
    for step in transitions['steps']:
        paragraphs.append(step['change']+' '+step['output']+' Основание перехода: '+(step['reason'] or 'не установлено')+'.')
    return {'answer': '\n\n'.join(paragraphs), 'claims': resolved, 'transitions': transitions,
            'calculations': calculations, 'coverage': value['coverage'], 'status': 'pass',
            'blocking': any(c['status']=='fail' for c in calculations), 'meaning': 'unknown'}


def analyze_text(root, answer, known_terms=(), mathematical_text=None):
    calculations = check_prose(answer if mathematical_text is None else mathematical_text)
    return {'calculations': calculations, 'terms': term_checks(root, answer, known_terms),
            'blocking': any(c['blocking'] for c in calculations),
            'limits': 'Проверяется ограниченная арифметика и признаки первого употребления понятий. Истинность, понимание и полнота развития не установлены.'}
