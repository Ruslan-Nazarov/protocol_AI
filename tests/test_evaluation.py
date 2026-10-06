import copy
import unittest
from protocol_atlas.evaluation import summarize

def row(ident,violation,detected,**extra):
    return dict(run_id='r',case_id=ident,cluster_id='same_task',reference_origin='authored_reference',
                violation=violation,detected=detected,admitted=None,task_success=None,
                violation_at_ms=None,detected_at_ms=None,cost_usd=None,latency_ms=None,**extra)

class EvaluationTests(unittest.TestCase):
    def test_counts_denominators_unknowns_and_costs(self):
        rows=[row('a',True,True),row('b',True,False),row('c',False,True),row('d',False,False),row('e',None,True),row('f',True,None)]
        rows[0].update(violation_at_ms=10,detected_at_ms=25,cost_usd=.1)
        r=summarize(rows,list('abcdefg'))
        self.assertEqual(r['miss_rate']['value'],.5);self.assertEqual(r['false_alarm_rate']['value'],.5)
        self.assertEqual(r['counts']['unknown_detection'],1);self.assertEqual(r['counts']['unknown_reference'],1)
        self.assertEqual(r['delay_ms']['mean'],15);self.assertEqual(r['delay_ms']['undetected_or_unknown'],2)
        self.assertIsNone(r['cost_usd']['total']);self.assertEqual(r['cost_usd']['known_subtotal'],.1)
        self.assertEqual(r['unobserved_cases'],['g']);self.assertEqual(r['clusters'],1)
    def test_empty_is_not_perfect(self):
        r=summarize([],['a'])
        self.assertIsNone(r['miss_rate']['value']);self.assertIsNone(r['false_alarm_rate']['value'])
        self.assertIsNone(r['cost_usd']['total']);self.assertIsNone(r['uncertainty_reduction'])
    def test_invalid_data_rejected(self):
        good=row('a',True,True)
        for update in ({'cost_usd':-1},{'latency_ms':float('nan')},{'violation':1},{'detected':False,'detected_at_ms':1},
                       {'violation_at_ms':20,'detected_at_ms':10},{'case_id':'outside'}):
            with self.subTest(update=update),self.assertRaises(ValueError):summarize([{**good,**update}],['a'])
        with self.assertRaises(ValueError):summarize([good,good],['a'])
    def test_always_reject_and_always_accept_are_not_perfect(self):
        r=summarize([row('a',True,True),row('b',False,True)],['a','b'])
        self.assertEqual(r['false_alarm_rate']['value'],1)
        r=summarize([row('a',True,False),row('b',False,False)],['a','b'])
        self.assertEqual(r['miss_rate']['value'],1)
