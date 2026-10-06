"""Reader understanding: grounded proposals, explicit human review, versioned context."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading

from protocol_atlas.answer_checks import check_answer
from protocol_atlas.runtime_rules import compile_rules, changed_bases, request_digest
from protocol_atlas.source_editor import SourceConflict

STATUSES = {'known': 'известно', 'introduced': 'введено',
            'unknown': 'неизвестно', 'doubted': 'под сомнением'}
FALLBACK = ('Понимание читателя не установлено. Не приписывай ему знание терминов. '
            'Объясняй необходимые понятия кратко на примере текущей задачи. '
            'Данное объяснение не подтверждает понимание; молчание не означает согласие.')


def now():
    return datetime.now(timezone.utc).isoformat()


def field(value, key, limit=2000, required=False):
    item = value.get(key, '')
    if not isinstance(item, str) or len(item) > limit or '\0' in item or required and not item.strip():
        raise ValueError('Некорректное поле профиля: '+key)
    return item.strip()


def empty_profile():
    return {'revision': 0, 'configured': False, 'areas': '', 'language': '',
            'preferences': '', 'terms': [], 'policy': FALLBACK}


def usage_values(result):
    return {k: result.get(k) if type(result.get(k)) is int and result[k] >= 0 else None
            for k in ('input_tokens', 'output_tokens')}


def markdown(profile):
    lines = ['# Профиль читателя', '', 'Версия: '+str(profile['revision']),
             'Основание: '+profile.get('decision', 'оценка отсутствует'), '',
             'Области работы: '+(profile.get('areas') or 'не установлены'),
             'Язык объяснения: '+(profile.get('language') or 'из текущего общения'),
             'Особенности объяснения: '+(profile.get('preferences') or 'не установлены'), '', FALLBACK, '']
    for item in profile.get('terms', []):
        lines += ['## '+item['term'], 'Состояние: '+STATUSES[item['status']],
                  'Основание: '+item['evidence']['quote'],
                  'Источник: реплика '+str(item['evidence']['message']+1)+' ('+item['evidence']['role']+')',
                  'Запись подтверждена человеком при сохранении версии '+str(profile['revision'])+'.', '']
    return '\n'.join(lines)+'\n'


class ReaderStore:
    def __init__(self, root, editor=None):
        self.root = Path(root).resolve()
        self.editor = editor
        self.lock = threading.RLock()
        self.path = self.root/'data/reader.sqlite3'
        if self.path.is_symlink() or self.path.parent.is_symlink():
            raise ValueError('Недопустимое хранилище профиля.')

    @contextmanager
    def db(self):
        self.path.parent.mkdir(exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=15)
        try:
            with connection:
                connection.executescript('CREATE TABLE IF NOT EXISTS profiles (revision INTEGER PRIMARY KEY, body TEXT NOT NULL);'
                                        'CREATE TABLE IF NOT EXISTS conversation (id INTEGER PRIMARY KEY, body TEXT NOT NULL);')
                yield connection
        finally:
            connection.close()

    def profile(self):
        if not self.path.is_file():
            return empty_profile()
        with self.db() as db:
            row = db.execute('SELECT body FROM profiles ORDER BY revision DESC LIMIT 1').fetchone()
        return json.loads(row[0]) if row else empty_profile()

    def conversation(self):
        if not self.path.is_file():
            return {'revision': 0, 'messages': [], 'proposal': None, 'calls': []}
        with self.db() as db:
            row = db.execute('SELECT body FROM conversation WHERE id=1').fetchone()
        return json.loads(row[0]) if row else {'revision': 0, 'messages': [], 'proposal': None, 'calls': []}

    def read(self):
        return {'profile': self.profile(), 'conversation': self.conversation()}

    def validate_proposal(self, proposal, messages):
        value = {key: field(proposal, key, 4000, key == 'message')
                 for key in ('message', 'areas', 'language', 'preferences')}
        terms = proposal.get('terms', [])
        questions = proposal.get('questions', [])
        if not isinstance(terms, list) or len(terms) > 100 or not isinstance(questions, list) or len(questions) > 10 or any(
                not isinstance(q, str) or len(q) > 2000 for q in questions):
            raise ValueError('Некорректный список понятий или вопросов.')
        value.update(terms=[], questions=questions)
        seen = set()
        for item in terms:
            term = field(item, 'term', 100, True)
            status = item.get('status')
            evidence = item.get('evidence', {})
            index = evidence.get('message')
            quote = field(evidence, 'quote', 2000, True)
            if term.casefold() in seen or status not in STATUSES or type(index) is not int or not 0 <= index < len(messages):
                raise ValueError('Понятие требует состояния и основания из беседы.')
            basis = messages[index]
            if quote not in basis['content'] or status != 'introduced' and basis['role'] != 'user':
                raise ValueError('Понимание требует конкретной реплики человека; объяснение ИИ не доказывает понимание.')
            seen.add(term.casefold())
            value['terms'].append({'term': term, 'status': status,
                                   'evidence': {'message': index, 'quote': quote, 'role': basis['role']}})
        return value

    def converse(self, payload):
        answer = field(payload, 'answer', 12000, True)
        previous = self.conversation()
        profile = self.profile()
        if payload.get('expected_revision') != previous['revision'] or payload.get('expected_profile_revision') != profile['revision']:
            raise SourceConflict('Профиль или беседа изменились. Обновите страницу.')
        settings = self.editor.settings(private=True)
        if not settings['configured']:
            raise ValueError('Сначала подключите свой ИИ.')
        key = settings.get('api_key')
        if key:
            answer = answer.replace(key, '[REDACTED]')
        history = previous['messages'] + [{'role': 'user', 'content': answer}]
        runtime = compile_rules(self.root, [])
        instruction = ('Помоги установить профиль понимания читателя по §1.3. Это беседа о том, '
                       'какие объяснения ему нужны для настройки протокола, без баллов интеллекта. '
                       'Используй сказанное человеком и текущий подтверждённый профиль; не делай выводов '
                       'о знаниях по профессии, возрасту или молчанию. Уточняй только необходимые понятия '
                       'для его работы; по возможности предложи небольшой пример применения. '
                       'Самоотчёт или содержательное применение могут дать предложение known, данное '
                       'объяснение — только introduced, непонимание — unknown, неоднозначность — doubted. '
                       'Сохраняй прежние понятия, пока человек не поправил их. Не превращай отсутствие '
                       'ответа в known. Возвращай JSON: message, areas, language, preferences (строки), '
                       'questions (массив), terms (массив {term,status,evidence:{message,quote}}). '
                       'message в evidence — индекс с нуля в messages ниже; quote — точная цитата '
                       'этой реплики. Для known/unknown/doubted основание только от user; для introduced '
                       'можно сослаться на текущее объяснение assistant, индекс которого равен длине messages. '
                       'Неизвестные поля оставляй пустыми. Предложение пока не принято человеком.\n\n')
        messages = [{'role': 'system', 'content': instruction+runtime['text']},
                    {'role': 'user', 'content': json.dumps({'confirmed_reader': profile, 'messages': history}, ensure_ascii=False)}]
        budget = self.editor.adaptive.profile().get('character_budget', 60000)
        if sum(len(m['content']) for m in messages) > budget:
            raise ValueError('Беседа превышает бюджет запроса; текст не обрезается.')
        result = self.editor.call({**settings, 'json_mode': True}, messages)
        raw = result['text'].strip()
        if key:
            raw = raw.replace(key, '[REDACTED]')
        if raw.startswith('```'):
            raw = '\n'.join(raw.splitlines()[1:-1])
        try:
            parsed = json.loads(raw)
            assistant = field(parsed, 'message', 4000, True)
            proposal = self.validate_proposal(parsed, history+[{'role': 'assistant', 'content': assistant}])
        except (ValueError, TypeError, AttributeError, KeyError):
            raise ValueError('ИИ вернул профиль без проверяемых оснований. Ответ остаётся в поле; уточните его.') from None
        checks = check_answer(self.root, proposal['message'])
        checks['blocking'] |= checks['status'] != 'completed'
        call = {'at': now(), 'messages': messages, 'runtime': runtime,
                'settings': {k: settings.get(k) for k in ('provider', 'endpoint', 'model', 'max_output')},
                'request_sha256': request_digest(messages), 'raw_answer': raw, 'checks': checks,
                'usage': usage_values(result),
                'actual_model': str(result.get('model') or '').replace(key, '[REDACTED]') if key else result.get('model'), 'reader_revision': profile['revision']}
        value = {'revision': previous['revision']+1, 'messages': history+[{'role': 'assistant', 'content': proposal['message']}],
                 'proposal': proposal, 'calls': previous['calls']+[call], 'checks': checks, 'usage': call['usage'],
                 'reader_revision': profile['revision'], 'runtime': runtime}
        with self.lock, self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT body FROM conversation WHERE id=1').fetchone()
            live_conversation = json.loads(row[0]) if row else {'revision': 0}
            live_profile = db.execute('SELECT MAX(revision) FROM profiles').fetchone()[0] or 0
            if live_conversation['revision'] != previous['revision'] or live_profile != profile['revision']:
                raise SourceConflict('Во время ответа профиль изменился. Перечитайте актуальную запись.')
            db.execute('INSERT OR REPLACE INTO conversation VALUES (1,?)', (json.dumps(value, ensure_ascii=False),))
        return self.read()

    def accept(self, payload):
        current = self.conversation()
        previous = self.profile()
        if payload.get('expected_revision') != current['revision'] or payload.get('expected_profile_revision') != previous['revision']:
            raise SourceConflict('Профиль изменился. Перечитайте предложение.')
        if current.get('reader_revision') != previous['revision'] or not current.get('proposal'):
            raise SourceConflict('Нужно новое предложение по текущему профилю.')
        if current.get('checks', {}).get('blocking') or changed_bases(self.root, current['runtime']):
            raise ValueError('Предложение требует повторной проверки ответа или его оснований.')
        checks = check_answer(self.root, current['proposal']['message'])
        if checks['blocking'] or checks['status'] != 'completed':
            raise ValueError('Текущая проверка ответа не пройдена.')
        proposal = current['proposal']
        edits = payload.get('statuses', {})
        if not isinstance(edits, dict) or any(k not in {t['term'] for t in proposal['terms']} or v not in STATUSES for k, v in edits.items()):
            raise ValueError('Неизвестное понятие или состояние.')
        terms = []
        for item in proposal['terms']:
            terms.append({**item, 'status': edits.get(item['term'], item['status']),
                          'confirmation': 'Человек проверил и сохранил предложение профиля.'})
        terms += [item for item in previous['terms'] if item['term'] not in {t['term'] for t in terms}]
        value = {k: proposal[k] for k in ('areas', 'language', 'preferences')}
        value.update(terms=terms, decision='Человек проверил предложение ИИ', assessment_revision=current['revision'],
                     evidence_messages=current['messages'], assessed=True)
        value['checks_at_confirmation'] = checks
        return self._save(value, previous['revision'], current['revision'])

    def defer(self, payload):
        return self._save({'areas': '', 'language': '', 'preferences': '', 'terms': [], 'assessed': False,
                           'decision': 'Человек явно выбрал работу без оценки понимания'}, payload.get('expected_profile_revision'))

    def _save(self, value, revision, conversation_revision=None):
        folder = self.root/'data/configuration/memory'
        path = folder/'READER.md'
        if any(p.is_symlink() for p in (path, folder, folder.parent, folder.parent.parent)):
            raise ValueError('Недопустимый путь представления профиля.')
        with self.lock, self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT MAX(revision) FROM profiles').fetchone()
            if revision != (row[0] or 0):
                raise SourceConflict('Профиль изменился. Обновите страницу.')
            if conversation_revision is not None:
                row = db.execute('SELECT body FROM conversation WHERE id=1').fetchone()
                if not row or json.loads(row[0])['revision'] != conversation_revision:
                    raise SourceConflict('Предложение изменилось до сохранения. Перечитайте его.')
            value.update(revision=revision+1, configured=True, updated_at=now(), policy=FALLBACK)
            db.execute('INSERT INTO profiles VALUES (?,?)', (value['revision'], json.dumps(value, ensure_ascii=False)))
        # A generated view, never an independent profile. Author's memory is untouched.
        folder.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown(value), encoding='utf-8')
        return self.read()


def reader_context(root):
    return ReaderStore(root).profile()
