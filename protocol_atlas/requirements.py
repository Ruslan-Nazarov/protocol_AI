"""Source-grounded requirement cards with clauses and honest implementation scopes."""
import re
import json
import sqlite3
from protocol_atlas.catalog import build_catalog, digest
from protocol_atlas.runtime_rules import section_basis
from protocol_atlas.project_checks import code_snapshot

MECHANISMS = [('1.1',
  'Восстановить задачу из доступных записей',
  'protocol_atlas/project_runtime.py',
  'Метод проверки задан; достаточность смысла оценивается отдельно. Указанный модуль проверяет только '
  'реализованные свойства; произвольное внешнее исполнение не контролируется.',
  'partial'),
 ('1.2',
  'Установить разрешённые действия',
  'protocol_atlas/source_editor.py',
  'Метод проверки задан; достаточность смысла оценивается отдельно. Указанный модуль проверяет только '
  'реализованные свойства; произвольное внешнее исполнение не контролируется.',
  'partial'),
 ('1.3',
  'Установить исходное понимание читателя',
  'protocol_atlas/reader.py',
  'Метод проверки задан; достаточность смысла оценивается отдельно. Указанный модуль проверяет только '
  'реализованные свойства; произвольное внешнее исполнение не контролируется.',
  'partial'),
 ('2.2',
  'Получить предметные сведения',
  'protocol_atlas/context.py',
  'Метод проверки задан; достаточность смысла оценивается отдельно. Указанный модуль проверяет только '
  'реализованные свойства; произвольное внешнее исполнение не контролируется.',
  'partial'),
 ('2.3',
  'Связать посылки и обозначения с предметом',
  'protocol_atlas/logic.py',
  'Метод проверки задан; достаточность смысла оценивается отдельно. Указанный модуль проверяет только '
  'реализованные свойства; произвольное внешнее исполнение не контролируется.',
  'partial'),
 ('3.1',
  'Выбрать логику по требуемому переходу',
  'protocol_atlas/logic.py',
  'Метод проверки задан; достаточность смысла оценивается отдельно. Указанный модуль проверяет только '
  'реализованные свойства; произвольное внешнее исполнение не контролируется.',
  'partial'),
 ('3.2',
  'Закрепить договор выполнения',
  'protocol_atlas/logic.py',
  'Метод проверки задан; достаточность смысла оценивается отдельно. Указанный модуль проверяет только '
  'реализованные свойства; произвольное внешнее исполнение не контролируется.',
  'partial'),
 ('3.3',
  'Назначить проверку вывода',
  'protocol_atlas/logic.py',
  'Метод проверки задан; достаточность смысла оценивается отдельно. Указанный модуль проверяет только '
  'реализованные свойства; произвольное внешнее исполнение не контролируется.',
  'partial'),
 ('4.1',
  'Получить проверяемые последствия ответа',
  'protocol_atlas/task_analysis.py',
  'Метод проверки задан; достаточность смысла оценивается отдельно. Указанный модуль проверяет только '
  'реализованные свойства; произвольное внешнее исполнение не контролируется.',
  'partial'),
 ('4.2',
  'Испытать проверяющий механизм',
  'scripts/verify_logic_core.py',
  'Метод проверки задан; достаточность смысла оценивается отдельно. Указанный модуль проверяет только '
  'реализованные свойства; произвольное внешнее исполнение не контролируется.',
  'partial'),
 ('4.3',
  'Разделить задачу и задать бюджет',
  'protocol_atlas/adaptive.py',
  'Метод проверки задан; достаточность смысла оценивается отдельно. Указанный модуль проверяет только '
  'реализованные свойства; произвольное внешнее исполнение не контролируется.',
  'partial'),
 ('5.1',
  'Проверить доступ к выполнению и наблюдению',
  'protocol_atlas/runtime_install.py',
  'Метод проверки задан; достаточность смысла оценивается отдельно. Указанный модуль проверяет только '
  'реализованные свойства; произвольное внешнее исполнение не контролируется.',
  'partial'),
 ('5.2',
  'Собрать только нужные инструкции и данные',
  'protocol_atlas/runtime_rules.py',
  'Метод проверки задан; достаточность смысла оценивается отдельно. Указанный модуль проверяет только '
  'реализованные свойства; произвольное внешнее исполнение не контролируется.',
  'partial'),
 ('6.1',
  'Выполнить переход из закреплённых оснований',
  'protocol_atlas/logic.py',
  'Метод проверки задан; достаточность смысла оценивается отдельно. Указанный модуль проверяет только '
  'реализованные свойства; произвольное внешнее исполнение не контролируется.',
  'partial'),
 ('6.2',
  'Проверить формулу и вычисление в их условиях',
  'protocol_atlas/math_checks.py',
  'Метод проверки задан; достаточность смысла оценивается отдельно. Указанный модуль проверяет только '
  'реализованные свойства; произвольное внешнее исполнение не контролируется.',
  'partial'),
 ('6.3',
  'Раскрыть результат через развитие предмета',
  'check_answer.py',
  'Метод проверки задан; достаточность смысла оценивается отдельно. Указанный модуль проверяет только '
  'реализованные свойства; произвольное внешнее исполнение не контролируется.',
  'partial'),
 ('6.4',
  'Различить основания отдельных утверждений',
  'protocol_atlas/task_analysis.py',
  'Метод проверки задан; достаточность смысла оценивается отдельно. Указанный модуль проверяет только '
  'реализованные свойства; произвольное внешнее исполнение не контролируется.',
  'partial'),
 ('7.1',
  'Получить фактическое наблюдение',
  'protocol_atlas/four_pillars.py',
  'Метод проверки задан; достаточность смысла оценивается отдельно. Указанный модуль проверяет только '
  'реализованные свойства; произвольное внешнее исполнение не контролируется.',
  'partial'),
 ('7.3',
  'Разрешить только обеспеченное продолжение',
  'protocol_atlas/project_runtime.py',
  'Метод проверки задан; достаточность смысла оценивается отдельно. Указанный модуль проверяет только '
  'реализованные свойства; произвольное внешнее исполнение не контролируется.',
  'partial'),
 ('8.1',
  'Установить место и причину расхождения',
  'protocol_atlas/project_runtime.py',
  'Метод проверки задан; достаточность смысла оценивается отдельно. Указанный модуль проверяет только '
  'реализованные свойства; произвольное внешнее исполнение не контролируется.',
  'partial'),
 ('8.2',
  'Исправить конкретное основание или проверку',
  'protocol_atlas/project_runtime.py',
  'Метод проверки задан; достаточность смысла оценивается отдельно. Указанный модуль проверяет только '
  'реализованные свойства; произвольное внешнее исполнение не контролируется.',
  'partial'),
 ('8.3',
  'Повторить затронутую проверку',
  'protocol_atlas/project_runtime.py',
  'Метод проверки задан; достаточность смысла оценивается отдельно. Указанный модуль проверяет только '
  'реализованные свойства; произвольное внешнее исполнение не контролируется.',
  'partial'),
 ('9.1',
  'Проверить соединение результатов',
  'protocol_atlas/answer_checks.py',
  'Метод проверки задан; достаточность смысла оценивается отдельно. Указанный модуль проверяет только '
  'реализованные свойства; произвольное внешнее исполнение не контролируется.',
  'partial'),
 ('9.2',
  'Сообщить результат и получить оставленное решение',
  'protocol_atlas/adaptive.py',
  'Метод проверки задан; достаточность смысла оценивается отдельно. Указанный модуль проверяет только '
  'реализованные свойства; произвольное внешнее исполнение не контролируется.',
  'partial'),
 ('9.3',
  'Сообщить измеренный расход',
  'protocol_atlas/adaptive.py',
  'Метод проверки задан; достаточность смысла оценивается отдельно. Указанный модуль проверяет только '
  'реализованные свойства; произвольное внешнее исполнение не контролируется.',
  'partial'),
 ('10.1',
  'Сохранить состояние, решения и свидетельства',
  'protocol_atlas/memory.py',
  'Метод проверки задан; достаточность смысла оценивается отдельно. Указанный модуль проверяет только '
  'реализованные свойства; произвольное внешнее исполнение не контролируется.',
  'partial'),
 ('10.2',
  'Включить проверенный опыт в следующую задачу',
  'protocol_atlas/adaptive.py',
  'Метод проверки задан; достаточность смысла оценивается отдельно. Указанный модуль проверяет только '
  'реализованные свойства; произвольное внешнее исполнение не контролируется.',
  'partial'),
 ('10.4',
  'Зафиксировать завершение или точную остановку',
  'protocol_atlas/project_runtime.py',
  'Метод проверки задан; достаточность смысла оценивается отдельно. Указанный модуль проверяет только '
  'реализованные свойства; произвольное внешнее исполнение не контролируется.',
  'partial')]

def verification(root):
    path = root/'data/adaptive.sqlite3'
    if not path.is_file() or path.is_symlink():
        return {'status':'not_recorded','current':False}
    try:
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
            row = db.execute('SELECT body FROM program_checks ORDER BY rowid DESC LIMIT 1').fetchone()
        if not row:
            return {'status':'not_recorded','current':False}
        check = json.loads(row[0])
        return {'status':check['status'],'current':check['snapshot']['sha256']==code_snapshot(root)['sha256'],
                'count':check['count'],'at':check['at'],'scope':check['scope']}
    except (sqlite3.Error,ValueError,KeyError):
        return {'status':'not_recorded','current':False}


def inventory(root):
    catalog = build_catalog(root, strict_annotations=False)
    doc = next(item for item in catalog['documents'] if item['path'] == 'PROTOCOL.md')
    runtime_path = root / 'atlas/rule_runtime.json'
    runtime_rules = json.loads(runtime_path.read_text(encoding='utf-8'))['rules'] if runtime_path.is_file() else []
    dependencies = json.loads(runtime_path.read_text(encoding='utf-8')).get('dependencies', {}) if runtime_path.is_file() else {}
    shared_current = all((root/name).is_file() and digest((root/name).read_bytes()) == sha for name,sha in dependencies.items())
    for rule in runtime_rules:
        try:
            _, basis = section_basis(doc, rule['section'])
            rule['current'] = shared_current and digest(basis.encode('utf-8')) == rule['basis_sha256']
        except ValueError:
            rule['current'] = False
    cards, covered = [], []
    checked = verification(root)
    counters = {}
    for block in doc['blocks']:
        if block['kind'] in ('heading', 'blank', 'separator'):
            continue
        section = next((item for item in doc['sections'] if item['id'] == block['section_id']), None)
        prefix = section['title'].split(' ')[0] if section else 'Введение'
        counters[prefix] = counters.get(prefix, 0) + 1
        number = re.match(r'^(\d+)\.\s', block['text'])
        key = prefix + ('.' + number[1] if number and prefix.startswith(('8.', '9.', '10.')) else ':' + str(counters[prefix]))
        if block['kind'] == 'code':
            kind = 'template'
        elif block['kind'] == 'table':
            kind = 'definition_table'
        elif any(word in block['text'].lower() for word in ('обязан', 'нельзя', 'требует', 'запрещ', 'правило', 'долж', 'подтверж', '→', 'кажд', 'фиксир')) or block['kind'] == 'list_item':
            kind = 'requirement'
        else:
            kind = 'context'
        exact = block['text'].strip()
        clauses = [piece.strip() for piece in re.split(r'(?<!\d\.)(?<=[.!?;])\s+(?=[А-ЯЁA-Z*])', exact) if piece.strip()]
        if kind == 'definition_table':
            clauses = [line.strip() for line in exact.splitlines() if line.strip() and
                       not re.fullmatch(r'\s*\|[\s:|\-]+\|?\s*', line)]
        matches = [item for item in MECHANISMS if prefix == item[0] or
                   prefix.startswith(item[0] if item[0].endswith('.') else item[0]+'.')]
        mechanism = max(matches, key=lambda item: len(item[0])) if matches else None
        runtime = [rule for rule in runtime_rules if prefix.rstrip('.') == rule['section'] or
                   prefix.startswith(rule['section']+'.')]
        cards.append({'id': key + ':' + digest(exact.encode())[:8], 'label': key, 'section': section['title'] if section else 'Введение',
                      'title': re.sub(r'[*`]', '', exact.splitlines()[0])[:140], 'kind': kind, 'text': exact,
                      'clauses': clauses, 'source': {'path': doc['path'], 'sha256': doc['sha256'], 'start_line': block['start_line'], 'end_line': block['end_line']},
                      'mechanism': {'title': mechanism[1], 'path': mechanism[2], 'scope': mechanism[3], 'status': mechanism[4]} if mechanism else
                          {'title': 'Предметная проверка агентом или человеком', 'path': None, 'scope': 'Автоматический механизм для этого фрагмента не заявлен.', 'status': 'human'},
                      'semantic_review': 'clauses_keep_parent_context;human_pending'})
        cards[-1]['runtime'] = runtime
        cards[-1]['mechanism'].update(exists=bool(mechanism and (root/mechanism[2]).is_file()),
                                      connection='Задачи и проверки в локальном приложении; условия включения указаны выше.' if mechanism else 'Оценка человеком',
                                      verification=checked if mechanism else {'status':'human_pending','current':False})
        covered.append(block['id'])
    expected = [block['id'] for block in doc['blocks'] if block['kind'] not in ('heading', 'blank', 'separator')]
    return {'catalog_revision': catalog['catalog_revision'], 'source_sha256': doc['sha256'], 'cards': cards,
            'coverage': {'source_blocks': len(expected), 'covered_blocks': len(covered), 'complete': covered == expected,
                         'semantic_verification': 'human_pending'},
            'limits': 'Карточки и подпункты сохраняют исходный контекст. Наличие механизма не означает выполнение всех требований ИИ.'}
