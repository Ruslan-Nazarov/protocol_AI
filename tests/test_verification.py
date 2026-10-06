import copy
import json
from pathlib import Path
import tempfile
import unittest

from protocol_atlas.project_runtime import ProjectRuntime, canonical
from protocol_atlas.catalog import digest
from protocol_atlas.runtime_cli import schema
from scripts.run_logic_demo import candidate

ROOT=Path(__file__).resolve().parents[1]

class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.r=ProjectRuntime(self.root);self.r.dispatch('init')
        self.stage={'id':'s','title':'s','requires':[],'type':'formal','volume':'one','complexity':'bounded',
                    'criteria':[{'id':'review','text':'meaning','kind':'agent_review'}]}
        self.op('start',goal='test',stages=[self.stage])
        (self.root/'proof.json').write_text('{}')
    def op(self,action,**p):
        return self.r.dispatch(action,{'expected_revision':self.r.status()['revision'],**p})
    def get(self):return self.r.status()['tasks'][0]['stages'][0]
    def check(self):
        self.op('check',stage_id='s',criterion_id='review',artifacts=['proof.json'],passed=True,evidence='agent only')
    def complete(self):
        return self.op('complete_stage',stage_id='s',summary='done',artifacts=['proof.json'])
    def proof(self):
        c=json.loads((ROOT/'examples/logic/syllogism.json').read_text(encoding='utf-8'))
        self.op('select_logic',stage_id='s',contract=c)
        self.op('begin_stage',stage_id='s')
        (self.root/'proof.json').write_text(json.dumps(candidate(self.get()['logic_selection'])),encoding='utf-8')
        self.op('check_logic',stage_id='s',candidate_path='proof.json',artifacts=['proof.json'])
        self.check();self.complete()
    def test_formal_mode_cannot_be_satisfied_by_review(self):
        self.op('set_verification',stage_id='s',mode='formal',reason='formal required')
        self.check()
        with self.assertRaises(ValueError):self.complete()
        self.proof()
        summary=self.get()['evidence_summary']
        self.assertEqual(summary['formal_conformance'],'passed')
        for prop in ('premise_truth','source_translation','actual_model_logic_use'):
            self.assertEqual(summary[prop],'not_checked')
        self.assertFalse(summary['external_enforcement'])
    def test_policy_change_needs_new_evidence_and_survives_plan(self):
        self.check();self.complete()
        self.op('set_verification',stage_id='s',mode='criteria',reason='explicit scope')
        self.assertEqual(self.get()['status'],'needs_recheck')
        with self.assertRaises(ValueError):self.complete()
        changed={**self.stage,'title':'new title'}
        self.op('plan',stages=[changed])
        self.assertEqual(self.get()['verification']['mode'],'criteria')
        self.check();self.complete()
        self.op('set_verification',stage_id='s',mode='formal',reason='stronger')
        with self.assertRaises(ValueError):self.op('plan',stages=[{**self.stage,'id':'other'}])
    def test_admission_returns_only_formal_result_and_rejects_changes(self):
        with self.assertRaises(ValueError):self.r.dispatch('admit_result',{'stage_id':'s'})
        self.proof()
        value=self.r.dispatch('admit_result',{'stage_id':'s'})
        self.assertEqual(value['answer'],'Все S являются P.')
        self.assertNotIn('done',value['answer'])
        (self.root/'proof.json').write_text('{}')
        with self.assertRaises(ValueError):self.r.dispatch('admit_result',{'stage_id':'s'})
    def test_unknown_and_failed_do_not_become_passed(self):
        self.assertEqual(self.get()['evidence_summary']['formal_conformance'],'not_checked')
        self.proof()
        raw=json.loads((self.root/'proof.json').read_text());raw['steps'][0]['formula'][1]='G'
        (self.root/'proof.json').write_text(json.dumps(raw))
        self.op('begin_stage',stage_id='s')
        self.op('check_logic',stage_id='s',candidate_path='proof.json',artifacts=['proof.json'])
        self.assertEqual(len(self.get()['result_history']),1)
        self.assertEqual(self.get()['evidence_summary']['formal_conformance'],'failed')
        with self.assertRaises(ValueError):self.r.dispatch('admit_result',{'stage_id':'s'})
    def test_empirical_mode_requires_command_and_import_requires_recheck(self):
        self.op('set_verification',stage_id='s',mode='empirical',reason='measurement')
        self.check()
        with self.assertRaises(ValueError):self.complete()
        self.op('set_verification',stage_id='s',mode='formal',reason='proof')
        self.proof()
        package=self.r.dispatch('export')
        self.op('import',package=package)
        self.assertEqual(self.get()['verification']['mode'],'formal')
        with self.assertRaises(ValueError):self.r.dispatch('admit_result',{'stage_id':'s'})
    def test_schema_exposes_operations(self):
        self.assertIn('mode',schema('set_verification')['properties'])
        self.assertEqual(schema('admit_result')['required'],['stage_id'])
