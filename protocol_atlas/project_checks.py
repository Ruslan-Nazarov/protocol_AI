"""A fixed project test operation and a snapshot of the checked program."""
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

from protocol_atlas.catalog import digest


def code_snapshot(root):
    root = Path(root).resolve()
    names = {'check_answer.py'}
    for folder, pattern in [('protocol_atlas','*.py'),('protocol_atlas/web','*'),('tests','*.py'),('scripts','*.py')]:
        names.update(p.relative_to(root).as_posix() for p in (root/folder).glob(pattern)
                     if p.is_file() and p.suffix in ('.py','.js','.css','.html'))
    names.update(p.relative_to(root).as_posix() for p in root.glob('*.md') if p.is_file())
    for folder, pattern in [('memory','*.md'),('docs','*.md'),('atlas','*.json'),('locales/en','**/*.json')]:
        names.update(p.relative_to(root).as_posix() for p in (root/folder).glob(pattern) if p.is_file())
    hashes = {}
    for name in sorted(names):
        path = root/name
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('Проверка программы требует обычных файлов внутри проекта.')
        if path.is_file():
            hashes[name] = digest(path.read_bytes())
    runtime = {'python':sys.version,'sqlite':sqlite3.sqlite_version}
    return {'files':hashes,'runtime':runtime,'sha256':digest(json.dumps([hashes,runtime],sort_keys=True).encode())}


def run_tests(root):
    root = Path(root)
    before = code_snapshot(root)
    if not (root/'tests').is_dir() or (root/'tests').is_symlink():
        raise ValueError('В проекте нет обычной папки tests.')
    command = [sys.executable,'-m','unittest','discover','-s','tests']
    result = subprocess.run(command,cwd=root,capture_output=True,encoding='utf-8',errors='replace',timeout=90,
                            env={**os.environ,'PYTHONUTF8':'1'},creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    output = result.stdout+'\n'+result.stderr
    count = re.search(r'(?m)^Ran (\d+) tests? in ', output)
    after = code_snapshot(root)
    passed = result.returncode == 0 and count and int(count[1]) > 0 and re.search(r'(?m)^OK(?:\s|$)',output)
    return {'status':'pass' if passed and before['sha256']==after['sha256'] else 'fail',
            'count':int(count[1]) if count else None,'exit_code':result.returncode,
            'snapshot':before,'changed_during_check':before['sha256']!=after['sha256'],
            'output':output[-20000:], 'command':['python','-m','unittest','discover','-s','tests'],
            'scope':'Запущены тесты проекта на указанной версии программы и исходных документов. Покрытие тестов и смысловая достаточность не подтверждаются самим успешным запуском.'}
