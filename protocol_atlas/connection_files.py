"""Download the current, explicitly listed AI connection documents."""
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
from pathlib import Path

from protocol_atlas.catalog import _source_paths
from protocol_atlas.source_editor import SourceConflict
from protocol_atlas.translations import TranslationStore, document_paths


CONNECTION_FILES = ('PROTOCOL.md', 'memory/STATE.md', 'memory/DECISIONS.md')
INSTRUCTION_NAMES = ('PROTOCOL_INSTRUCTION.md', 'AGENTS.protocol.md', 'CLAUDE.protocol.md', 'GEMINI.protocol.md', 'FIRST_MESSAGE.md')


def project_paths(root):
    """Only distributable sources; never keys, database, runs or backups."""
    root = Path(root)
    paths = set(_source_paths(root)) | set(document_paths(root)) | {'atlas/annotations.json', '.env.example'}
    if (root / 'atlas/rule_runtime.json').is_file():
        paths.add('atlas/rule_runtime.json')
    for folder, pattern in (('protocol_atlas', '*.py'), ('protocol_atlas/web', '*'),
                            ('scripts', '*.py'), ('tests', '*.py'), ('locales/en', '*.json'),
                            ('locales/en/documents', '**/*.json')):
        paths.update(p.relative_to(root).as_posix() for p in (root / folder).glob(pattern)
                     if p.is_file() and (folder != 'protocol_atlas/web' or p.suffix in ('.js', '.css', '.html')))
    return sorted(paths)


def source_bytes(root, name):
    root = Path(root).resolve()
    target = root / name
    if target.is_symlink() or not target.resolve().is_relative_to(root):
        raise ValueError('Недопустимый путь документа.')
    return target.read_bytes()


def instruction_download(text, filename):
    if filename not in INSTRUCTION_NAMES or not isinstance(text, str) or not text.strip() or len(text) > 8000 or '\0' in text:
        raise ValueError('Недопустимая инструкция для скачивания.')
    return (text.rstrip() + '\n').encode('utf-8'), filename, 'text/markdown'


def connection_download(root, language='ru', path=None, bundle='basic'):
    if language not in ('ru', 'en'):
        raise ValueError('Выберите язык файлов: ru или en.')
    if bundle not in ('basic', 'memory', 'project'):
        raise ValueError('Неизвестный комплект файлов.')
    if path is not None and path not in project_paths(root):
        raise ValueError('Файл отсутствует в наборе для подключения.')
    translations = TranslationStore(root)
    names = project_paths(root) if bundle == 'project' else (
        ['PROTOCOL.md', 'check_answer.py'] + [p for p in _source_paths(root) if p.startswith('memory/')]
        if bundle == 'memory' else CONNECTION_FILES)
    files = {}
    for name in (path,) if path else names:
        raw = source_bytes(root, name)
        # Runnable projects preserve Russian originals and their linked English
        # catalogs; translating the originals would invalidate those catalogs.
        if language == 'ru' or bundle == 'project' and path is None or not name.endswith('.md'):
            files[name] = raw
        else:
            document = translations.read(name)
            if document['pending']:
                raise SourceConflict('Обновите английский перевод перед скачиванием файлов.')
            files[name] = ''.join(unit['translation'] for unit in document['units']).encode('utf-8')
    if path:
        return files[path], path.rsplit('/', 1)[-1], 'text/markdown' if path.endswith('.md') else 'text/plain'
    buffer = BytesIO()
    with ZipFile(buffer, 'w', compression=ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    filename = 'protocol-ai-app.zip' if bundle == 'project' else f'protocol-ai-{language}{"-memory" if bundle == "memory" else ""}.zip'
    return buffer.getvalue(), filename, 'application/zip'
