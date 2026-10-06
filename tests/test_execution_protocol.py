import copy
import importlib.util
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('execution_audit',ROOT/'scripts/verify_execution_protocol.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)


class ExecutionProtocolTests(unittest.TestCase):
    def test_all_requirements_have_checks_routes_and_source_mapping(self):
        data=audit.validate(ROOT)
        self.assertEqual(len(data['rules']),32)

    def test_required_route_scenarios(self):
        results=audit.scenarios(audit.validate(ROOT))
        self.assertEqual(results['missing_data'],'wait')
        self.assertEqual(results['unavailable_practice'],'wait')
        self.assertEqual(results['changed_premise_repeats_dependencies'],'done')

    def test_unknown_or_missing_return_origin_is_not_silently_skipped(self):
        data=audit.validate(ROOT)
        with self.assertRaises(AssertionError):audit.walk(data,{'6.1':['fail']})
        with self.assertRaises(AssertionError):audit.walk(data,{'6.1':['approved_by_model']})
        for r in data['rules']:
            self.assertEqual(r['on_unknown'],'wait')

    def test_repeated_failure_does_not_become_success(self):
        data=audit.validate(ROOT)
        with self.assertRaises(AssertionError):audit.walk(data,{'6.1':['fail']*100},'6.1')


if __name__=='__main__':unittest.main()
