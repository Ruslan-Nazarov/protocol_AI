from pathlib import Path
import json
import shutil
import tempfile
import unittest

from protocol_atlas.memory import MemoryStore
from protocol_atlas.regulator import simulate, RECOMMENDED
from protocol_atlas.requirements import inventory

ROOT = Path(__file__).resolve().parents[1]


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in ('PROTOCOL.md', 'check_answer.py', 'memory', 'atlas', 'docs'):
            source, target = ROOT / name, self.root / name
            shutil.copytree(source, target) if source.is_dir() else shutil.copy2(source, target)
        self.store = MemoryStore(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def save(self, key, basis=None, revision=None, statement='Содержание'):
        return self.store.save({'id': key, 'title': key, 'statement': statement,
                                'expected_revision': revision, 'basis': basis or []})

    def ref(self, key, revision=1):
        return {'type': 'record', 'id': key, 'revision': revision}

    def test_checked_response_is_bound_to_assembly_and_does_not_change_memory(self):
        self.save('a')
        payload={'ids':['a'],'goal':'Продолжить'}
        assembly=self.store.assemble(payload)
        text=json.dumps({'claims':[{'type':'record','ref_id':'r1'},
            {'type':'proposal','text':'Новый вариант','basis_refs':['r1'],'need':None}]})
        result=self.store.check_response({**payload,'assembly_id':assembly['assembly_id'],'text':text})
        self.assertEqual(result['claims'][1]['status'],'proposed')
        self.assertEqual(self.store.get('a')['revision'],1)
        self.save('a',revision=1,statement='Изменено')
        with self.assertRaisesRegex(ValueError,'Снимок'):
            self.store.check_response({**payload,'assembly_id':assembly['assembly_id'],'text':text})

    def test_revisions_pin_history_and_propagate_recheck(self):
        self.save('a'); self.save('b', [self.ref('a')]); self.save('c', [self.ref('b')])
        self.save('a', revision=1, statement='Изменение')
        self.assertEqual(self.store.get('a', 1)['statement'], 'Содержание')
        self.assertEqual(set(self.store.list()['rechecks']), {'b', 'c'})
        context = self.store.assemble({'ids': ['c'], 'goal': 'Продолжить'})
        self.assertEqual(context['status'], 'blocked')
        self.assertEqual(context['included'], [
            {'id': 'a', 'revision': 1}, {'id': 'b', 'revision': 1}, {'id': 'c', 'revision': 1}])
        with self.assertRaises(ValueError):
            self.store.acknowledge('b', {'revision': 1, 'evidence': 'Проверено'})
        self.save('b', [self.ref('a', 2)], revision=1)
        self.store.acknowledge('b', {'revision': 2, 'evidence': 'Сверено с основанием a@2'})
        self.save('c', [self.ref('b', 2)], revision=1)
        self.store.acknowledge('c', {'revision': 2, 'evidence': 'Сверено с b@2'})
        self.assertEqual(self.store.assemble({'ids': ['c'], 'goal': 'Продолжить'})['status'], 'ready')

    def test_cycle_and_concurrent_edit_rejected(self):
        self.save('a'); self.save('b', [self.ref('a')])
        with self.assertRaisesRegex(ValueError, 'Цикл'):
            self.save('a', [self.ref('b')], revision=1)
        with self.assertRaisesRegex(ValueError, 'Версия'):
            self.save('a', revision=2)
        self.assertEqual(self.store.get('a')['revision'], 1)

    def test_import_is_idempotent_source_changes_keep_snapshot(self):
        first = self.store.import_sources()
        self.assertGreater(first['imported_revisions'], 30)
        self.assertTrue(any(r['basis'][0]['path'] == 'memory/GLOSSARY.md' for r in first['records']))
        self.assertEqual(self.store.import_sources()['imported_revisions'], 0)
        source = next(r for r in first['records'] if r['basis'][0]['path'] == 'memory/STATE.md')
        self.save('dependent', [self.ref(source['id'])])
        path = self.root / 'memory/STATE.md'
        path.write_text(path.read_text(encoding='utf-8') + '\nНовые данные\n', encoding='utf-8')
        self.assertIn('dependent', self.store.list()['rechecks'])
        old = source['basis'][0]
        self.assertNotIn('Новые данные', self.store.source(old['path'], old['sha256'])['text'])
        with self.assertRaises(ValueError):
            self.store.acknowledge(source['id'], {'revision': 1, 'evidence': 'Старые данные'})

    def test_no_silent_context_truncation_or_arbitrary_source(self):
        self.save('long', statement='X' * 2000)
        result = self.store.assemble({'ids': ['long'], 'goal': 'Цель', 'budget': 500})
        self.assertTrue(result['overflow'])
        self.assertIn('X' * 2000, result['context'])
        with self.assertRaises(FileNotFoundError):
            self.store.source('.env', 'unknown')

    def test_repeated_headings_and_parent_context_are_imported(self):
        (self.root/'memory/EXTRA.md').write_text('# Пример\n\nВводное ограничение.\n\n## Повтор\nПервое основание.\n\n## Повтор\nВторое основание.\n',encoding='utf-8')
        records = self.store.import_sources()['records']
        extra = [r for r in records if r['basis'][0]['path']=='memory/EXTRA.md']
        self.assertEqual(len(extra), 3)
        self.assertEqual(len({r['id'] for r in extra}), 3)
        self.assertEqual({r['statement'] for r in extra}, {'Вводное ограничение.','Первое основание.','Второе основание.'})

    def test_import_does_not_overwrite_manual_revision_or_false_provenance(self):
        source = self.store.import_sources()['records'][0]
        edited = self.store.save({**source,'expected_revision':source['revision'], 'statement':'Ручная гипотеза', 'basis':[], 'origin':'source_import'})
        self.assertEqual(edited['origin'],'manual')
        self.assertEqual(edited['status'],'proposed')
        imported = self.store.import_sources()
        self.assertIn(source['id'],imported['manual_records_preserved'])
        self.assertEqual(self.store.get(source['id'])['statement'],'Ручная гипотеза')

    def test_inventory_keeps_every_source_block_and_exact_clauses(self):
        result = inventory(self.root)
        self.assertTrue(result['coverage']['complete'])
        self.assertGreater(len(result['cards']), 100)
        for card in result['cards']:
            self.assertTrue(all(clause in card['text'] for clause in card['clauses']))
            self.assertGreaterEqual(card['source']['end_line'], card['source']['start_line'])


class RegulatorTests(unittest.TestCase):
    def run_case(self, **changes):
        return simulate({'policy': RECOMMENDED, **changes})

    def success(self, **changes):
        return {'type': 'success', 'a_passed': True, 'b_passed': True, **changes}

    def test_success_series_only_unlocks_single_probe(self):
        result = self.run_case(events=[self.success()] * 3 + [self.success(type='probe_success')] * 2)
        self.assertEqual(result['profile']['C'], 5)
        self.assertEqual(result['history'][-1]['outcome'], 'blocked')

    def test_second_model_cannot_raise_calibration(self):
        result = self.run_case(events=[self.success(second_model_only=True)] * 3)
        self.assertEqual(result['profile']['C'], 4)
        self.assertEqual(result['profile']['series'], 0)

    def test_failure_silent_recovery_and_bounds(self):
        result = self.run_case(profile={'C': 1, 'D': 3}, events=[{'type': 'silent_error'}, self.success(), self.success()])
        self.assertEqual(result['profile']['C'], 1)
        self.assertEqual(result['profile']['D'], 1)
        self.assertFalse(result['profile']['silent'])
        result = self.run_case(events=[self.success(a_passed=False)])
        self.assertEqual(result['history'][0]['outcome'], 'error')

    def test_load14_external_gate_and_model_change(self):
        result = self.run_case(factors=dict.fromkeys('VLHN', 3), exact_count_bonus=2)
        self.assertEqual(result['load']['raw'], 14)
        self.assertEqual(result['gate'], 'split')
        result = self.run_case(profile={'D': 3}, external_or_irreversible=True, decision_depth=2)
        self.assertEqual(result['gate'], 'decision')
        result = self.run_case(profile={'C': 12, 'D': 3}, events=[{'type': 'model_change'}])
        self.assertEqual((result['profile']['C'], result['profile']['D']), (4, 1))

    def test_repeated_silent_error_preserves_original_recovery_target(self):
        result = self.run_case(policy={**RECOMMENDED,'recovery':'restore_previous'},profile={'D':3},
                               events=[{'type':'silent_error'},{'type':'silent_error'},self.success(),self.success()])
        self.assertEqual(result['profile']['D'],3)


if __name__ == '__main__':
    unittest.main()
