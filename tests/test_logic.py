import copy
import io
import itertools
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from protocol_atlas.logic import PROFILES, apply_rule, select, verify, formula, Violation
from protocol_atlas.project_runtime import ProjectRuntime
from protocol_atlas.runtime_cli import mcp, schema
from scripts.run_logic_demo import candidate, mutations

ROOT = Path(__file__).resolve().parents[1]


def contract():
    return json.loads((ROOT/'examples/logic/syllogism.json').read_text(encoding='utf-8'))


def propositional():
    c = contract()
    c.update(profile='classical-propositional-v1', enabled_rules=list(PROFILES['classical-propositional-v1']['rules']),
             selection_reason='Проверяем условный переход между высказываниями.',
             alternatives=[{'profile':'syllogistic-universal-v1','reason_not_selected':'Нужна импликация высказываний.'}])
    c['symbols'] = [{'id': s, 'symbol': s, 'meaning': 'Утверждение '+s} for s in ('S', 'M', 'P')]
    c['premises'] = [{'id': 'p'+str(i), 'formula': f, 'basis': {'kind': 'assumption', 'reason': 'Условная посылка примера'}}
                     for i, f in enumerate(['S', ['implies', 'S', 'P']], 1)]
    return c


class LogicTests(unittest.TestCase):
    def setUp(self):
        self.selection = select(contract())
        self.good = candidate(self.selection)

    def check(self, value, selection=None):
        return verify(json.dumps(value, ensure_ascii=False), selection or self.selection)

    def test_valid_proof_has_conditional_scope_and_generated_text(self):
        result = self.check(self.good)
        self.assertTrue(result['admitted'])
        self.assertEqual(result['answer'], 'Все S являются P.')
        self.assertEqual(result['conclusions'][0]['premise_ids'], ['p1','p2'])
        self.assertEqual(result['semantic_status'], 'unverified')

    def test_all_injected_faults_are_caught_with_original_preserved(self):
        # Derive the condition from each contract, not from a list of banned names.
        for required in ('S', 'T'):
            c = contract()
            c['symbols'][0]['symbol'] = required
            c['premises'][0]['formula'][1] = required
            selected = select(c)
            alternatives = list('ABCDEFGHIJKLMNOPQRSTUVWXYZ') + [
                required.lower(), 'Ѕ' if required == 'S' else 'Т',
                ' '+required, required+' ', required*2, 'Other_17', '',
            ]
            for actual in alternatives:
                with self.subTest(required=required, actual=actual):
                    value = candidate(selected)
                    value['steps'][0]['formula'][1] = actual
                    raw = json.dumps(value, ensure_ascii=False)
                    result = verify(raw, selected)
                    self.assertEqual(result['admitted'], actual == required)
                    self.assertEqual(result['raw'], raw)
                    if actual != required:
                        self.assertEqual(result['answer'], '')
                        self.assertTrue(result['violations'])
                    if actual in ('M', 'P'):
                        # A declared symbol can still be wrong in this position.
                        self.assertEqual(result['violations'][0]['code'], 'invalid_conclusion')
        for name, value in mutations(self.good).items():
            with self.subTest(name=name):
                raw = json.dumps(value, ensure_ascii=False)
                result = verify(raw, self.selection)
                self.assertFalse(result['admitted'])
                self.assertEqual(result['raw'], raw)
                self.assertTrue(result['violations'])
                self.assertEqual(result['answer'], '')

    def test_quoted_G_is_not_a_global_ban(self):
        c = contract(); c['sources']['note'] = 'Пример неверного обозначения: G.'
        selected = select(c)
        self.assertTrue(self.check(candidate(selected), selected)['admitted'])
        # G is also valid in the same scope when it denotes a different concept.
        c['symbols'][2]['symbol'] = 'G'
        c['premises'][1]['formula'][2] = 'G'
        selected = select(c); value = candidate(selected)
        value['steps'][0]['formula'][2] = 'G'
        self.assertTrue(self.check(value, selected)['admitted'])

    def test_explicit_rename_requires_new_contract_and_candidate(self):
        c = contract(); c['version'] = 2; c['symbols'][0]['symbol'] = 'G'; c['premises'][0]['formula'][1] = 'G'
        selected = select(c); value = candidate(selected); value['steps'][0]['formula'][1] = 'G'
        self.assertTrue(self.check(value, selected)['admitted'])
        self.assertFalse(self.check(self.good, selected)['admitted'])

    def test_same_symbol_new_meaning_invalidates_old_candidate(self):
        c = contract(); c['symbols'][0]['meaning'] = 'круги'; c['version'] = 2
        self.assertFalse(self.check(self.good, select(c))['admitted'])

    def test_forged_contract_and_checker_versions_are_rejected(self):
        selected = copy.deepcopy(self.selection); selected['contract']['symbols'][0]['meaning'] = 'круги'
        self.assertEqual(self.check(self.good, selected)['violations'][0]['code'], 'contract_changed')
        selected = copy.deepcopy(self.selection); selected['checker_sha256'] = 'old'
        self.assertEqual(self.check(self.good, selected)['violations'][0]['code'], 'checker_changed')

    def test_unknown_profile_rule_and_fabricated_quote_cannot_be_selected(self):
        for key, value in [('profile','invented'),('enabled_rules',['anything'])]:
            c = contract(); c[key] = value
            with self.assertRaises(ValueError):select(c)
        c = contract(); c['premises'][0]['basis']['quote'] = 'Нет в источнике'
        with self.assertRaises(ValueError):select(c)

    def test_disabled_rule_is_not_silently_reintroduced(self):
        c = contract(); c['enabled_rules'] = ['no_conversion']; selected = select(c)
        self.assertFalse(self.check(candidate(selected), selected)['admitted'])

    def test_duplicate_keys_cycles_and_no_conclusion_are_rejected(self):
        self.assertFalse(verify('{"scope":"a","scope":"b"}', self.selection)['admitted'])
        c = copy.deepcopy(self.good); c['steps'][0]['inputs'][0] = 't1'
        self.assertFalse(self.check(c)['admitted'])
        c = copy.deepcopy(self.good); c['conclusions'] = []
        self.assertFalse(self.check(c)['admitted'])

    def test_oversized_and_deep_candidates_are_not_executed(self):
        for raw in ('x'*64001, '['*2000+'0'+']'*2000, '__import__("os").system("bad")'):
            self.assertFalse(verify(raw, self.selection)['admitted'])

    def test_propositional_choice_executes_different_language_and_rule(self):
        selected = select(propositional())
        c = candidate(selected); c['steps'] = [{'id':'t1','rule':'modus_ponens','inputs':['p1','p2'],'formula':'P'}]
        self.assertTrue(self.check(c, selected)['admitted'])
        self.assertFalse(self.check(candidate(selected), selected)['admitted'])

    def test_long_trace_late_drift_and_restored_selection(self):
        c = propositional(); c['premises'][0]['formula'] = ['and','S','P']
        selected = json.loads(json.dumps(select(c)))
        value = candidate(selected)
        value['steps'] = [{'id':'t'+str(i),'rule':'and_left','inputs':['p1'],'formula':'S'} for i in range(100)]
        value['conclusions'] = ['t99']
        self.assertTrue(self.check(value, selected)['admitted'])
        value['steps'][-1]['formula'] = 'G'
        self.assertEqual(self.check(value, selected)['violations'][0]['where'], 'steps[99].formula')

    def test_semantic_translation_is_not_falsely_certified(self):
        c = contract(); c['premises'][0]['formula'] = ['all','P','M']
        # Exact quotations cannot prove that the agent translated them faithfully.
        selected = select(c); value = candidate(selected); value['steps'][0]['formula'] = ['all','P','P']
        result = self.check(value, selected)
        self.assertTrue(result['admitted'])
        self.assertEqual(result['semantic_status'], 'unverified')

    def test_rules_preserve_truth_in_exhaustive_small_models(self):
        examples = {
            'barbara': [('all','S','M'),('all','M','P')],
            'celarent': [('all','S','M'),('no','M','P')],
            'no_conversion': [('no','S','P')],
            'modus_ponens': ['S',('implies','S','P')],
            'modus_tollens': [('implies','S','P'),('not','P')],
            'and_intro': ['S','P'], 'and_left': [('and','S','P')],
            'and_right': [('and','S','P')], 'double_negation': [('not',('not','S'))],
        }
        def truth(f, world):
            if isinstance(f, str):return world[f]
            op, *args = f
            if op == 'all':return world[args[0]] <= world[args[1]]
            if op == 'no':return not (world[args[0]] & world[args[1]])
            if op == 'not':return not truth(args[0], world)
            if op == 'and':return truth(args[0], world) and truth(args[1], world)
            return not truth(args[0], world) or truth(args[1], world)
        for profile in PROFILES.values():
            for rule in profile['rules']:
                args = examples[rule]; result = apply_rule(rule, args)
                values = [set(),{0},{1},{0,1}] if rule in ('barbara','celarent','no_conversion') else [False,True]
                for combo in itertools.product(values, repeat=3):
                    world = dict(zip(('S','M','P'), combo))
                    if all(truth(a, world) for a in args):
                        self.assertTrue(truth(result, world), (rule, world))


class RuntimeLogicTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.runtime = ProjectRuntime(self.root)
        self.runtime.dispatch('init')
        self.stage = {'id':'proof','title':'Proof','requires':[],'type':'formal','volume':'one proof','complexity':'bounded',
                      'criteria':[{'id':'content','kind':'agent_review','text':'Inspect meaning separately'}]}
        self.write('start', goal='Deduce', stages=[self.stage])
        self.write('select_logic', stage_id='proof', contract=contract())
        self.selection = self.runtime.status()['tasks'][0]['stages'][0]['logic_selection']
        self.write('begin_stage', stage_id='proof')
        self.set_candidate(candidate(self.selection))

    def write(self, action, **payload):
        return self.runtime.dispatch(action, {'expected_revision':self.runtime.status()['revision'], **payload})

    def set_candidate(self, value):
        (self.root/'proof.json').write_text(json.dumps(value), encoding='utf-8')

    def check(self):
        return self.write('check_logic', stage_id='proof', candidate_path='proof.json', artifacts=['proof.json'])

    def finish(self):
        self.write('check', stage_id='proof', criterion_id='content', artifacts=['proof.json'], passed=True, evidence='Agent inspection only')
        return self.write('complete_stage', stage_id='proof', artifacts=['proof.json'], summary='Conditional result')

    def test_agent_review_cannot_replace_logic_check(self):
        with self.assertRaises(ValueError):self.finish()
        self.check(); self.finish()

    def test_latest_failure_blocks_and_keeps_original(self):
        self.check()
        bad = mutations(candidate(self.selection))['S_to_G']; self.set_candidate(bad)
        result = self.check()
        self.assertIn('G', result['operation']['check']['report']['raw'])
        with self.assertRaises(ValueError):self.finish()
        self.assertEqual(len(self.runtime.status()['tasks'][0]['stages'][0]['logic_checks']), 2)

    def test_result_change_and_checker_change_invalidate_completion(self):
        self.check(); self.finish()
        with patch('protocol_atlas.project_runtime.checker_version', return_value='changed'):
            self.assertEqual(self.runtime.status()['tasks'][0]['stages'][0]['status'], 'needs_recheck')
        (self.root/'proof.json').write_text('{}', encoding='utf-8')
        self.assertEqual(self.runtime.status()['tasks'][0]['stages'][0]['status'], 'needs_recheck')

    def test_reselection_requires_version_and_preserves_history(self):
        c = contract(); c['scope'] = 'new scope'
        with self.assertRaises(ValueError):self.write('select_logic',stage_id='proof',contract=c,change_reason='Scope changed')
        c['version'] = 2
        self.write('select_logic',stage_id='proof',contract=c,change_reason='Scope changed')
        stage = self.runtime.status()['tasks'][0]['stages'][0]
        self.assertEqual(stage['logic_history'][0]['selection'], self.selection)
        self.assertIn('new scope', self.runtime.dispatch('context')['text'])

    def test_replan_preserves_selection_and_cannot_remove_protected_stage(self):
        stage = {**self.stage, 'title':'Changed plan'}
        self.write('plan', stages=[stage])
        self.assertEqual(self.runtime.status()['tasks'][0]['stages'][0]['logic_selection'], self.selection)
        with self.assertRaises(ValueError):self.write('plan', stages=[{**stage, 'id':'bypass'}])

    def test_imported_success_requires_local_check(self):
        self.check(); self.finish()
        package = self.runtime.dispatch('export')
        with tempfile.TemporaryDirectory() as folder:
            other = ProjectRuntime(folder)
            (Path(folder)/'proof.json').write_bytes((self.root/'proof.json').read_bytes())
            other.dispatch('import', {'expected_revision':0,'package':package})
            stage = other.status()['tasks'][0]['stages'][0]
            self.assertEqual(stage['logic_checks'][0]['origin'], 'imported')
            self.assertFalse(other.logic_check_current(stage))

    def test_mcp_exposes_executable_checks_and_contract(self):
        out = io.StringIO()
        mcp(self.runtime, io.StringIO(json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/list'})+'\n'), out)
        names = {t['name'] for t in json.loads(out.getvalue())['result']['tools']}
        self.assertTrue({'protocol_select_logic','protocol_check_logic','protocol_logic_profiles'} <= names)
        self.assertIn('contract', schema('select_logic')['required'])
        self.assertEqual(set(self.runtime.dispatch('logic_profiles')['profiles']), set(PROFILES))
        self.assertIn('all(S,M)', self.runtime.dispatch('context')['text'])

    def test_installed_engine_contains_checker_and_runs_cli(self):
        import subprocess
        from protocol_atlas.runtime_install import install
        install(self.root, 'api', source=ROOT)
        runner = self.root/'.protocol/engine/runner.py'
        payload = {'expected_revision':self.runtime.status()['revision'],'stage_id':'proof',
                   'candidate_path':'proof.json','artifacts':['proof.json']}
        (self.root/'request.json').write_text(json.dumps(payload), encoding='utf-8')
        result = subprocess.run([sys.executable, '-X', 'utf8', str(runner), 'check_logic', '--project', str(self.root),
                                 '--input', str(self.root/'request.json')], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['operation']['check']['report']['admitted'])


if __name__ == '__main__':unittest.main()
