import json
import unittest

from protocol_atlas.context import compile_context, validate_response, context_need
from protocol_atlas.episodes import synthetic


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.record={'id':'a','revision':1,'kind':'decision','status':'accepted','current':True,
            'statement':'Предел действует только на R.','scope':'R','need':None,'transition':None,'verification':None,
            'basis':[{'type':'source','path':'test.md','sha256':'a'*64,'start_line':2,'end_line':2,
                      'quote':'Предел действует только на R.\n'}]}
        self.compiled=compile_context([self.record],'Продолжить')

    def check(self, claims):
        return validate_response(json.dumps({'claims':claims},ensure_ascii=False),self.compiled['references'])

    def test_source_and_record_are_lossless_without_repeated_text(self):
        self.assertEqual(self.compiled['context'].count(self.record['statement']),1)
        result=self.check([{'type':'record','ref_id':'r1'},{'type':'source','ref_id':'s1','quote':'только на R.'}])
        self.assertEqual(result['claims'][0]['record']['statement'],self.record['statement'])
        self.assertEqual(result['claims'][0]['record']['status'],'accepted')
        self.assertEqual(result['claims'][1]['source']['sha256'],'a'*64)
        self.assertEqual(result['meaning'],'unknown')

    def test_new_text_cannot_become_accepted_or_rewrite_record(self):
        for item in [{'type':'record','ref_id':'r1','text':'Другой предел'},
                     {'type':'proposal','text':'Изменить','basis_refs':[],'need':None,'status':'accepted'},
                     {'type':'source','ref_id':'s1','quote':'Для всех наборов.'},
                     {'type':'record','ref_id':'r999'}, {'type':[]}]:
            with self.subTest(item=item),self.assertRaises(ValueError):self.check([item])
        result=self.check([{'type':'proposal','text':'Изменить','basis_refs':['r1'],'need':None},
                          {'type':'inference','text':'Следствие','basis_refs':['s1'],'scope':None,'uncertainties':None}])
        self.assertEqual([c['status'] for c in result['claims']],['proposed','unverified'])

    def test_missing_basis_is_not_filled_by_assumption(self):
        with self.assertRaises(ValueError):
            self.check([{'type':'inference','text':'Следствие','basis_refs':[],'scope':None,'uncertainties':None}])

    def test_history_and_hypotheses_do_not_replace_accepted_record(self):
        old={**self.record,'current':False}
        proposal={**self.record,'id':'b','kind':'hypothesis','status':'proposed','statement':'Новый вариант','basis':[]}
        result=compile_context([old,proposal],'Продолжить')
        self.assertEqual(result['groups']['accepted'],[])
        self.assertEqual(result['groups']['historical_or_rejected'],['r1'])
        self.assertEqual(result['groups']['proposals_and_hypotheses'],['r2'])
        self.assertEqual(result['references']['r1']['status'],'accepted')
        self.assertIsNone(result['references']['r2']['need'])

    def test_need_checks_basis_before_suggesting_compression(self):
        self.assertEqual(context_need('ready',False,[],[])['action'],'use_exact')
        self.assertEqual(context_need('blocked',True,[],['a'])['action'],'revise_basis')
        self.assertEqual(context_need('blocked',True,[],[])['action'],'reduce_selection')

    def test_long_cases_keep_authored_memory_and_exact_source_selection(self):
        for case in ('revision','contradiction'):
            short,long=synthetic(case),synthetic('long-'+case)
            self.assertGreater(long['characters'],20000)
            self.assertEqual(short['exact_context'],long['exact_context'])
            self.assertEqual(short['tasks'],long['tasks'])
            self.assertLess(len(long['exact_context']['context']),6000)
            self.assertNotEqual(short['catalog_revision'],long['catalog_revision'])

    def test_unknown_root_uncertainties_remain_null(self):
        payload={'answers':[{'task_id':'check','claims':[{'type':'unknown','text':'Нет данных'}],'uncertainties':None}]}
        result=validate_response(json.dumps(payload),self.compiled['references'],[{'id':'check'}])
        self.assertIsNone(result['answers'][0]['uncertainties'])
        payload['answers'][0]['uncertainties']=[]
        with self.assertRaises(ValueError):validate_response(json.dumps(payload),self.compiled['references'],[{'id':'check'}])

    def test_explicit_legacy_hypothesis_status_is_grouped_without_inference(self):
        context=synthetic('contradiction')['exact_context']
        self.assertEqual(context['groups']['accepted'],['r1'])
        self.assertEqual(context['groups']['proposals_and_hypotheses'],['r2'])
        self.assertEqual(context['references']['r2']['status'],'hypothesis')
