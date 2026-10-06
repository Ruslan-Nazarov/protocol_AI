"""Free-form project intake, kept separate from accepted project settings."""
import json
import threading

from protocol_atlas.adaptive import text
from protocol_atlas.runtime_rules import compile_rules
from protocol_atlas.runtime_rules import request_digest, changed_bases
from protocol_atlas.answer_checks import check_answer
from protocol_atlas.reader import usage_values
from protocol_atlas.source_editor import SourceConflict
from protocol_atlas.translations import write_json


class Onboarding:
    def __init__(self, editor, adaptive):
        self.editor = editor
        self.adaptive = adaptive
        self.lock = threading.RLock()

    def read(self):
        path = self.editor.data_path('onboarding.json')
        return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {
            'revision': 0, 'messages': [], 'proposal': None}

    def converse(self, payload):
        answer = text(payload, 'answer', limit=12000)
        with self.lock:
            previous = self.read()
            if payload.get('expected_revision') != previous['revision']:
                raise SourceConflict('Описание проекта изменилось. Обновите страницу.')
            settings = self.editor.settings(private=True)
            if not settings['configured']:
                raise ValueError('Добавьте свой ИИ в настройках. Ваш текст останется в поле ответа.')
            if settings.get('api_key'):
                answer = answer.replace(settings['api_key'], '[REDACTED]')
            runtime = compile_rules(self.editor.root, [])
            history = previous['messages'] + [{'role': 'user', 'content': answer}]
            reader = self.adaptive.reader.profile()
            messages = [{'role': 'system', 'content':
                'Помоги пользователю настроить протокол как фреймворк для своего ИИ. '
                'Здесь настраивают промпты, правила, этапы, память и подключённые скрипты, '
                'а рабочие задачи выполняют в Codex, другом агенте или чате. '
                'Выясни, для какой работы нужны эти настройки, и связывай требования '
                'с необходимыми инструкциями и проверками. Не отправляй человека '
                'в рабочий клиент до завершения настройки и испытания протокола. '
                'Пользователь отвечает свободным текстом. Объедини сведения всей беседы, '
                'учитывая исправления. Не требуй заполнения структуры или JSON от человека. '
                'Не выполняй проект и не выдумывай требования, API, даты или материалы. '
                'Задавай один следующий необходимый вопрос; не спрашивай то, что уже известно. '
                'Верни только JSON: message (понятный ответ по-русски), purpose (цель), '
                'requirements (только явно названные обязательные требования), '
                'starting_point (что уже есть), questions (массив недостающих сведений). '
                'Неизвестные строки оставь пустыми. Итог является предложением, которое '
                'человек должен проверить перед сохранением.\n\n' + runtime['text'] +
                '\n\nПодтверждённый профиль читателя:\n'+json.dumps(reader, ensure_ascii=False)}] + history
            budget = self.adaptive.profile().get('character_budget', 60000)
            if sum(len(m['content']) for m in messages) > budget:
                raise ValueError('Беседа превышает бюджет запроса. Ответ остаётся в поле без обрезки; начните отдельную постановку задачи.')
            result = self.editor.call({**settings, 'json_mode': True}, messages)
            raw = result['text'].strip()
            if raw.startswith('```'):
                raw = '\n'.join(raw.splitlines()[1:-1])
            try:
                proposal = json.loads(raw)
                proposal = {**{k: text(proposal, k, k == 'message', 20000)
                               for k in ('message', 'purpose', 'requirements', 'starting_point')},
                            'questions': proposal.get('questions', [])}
                if not isinstance(proposal['questions'], list) or len(proposal['questions']) > 20 or any(
                        not isinstance(q, str) or len(q) > 2000 for q in proposal['questions']):
                    raise ValueError()
            except (ValueError, TypeError, AttributeError):
                raise ValueError('ИИ вернул неполное описание. Ваш ответ сохранён в поле; попробуйте ещё раз.') from None
            key = settings.get('api_key')
            if key:
                proposal = {k: ([q.replace(key, '[REDACTED]') for q in v] if isinstance(v, list)
                                else v.replace(key, '[REDACTED]')) for k, v in proposal.items()}
            value = {'revision': previous['revision'] + 1,
                     'messages': history + [{'role': 'assistant', 'content': proposal['message']}],
                     'proposal': proposal, 'usage': usage_values(result),
                     'model': (result.get('model') or settings['model']).replace(key, '[REDACTED]') if key else result.get('model') or settings['model'],
                     'reader_revision': reader['revision'], 'runtime': runtime,
                     'checks': check_answer(self.editor.root, proposal['message'])}
            value['calls'] = previous.get('calls', []) + [{
                'messages': messages, 'request_sha256': request_digest(messages), 'runtime': runtime,
                'settings': {k: settings.get(k) for k in ('provider', 'endpoint', 'model', 'max_output')},
                'raw_answer': raw.replace(key, '[REDACTED]') if key else raw,
                'usage': value['usage'], 'checks': value['checks'], 'reader_revision': reader['revision']}]
            value['checks']['blocking'] |= value['checks']['status'] != 'completed'
            write_json(self.editor.data_path('onboarding.json'), value)
            return value

    def accept(self, payload):
        with self.lock:
            current = self.read()
            if payload.get('expected_revision') != current['revision']:
                raise SourceConflict('Описание изменилось. Перечитайте его перед сохранением.')
            proposal = current.get('proposal')
            if not proposal or not proposal['purpose']:
                raise ValueError('Сначала опишите проект и получите предложение ИИ.')
            if current.get('checks', {}).get('blocking'):
                raise ValueError('Сначала исправьте сбой проверки или ссылки в ответе ИИ.')
            checks = check_answer(self.editor.root, proposal['message'])
            if checks['blocking'] or checks['status'] != 'completed':
                raise ValueError('Текущая проверка ответа не пройдена.')
            if current.get('reader_revision', 0) != self.adaptive.reader.profile()['revision']:
                raise SourceConflict('Профиль читателя изменился. Уточните настройку с текущим профилем.')
            if current.get('runtime', {}).get('mode') and changed_bases(self.editor.root, current['runtime']):
                raise SourceConflict('Правила изменились. Уточните настройку по актуальным основаниям.')
            return self.adaptive.configure({
                'expected_revision': payload.get('expected_profile_revision'),
                'purpose': proposal['purpose'],
                'requirements': proposal['requirements'] or 'Обязательные требования пока не установлены; уточнить перед выполнением.',
                'starting_point': proposal['starting_point'] or 'Исходное состояние пока не установлено; уточнить перед выполнением.',
                'character_budget': self.adaptive.profile().get('character_budget', 60000),
                'known_terms': self.adaptive.profile().get('known_terms', [])})
