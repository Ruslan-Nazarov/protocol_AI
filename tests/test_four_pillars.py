import copy
import unittest
from unittest.mock import patch

from protocol_atlas import four_pillars as fp
from protocol_atlas.logic import canonical


class FourPillarsTests(unittest.TestCase):
    def setUp(self):
        self.contract = fp.make_contract()
        self.candidate = fp.example_candidate(self.contract)

    def reject_before_execution(self, candidate, contract=None):
        with patch.object(fp, '_write') as write:
            result = fp.run(canonical(candidate), contract or self.contract)
        self.assertFalse(result['admitted'])
        self.assertEqual(result['answer'], '')
        self.assertEqual(result['status'], 'rejected')
        write.assert_not_called()

    def test_real_file_states_and_causal_answer(self):
        result = fp.run(canonical(self.candidate),self.contract)
        self.assertTrue(result['admitted'], result)
        self.assertEqual([r['actual_hex'] for r in result['observations']],['41','4142','414243'])
        self.assertEqual(result['phases'],['received','contract_pinned','prediction_checked',
                                          'execution_started','reality_checked','admitted'])
        self.assertIn('Последовательные добавления',result['answer'])
        self.assertEqual(result['api_calls'],0)

    def test_correct_boundary_variants_are_retained(self):
        for initial, chunks, expected in [(b'',(b'',),''),
                ('Я'.encode(),('ё'.encode(),b'\x00'), 'd0afd19100'),
                (b'\xff',(b'\x01',b'\x02',b'\x03',b'\x04'),'ff01020304'),
                (b'x'*64,(b'y'*64,)*4, (b'x'*64+b'y'*256).hex())]:
            with self.subTest(expected=expected[:20]):
                contract=fp.make_contract(initial,chunks)
                result=fp.run(canonical(fp.example_candidate(contract)),contract)
                self.assertTrue(result['admitted'], result)
                self.assertEqual(result['observations'][-1]['actual_hex'],expected)

    def test_alternative_valid_proof_is_retained(self):
        proof=self.candidate['logic']
        proof['steps'].extend([
            {'id':'pair','rule':'and_intro','inputs':['derived2','initial'],'formula':['and','S2','S0']},
            {'id':'final','rule':'and_left','inputs':['pair'],'formula':'S2'}])
        proof['conclusions']=['final']
        self.assertTrue(fp.run(canonical(self.candidate),self.contract)['admitted'])

    def test_missing_any_pillar_is_rejected(self):
        for key in ('world','development','logic','reality'):
            candidate=copy.deepcopy(self.candidate);del candidate[key]
            with self.subTest(key=key):self.reject_before_execution(candidate)

    def test_declaration_definition_instruction_cannot_substitute(self):
        for text in ('Файл — последовательность байтов.', 'Выполните запись и проверьте.', 'Ответ правильный.'):
            self.reject_before_execution({'answer':text})
        self.candidate['answer']='Проверено: всё верно.'
        self.reject_before_execution(self.candidate)

    def test_answer_revision_is_not_subject_development(self):
        self.candidate['development']=[{'draft':'first'},{'draft':'improved'}]
        self.reject_before_execution(self.candidate)

    def test_wrong_transition_and_skipped_step(self):
        for bad in ([{'event':'append1','before_hex':'41','after_hex':'42'},self.candidate['development'][1]],
                    self.candidate['development'][1:]):
            candidate=copy.deepcopy(self.candidate);candidate['development']=bad
            self.reject_before_execution(candidate)

    def test_different_world_and_fake_observation(self):
        for field,value in [('world','another-file'),('reality',{'passed':True}),('observations',[{'passed':True}])]:
            candidate=copy.deepcopy(self.candidate);candidate[field]=value
            self.reject_before_execution(candidate)

    def test_invalid_inference_and_unrelated_true_conclusion(self):
        candidate=copy.deepcopy(self.candidate);candidate['logic']['steps'][0]['formula']='S2'
        self.reject_before_execution(candidate)
        self.candidate['logic']['conclusions']=['initial']
        self.reject_before_execution(self.candidate)

    def test_contract_change_and_relaxed_rules_rejected(self):
        changed=fp.make_contract(b'A',(b'X',b'C'))
        self.reject_before_execution(self.candidate,changed)
        changed=copy.deepcopy(self.contract);changed['logic']['contract']['premises'][0]['formula']='S2'
        self.reject_before_execution(self.candidate,changed)
        changed=copy.deepcopy(self.contract);changed['budget']['attempts']=20
        self.reject_before_execution(self.candidate,changed)

    def test_contradicting_reality_stops_dependent_execution(self):
        with patch.object(fp,'_observe',side_effect=[b'A',b'AX']) as observe:
            result=fp.run(canonical(self.candidate),self.contract)
        self.assertFalse(result['admitted'])
        self.assertEqual(result['status'],'contradicted')
        self.assertEqual(result['answer'],'')
        self.assertEqual(observe.call_count,2)
        self.assertEqual(result['observations'][-1]['actual_hex'],'4158')

    def test_unavailable_reality_is_not_a_discovered_falsehood(self):
        for method in ('_write','_observe'):
            with self.subTest(method=method),patch.object(fp,method,side_effect=OSError('injected I/O failure')):
                result=fp.run(canonical(self.candidate),self.contract)
                self.assertFalse(result['admitted'])
                self.assertEqual(result['status'],'unverified')
                self.assertEqual(result['answer'],'')

    def test_no_cached_admission_or_supplied_report(self):
        raw=canonical(self.candidate)
        admitted=fp.run(raw,self.contract)
        self.reject_before_execution(admitted)
        with patch.object(fp,'_observe',side_effect=OSError('unavailable')):
            self.assertFalse(fp.run(raw,self.contract)['admitted'])

    def test_limits_duplicate_keys_and_malformed_input(self):
        for raw in ('x'*16001,'{"world":"a","world":"b"}','null','[]'):
            with self.subTest(raw=raw[:20]),patch.object(fp,'_write') as write:
                self.assertFalse(fp.run(raw,self.contract)['admitted']);write.assert_not_called()
        with self.assertRaises(ValueError):fp.make_contract(b'a'*65)
        with self.assertRaises(ValueError):fp.make_contract(additions=())


if __name__=='__main__':unittest.main()
