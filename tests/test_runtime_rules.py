import json
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import Mock

from protocol_atlas.adaptive import AdaptiveTasks
from protocol_atlas.answer_checks import check_answer
from protocol_atlas.runtime_rules import compile_rules, CORE_SECTIONS
from protocol_atlas.source_editor import SourceConflict

ROOT = Path(__file__).resolve().parents[1]


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('PROTOCOL.md', 'memory/GLOSSARY.md', 'atlas/rule_runtime.json', 'check_answer.py'):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        self.settings = dict(configured=True, provider='custom', endpoint='http://localhost', model='test', api_key='')
        self.editor = Mock()
        self.editor.settings.return_value = self.settings
        self.editor.call.return_value = {'text': 'Проверен пункт §6.3.', 'input_tokens': 2, 'output_tokens': 3}
        self.tasks = AdaptiveTasks(self.root, self.editor)
        self.tasks.configure(dict(expected_revision=0, purpose='Проверка', requirements='Сохранить основания',
                                  starting_point='Исходный текст', character_budget=60000))
        self.payload = dict(goal='Объяснить', task_type='Объяснение', volume='Одно понятие',
                            complexity='Предварительная оценка', criteria='Понятный пример',
                            materials='Точный материал, который нельзя обрезать.', rule_packs=[])

    def registry(self, change):
        path = self.root / 'atlas/rule_runtime.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        change(data)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')

    def test_oversized_rules_block_before_paid_call_without_truncation(self):
        self.registry(lambda d: d['rules'][0].update(instruction='x' * 12001))
        with self.assertRaisesRegex(ValueError, '12000'):
            self.tasks.start(self.payload)
        self.editor.call.assert_not_called()

    def test_compact_manifest_exposes_size_without_claiming_token_count(self):
        compact = compile_rules(self.root, stage='6')
        all_rules = compile_rules(self.root)
        self.assertLess(compact['characters'], all_rules['characters'])
        self.assertGreater(compact['context_size']['saved_characters'], 0)
        self.assertIsNone(compact['context_size']['exact_tokens'])
        self.assertEqual(compact['context_size']['rule_utf8_bytes'], len(compact['text'].encode('utf-8')))
        self.assertTrue(compact['omitted'])

    def completed(self):
        task = self.tasks.start(self.payload)
        for _ in range(150):
            result = self.tasks.get(task['id'])
            if result['status'] != 'running':
                return result
            time.sleep(.01)
        self.fail('Task timeout')

    def test_core_is_always_present_and_explicit_groups_are_audited(self):
        rules = compile_rules(self.root, stage='6')
        self.assertTrue(CORE_SECTIONS.issubset({r['section'] for r in rules['rules']}))
        self.assertEqual({r['section'] for r in rules['rules']}-CORE_SECTIONS, {'6.1','6.2','6.3','6.4'})
        self.assertTrue(all(r['stage']!='6' for r in rules['omitted']))
        self.assertLess(rules['characters'], rules['full_characters'] / 4)
        research = compile_rules(self.root, ['research'], stage='2')
        self.assertIn('2.2', [r['section'] for r in research['rules']])
        self.assertNotIn('6.2', [r['section'] for r in research['rules']])
        with self.assertRaises(ValueError):
            compile_rules(self.root, ['unknown'])

    def test_missing_core_or_stale_selected_source_prevents_call(self):
        self.registry(lambda d: d['rules'].pop(0))
        with self.assertRaises(ValueError):
            self.tasks.start(self.payload)
        self.editor.call.assert_not_called()

    def test_guard_dependency_change_invalidates_even_another_selected_stage(self):
        path = self.root / 'PROTOCOL.md'
        source = path.read_text(encoding='utf-8')
        path.write_text(source.replace('### 2.2 Получить предметные сведения', '### 2.2 Получить актуальные сведения'), encoding='utf-8')
        with self.assertRaises(SourceConflict):
            compile_rules(self.root, stage='6')
        path.write_text(source.replace('### 6.3 Раскрыть результат через развитие предмета', '### 6.3 Раскрыть изменённое объяснение'), encoding='utf-8')
        with self.assertRaises(SourceConflict):
            self.tasks.start(self.payload)
        self.editor.call.assert_not_called()

    def test_shared_concept_change_invalidates_instructions(self):
        with (self.root/'memory/GLOSSARY.md').open('a', encoding='utf-8') as stream:
            stream.write('\nУточнённое значение развития.\n')
        with self.assertRaises(SourceConflict):
            compile_rules(self.root, [])

    def test_request_contains_exact_material_and_preview_change_is_rejected(self):
        prepared = self.tasks.prepare(self.payload)
        user = json.loads(prepared['messages'][1]['content'])
        self.assertEqual(user['task']['materials'], self.payload['materials'])
        self.assertEqual(prepared['runtime']['packs'], [])
        with self.assertRaises(SourceConflict):
            self.tasks.start({**self.payload, 'goal': 'Другая цель',
                              'expected_request_sha256': prepared['request_sha256']})
        self.settings['max_output'] = 500
        with self.assertRaises(SourceConflict):
            self.tasks.start({**self.payload, 'expected_request_sha256': prepared['request_sha256']})
        self.editor.call.assert_not_called()

    def test_response_checks_are_saved_and_bad_references_cannot_be_accepted(self):
        self.editor.call.return_value = {'text': 'Пункт §999.1 подтверждает результат.'}
        result = self.completed()
        self.assertEqual(result['status'], 'awaiting_review')
        self.assertEqual(result['checks']['missing_protocol_sections'], ['999.1'])
        self.assertTrue(result['checks']['blocking'])
        with self.assertRaises(ValueError):
            self.tasks.review(dict(id=result['id'], expected_revision=2, outcome='accepted', evidence='Прочитано'))
        revised = self.tasks.review(dict(id=result['id'], expected_revision=2, outcome='revise',
                                         evidence='Ссылка проверена', error='Нет пункта'))
        self.assertEqual(revised['review']['outcome'], 'revise')

    def test_rule_change_after_result_blocks_acceptance(self):
        result = self.completed()
        path = self.root/'PROTOCOL.md'
        source = path.read_text(encoding='utf-8')
        path.write_text(source.replace('### 6.3 Раскрыть результат через развитие предмета', '### 6.3 Раскрыть изменённое объяснение'), encoding='utf-8')
        with self.assertRaises(SourceConflict):
            self.tasks.review(dict(id=result['id'], expected_revision=2, outcome='accepted', evidence='Прочитано'))

    def test_heuristics_are_warnings_but_checker_failure_blocks_acceptance(self):
        checked = check_answer(self.root, 'Очевидно, это работает.')
        self.assertGreater(checked['warning_count'], 0)
        self.assertFalse(checked['blocking'])
        (self.root/'check_answer.py').write_text('raise RuntimeError("broken")', encoding='utf-8')
        checked = check_answer(self.root, 'Ответ.')
        self.assertEqual(checked['status'], 'failed')
        self.assertTrue(checked['blocking'])

    def test_editor_does_not_force_full_protocol_into_unrelated_document(self):
        from protocol_atlas.editor_ai import AIEditor
        from protocol_atlas.catalog import digest, REQUIRED_SOURCES
        for name in REQUIRED_SOURCES:
            target = self.root / name
            if not target.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, target)
        path = self.root/'memory/STATE.md'
        path.write_text('# Состояние\n\nНачало.\n', encoding='utf-8')
        editor = AIEditor(self.root)
        preview = editor.preview(dict(path='memory/STATE.md', text=path.read_text(encoding='utf-8'),
                                      expected_sha256=digest(path.read_bytes()), intent='Уточнить', paths=[]))
        self.assertNotIn('PROTOCOL.md', [item['path'] for item in preview['coverage']])
        self.assertEqual(preview['runtime']['mode'], 'compiled')


    def test_unknown_stage_blocks_call_and_selected_stage_reaches_request(self):
        with self.assertRaises(ValueError):
            self.tasks.start({**self.payload,'protocol_stage':'99'})
        self.editor.call.assert_not_called()
        prepared=self.tasks.prepare({**self.payload,'protocol_stage':'7'})
        self.assertEqual(prepared['runtime']['stage'],'7')
        self.assertEqual({r['section'] for r in prepared['runtime']['rules']}-CORE_SECTIONS, {'7.1','7.2','7.3'})


if __name__ == '__main__':
    unittest.main()
