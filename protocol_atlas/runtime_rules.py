"""Deterministic, versioned instructions; explanatory documents stay out of requests."""
import json
import re
from pathlib import Path

from protocol_atlas.catalog import digest, parse_document
from protocol_atlas.source_editor import SourceConflict

PACKS = {
    'research': 'Исследование, источники и формулы',
    'memory': 'Сохранение и продолжение работы',
    'architecture': 'Связанные этапы сложной задачи',
    'external': 'Актуальные внешние сведения',
}
LEGACY_CORE_SECTIONS = {'1', '2', '3', '5', '7', '8.2', '8.3', '8.4', '8.5', '8.6',
                 '10.1', '10.2', '10.3', '11', '12'} | {'8.1.'+str(i) for i in range(1, 16)}
CORE_SECTIONS = {str(i) for i in range(1, 11)}

# A character bound, not an exact token count. Reject rather than truncate rules.
MAX_RULE_CHARACTERS = 12000


def context_size(text, source):
    if len(text) > MAX_RULE_CHARACTERS:
        raise ValueError('Сборка правил превышает лимит 12000 символов. '
                         'Выберите нужные группы или пересмотрите краткие инструкции; правила не обрезаются.')
    return {'rule_character_limit': MAX_RULE_CHARACTERS,
            'rule_utf8_bytes': len(text.encode('utf-8')),
            'source_utf8_bytes': len(source.encode('utf-8')),
            'saved_characters': len(source)-len(text),
            'exact_tokens': None,
            'counting_basis': 'characters_and_utf8_bytes_not_tokens'}


def section_basis(document, prefix):
    section = next((s for s in document['sections']
                    if s['title'].split()[0].rstrip('.') == prefix), None)
    if section is None:
        raise ValueError('В протоколе отсутствует пункт ' + prefix)
    value = ''.join(b['text'] for b in document['blocks']
                    if section['start_line'] <= b['start_line'] <= section['end_line'])
    return section, value


def compile_rules(root, packs=None, stage=None):
    root = Path(root)
    if stage is not None and (not isinstance(stage, str) or stage not in CORE_SECTIONS):
        raise ValueError('Выберите известный этап исполнения 1–10.')
    packs = list(PACKS) if packs is None else packs
    if not isinstance(packs, list) or any(p not in PACKS for p in packs):
        raise ValueError('Выберите известные группы правил.')
    packs = sorted(set(packs))
    path = root / 'PROTOCOL.md'
    if not path.is_file() or path.is_symlink():
        raise ValueError('Протокол недоступен.')
    raw = path.read_bytes()
    document = parse_document('PROTOCOL.md', raw)
    registry = root / 'atlas/rule_runtime.json'
    if not registry.is_file():
        if stage is not None:
            raise ValueError('Выбор этапа требует реестра инструкций исполнения.')
        # Small standalone installations can use their exact source without a compiler.
        value = raw.decode('utf-8')
        if len(value) > 4000:
            raise ValueError('Нет проверенной сборки правил. Полный протокол превышает 4000 символов.')
        return {'text': value, 'rules': [], 'packs': packs, 'omitted': [],
                'source_sha256': document['sha256'], 'characters': len(value),
                'full_characters': len(value), 'mode': 'small_source',
                'context_size': context_size(value, value)}
    if registry.is_symlink():
        raise ValueError('Недопустимый путь инструкций.')
    data = json.loads(registry.read_text(encoding='utf-8'))
    entries = data.get('rules', [])
    schema = data.get('schema_version')
    if schema not in (1, 2) or not entries:
        raise ValueError('Недействующая схема кратких инструкций.')
    if stage is not None and schema != 2:
        raise ValueError('Выбор этапа требует схемы инструкций v2.')
    if len({e['section'] for e in entries}) != len(entries) or any(e['pack'] not in {'core', *PACKS} for e in entries):
        raise ValueError('Повтор или неизвестная группа инструкций.')
    mandatory = CORE_SECTIONS if schema == 2 else LEGACY_CORE_SECTIONS
    if not mandatory.issubset({e['section'] for e in entries if e['pack'] == 'core'}):
        raise ValueError('Постоянное ядро неполно. Вызов не разрешён.')
    if schema == 2 and any(e.get('stage') not in CORE_SECTIONS or e.get('kind') not in ('guard','rule')
                          or e['stage'] != e['section'].split('.')[0]
                          or (e['kind']=='guard') != (e['section'] in CORE_SECTIONS) for e in entries):
        raise ValueError('Неверная привязка инструкции к этапу.')
    if schema == 2:
        sections={s['title'].split()[0].rstrip('.') for s in document['sections'] if s['title'][0].isdigit()}
        if sections != {e['section'] for e in entries}:
            raise ValueError('Реестр не покрывает все этапы и правила исполнения.')
    for name, sha in data.get('dependencies', {}).items():
        dependency = root / name
        if not dependency.is_file() or dependency.is_symlink() or not dependency.resolve().is_relative_to(root.resolve()):
            raise ValueError('Основание инструкций недоступно: ' + name)
        if digest(dependency.read_bytes()) != sha:
            raise SourceConflict('Общее основание кратких инструкций изменено: ' + name)
    selected, omitted, instructions = [], [], []
    for entry in entries:
        if schema == 2 and stage is not None and entry['kind'] != 'guard' and entry['stage'] != stage:
            omitted.append({'section':entry['section'], 'reason':'Подробность другого этапа; условие перехода сохранено в ядре',
                            'stage':entry['stage'], 'pack':entry['pack']})
            continue
        if schema == 1 and entry['pack'] != 'core' and entry['pack'] not in packs:
            omitted.append({'section': entry['section'], 'reason': 'Группа не выбрана для этой задачи',
                            'pack': entry['pack']})
            continue
        section, basis = section_basis(document, entry['section'])
        if digest(basis.encode('utf-8')) != entry['basis_sha256']:
            raise SourceConflict('Пункт ' + entry['section'] +
                                 ' изменился. Обновите его краткую инструкцию перед вызовом ИИ.')
        instruction = entry['instruction'].strip()
        if not instruction:
            raise ValueError('Пустая инструкция: ' + entry['section'])
        instructions.append('§' + entry['section'] + ' ' + instruction)
        selected.append({'section': entry['section'], 'title': section['title'],
                         'line': section['start_line'], 'basis_sha256': entry['basis_sha256'],
                         'instruction': instruction, 'pack': entry['pack'],
                         'reason': 'Условие перехода' if schema == 2 and entry['kind']=='guard' else
                                   'Правило этапа '+entry['stage'] if schema == 2 else
                                   'Постоянное ядро' if entry['pack'] == 'core' else PACKS[entry['pack']]})
    text = '\n\n'.join(instructions)
    return {'text': text, 'rules': selected, 'packs': packs, 'omitted': omitted,
            'source_sha256': document['sha256'], 'registry_sha256': digest(registry.read_bytes()),
            'dependencies': data.get('dependencies', {}),
            'characters': len(text), 'full_characters': len(raw.decode('utf-8')),
            'stage':stage, 'selection_mode':'execution_stage' if schema == 2 else 'legacy_packs',
            'mode': 'compiled', 'context_size': context_size(text, raw.decode('utf-8'))}


def verify_registry(root):
    return compile_rules(root, list(PACKS))


def request_digest(messages):
    return digest(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode('utf-8'))


def changed_bases(root, manifest):
    raw = (Path(root) / 'PROTOCOL.md').read_bytes()
    document = parse_document('PROTOCOL.md', raw)
    if manifest['mode'] == 'small_source':
        return ['PROTOCOL.md'] if document['sha256'] != manifest['source_sha256'] else []
    changed = []
    for name, sha in manifest.get('dependencies', {}).items():
        dependency = Path(root) / name
        if not dependency.is_file() or digest(dependency.read_bytes()) != sha:
            changed.append(name)
    for entry in manifest['rules']:
        try:
            _, basis = section_basis(document, entry['section'])
            if digest(basis.encode('utf-8')) == entry['basis_sha256']:
                continue
        except ValueError:
            pass
        changed.append(entry['section'])
    return changed
