import copy
import json
import unittest
from scripts.run_logic_pilot import cases,messages,reference,RESERVE,LIMIT,report
from protocol_atlas.logic import verify

class PilotTests(unittest.TestCase):
    def test_inputs_fit_reserved_budget_and_expected_proofs_pass(self):
        self.assertLessEqual(12*RESERVE,LIMIT)
        for case in cases():
            for arm in ('baseline','instructions'):
                self.assertLess(len(json.dumps(messages(case,arm),ensure_ascii=False).encode()),20000)
            raw=json.dumps(case['expected'])
            self.assertTrue(reference(raw,case))
            self.assertTrue(verify(raw,case['selection'])['admitted'])
    def test_formal_success_is_not_task_success(self):
        case=cases()[0];wrong=copy.deepcopy(case['expected']);wrong['conclusions']=['p1']
        self.assertTrue(verify(json.dumps(wrong),case['selection'])['admitted'])
        self.assertFalse(reference(json.dumps(wrong),case))
        self.assertFalse(reference('not json',case))
    def test_missing_call_not_counted_as_correct(self):
        r=report({'cases':cases()},[{'status':'failed'}])
        self.assertEqual(r['completed_calls'],0)
        self.assertIsNone(r['arms']['baseline']['miss_rate']['value'])
