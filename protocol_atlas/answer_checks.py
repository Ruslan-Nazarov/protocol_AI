"""Automatic checks report evidence; semantic acceptance remains human."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from protocol_atlas.catalog import digest, parse_document


def check_answer(root, answer):
    root = Path(root)
    document = parse_document('PROTOCOL.md', (root / 'PROTOCOL.md').read_bytes())
    labels = {s['title'].split()[0].rstrip('.') for s in document['sections']}
    references = set(re.findall(r'§\s*(\d+(?:\.\d+)*)', answer))
    missing = sorted(references - labels) if document['sections'] else []
    result = {'missing_protocol_sections': missing, 'warnings': [], 'warning_count': None,
              'status': 'unavailable', 'blocking': bool(missing),
              'limits': 'Проверяются ссылки и признаки формы. Смысл, полнота и истинность требуют проверки человеком.'}
    script = root / 'check_answer.py'
    if not script.is_file() or script.is_symlink():
        return result
    try:
        script_raw = script.read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            draft = Path(folder) / 'answer.txt'
            draft.write_text(answer, encoding='utf-8')
            checker = Path(folder) / 'checker.py'
            checker.write_bytes(script_raw)
            output = subprocess.run([sys.executable, str(checker), str(draft)],
                                    capture_output=True, encoding='utf-8', timeout=10,
                                    env={**os.environ, 'PYTHONUTF8': '1'})
        if output.returncode not in (0, 1):
            raise ValueError('Проверка не завершена.')
        count = re.search(r'Замечаний: (\d+)', output.stdout)
        if not count:
            raise ValueError('Отсутствует итоговый отчёт проверки.')
        result.update(status='completed', checker_sha256=digest(script_raw),
                      warnings=[line for line in output.stdout.splitlines() if not line.startswith('Замечаний:')],
                      warning_count=int(count[1]) if count else None)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        result.update(status='failed', blocking=True)
    return result
