import json
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import Mock
from unittest.mock import patch

from protocol_atlas.adaptive import AdaptiveTasks
from protocol_atlas.catalog import REQUIRED_SOURCES
from protocol_atlas.memory import MemoryStore
from protocol_atlas.math_checks import check_equation, check_prose
from protocol_atlas.retrieval import retrieve, changed_context, search_items
from protocol_atlas.source_editor import SourceConflict
from protocol_atlas.task_analysis import resolve_answer, transition_graph, analyze_text
from protocol_atlas.workflows import validate_plan


class ArithmeticTests(unittest.TestCase):
    def test_wrong_arithmetic_is_detected_in_prose_at_sentence_end(self):
        checks = check_prose('При равном распределении 120 / 3 = 50.')
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0]['computed'], '40')
        self.assertTrue(checks[0]['blocking'])

    def test_exact_decimal_and_fraction_arithmetic(self):
        for left,right in [('0.1+0.2','0.3'),(' 120 / 3 ','40'),('1/3+1/6','1/2'),('2^3','8')]:
            self.assertEqual(check_equation(left,right)['status'],'pass')

    def test_polynomial_identity_and_counterexample(self):
        self.assertEqual(check_equation('x*(x+1)','x*x+x')['status'],'pass')
        self.assertEqual(check_equation('(x+1)^2','x*x+1')['status'],'fail')

    def test_functions_variable_division_and_undefined_power_are_unknown(self):
        for expression in ['sqrt(x*x)','x/x','0**0','x**0','1/0']:
            self.assertEqual(check_equation(expression,'1')['status'],'unknown')

    def test_executable_and_resource_exhausting_input_are_not_run(self):
        for expression in ['__import__("os").system("echo bad")','(1+x)^999999','1e9999999999','x.__class__','[1]*999999']:
            self.assertEqual(check_equation(expression,'1')['status'],'unknown')

    def test_rounding_and_code_examples_do_not_become_hard_failures(self):
        self.assertFalse(check_prose('1 / 3 = 0.333.')[0]['blocking'])
        self.assertEqual(check_prose('```\n120 / 3 = 50\n```'),[])
        self.assertFalse(check_prose('Пример ошибки: 120 / 3 = 50.')[0]['blocking'])


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.references={'s1':{'type':'source','path':'test.md','sha256':'snapshot','start_line':1,'end_line':2,
                               'quote':'Предел равен пяти. Только для группы R.'}}
        self.events=[{'id':'e1','summary':'Зафиксирован состав запроса.','scope':'Не проверена истинность.'}]
        self.criteria=[{'id':'k1','text':'Показать условия.'}]
        self.answer={'claims':[{'type':'source','ref_id':'s1','quote':'Только для группы R.'}],
                     'transitions':[],'calculations':[],
                     'coverage':[{'criterion_id':'k1','state':'addressed','claim_ids':['c1'],'note':None}]}

    def resolve(self):
        return resolve_answer(json.dumps(self.answer,ensure_ascii=False),self.references,self.events,self.criteria)

    def test_exact_quote_and_criterion_mapping(self):
        result=self.resolve()
        self.assertIn('[ИЗ ИСТОЧНИКА]',result['answer'])
        self.assertFalse(result['blocking'])
        self.assertEqual(result['meaning'],'unknown')

    def test_fabricated_quote_and_missing_event_are_rejected(self):
        self.answer['claims'][0]['quote']='Во всех группах.'
        with self.assertRaises(ValueError):self.resolve()
        self.answer['claims']=[{'type':'verified','event_id':'unperformed-test'}]
        with self.assertRaises(ValueError):self.resolve()

    def test_checked_event_text_is_generated_by_application(self):
        self.answer['claims']=[{'type':'verified','event_id':'e1'}]
        self.assertIn('Не проверена истинность.',self.resolve()['answer'])
        self.answer['claims'][0]['text']='125 тестов пройдены'
        with self.assertRaises(ValueError):self.resolve()

    def test_missing_criterion_and_fake_claim_are_rejected(self):
        self.answer['coverage']=[]
        with self.assertRaises(ValueError):self.resolve()
        self.answer['coverage']=[{'criterion_id':'k1','state':'addressed','claim_ids':['c999'],'note':None}]
        with self.assertRaises(ValueError):self.resolve()

    def test_supported_wrong_calculation_blocks_acceptance(self):
        self.answer['calculations']=[{'left':'120/3','right':'50','meaning':'равное распределение','unit':'страниц в день'}]
        self.assertTrue(self.resolve()['blocking'])

    def test_valid_reference_does_not_prove_inference(self):
        self.answer['claims']=[{'type':'inference','text':'Предел действует во всех группах.',
                                'basis_refs':['s1'],'scope':None,'uncertainties':None}]
        result=self.resolve()
        self.assertEqual(result['claims'][0]['status'],'unverified')
        self.assertEqual(result['meaning'],'unknown')

    def test_transition_cycles_missing_bases_and_null_reasons(self):
        step={'id':'t1','inputs':['s1'],'output':'Новое состояние','change':'Сохраняем сведения',
              'reason':None,'conditions':None}
        self.assertEqual(len(transition_graph([step],self.references)['warnings']),2)
        with self.assertRaises(ValueError):transition_graph([{**step,'inputs':['missing']}],self.references)
        with self.assertRaises(ValueError):transition_graph([{**step,'inputs':['step:t1']}],self.references)


class RuntimeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'tests').mkdir()
        for name in REQUIRED_SOURCES:
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text('# Документ\n\nДоступные сведения.\n',encoding='utf-8')
        shutil.copyfile(Path(__file__).resolve().parents[1]/'check_answer.py',self.root/'check_answer.py')
        (self.root/'PROTOCOL.md').write_text('# Протокол\n\n## 1. Основания\n\nВводная связь.\n\n### 1.1 Хранение\n\nХраним локально.\n\nУсловие: только после принятия человеком.\n',encoding='utf-8')
        (self.root/'memory/GLOSSARY.md').write_text('# Словарь\n\n**Рекурсия.** Повторное обращение.\n',encoding='utf-8')
        self.memory=MemoryStore(self.root)
        self.editor=Mock()
        self.settings={'configured':True,'provider':'custom','endpoint':'http://localhost/v1','model':'one','api_key':'secret'}
        self.editor.settings.side_effect=lambda **kw:self.settings
        self.editor.call.return_value={'text':'Результат.','input_tokens':3,'output_tokens':4}
        self.store=AdaptiveTasks(self.root,self.editor,self.memory)
        self.store.configure({'expected_revision':0,'purpose':'Работа','requirements':'Сохранить основания',
                              'starting_point':'Исходные записи','character_budget':30000})
        self.payload={'goal':'Хранение','task_type':'Редактирование документов','volume':'Один пункт','complexity':'Предварительно',
                      'criteria':'Показать результат','materials':'Исходные сведения.'}

    def record(self, ident, kind='decision',status='accepted',basis=None):
        return self.memory.save({'id':ident,'title':ident,'kind':kind,'status':status,'statement':'Локальное хранение',
                                 'basis':basis or []})

    def run_task(self,payload=None):
        task=self.store.start(payload or self.payload)
        for _ in range(150):
            task=self.store.get(task['id'])
            if task['status']!='running':return task
            time.sleep(.01)
        self.fail('Worker did not finish')

    def accepted(self,task):
        return self.store.review({'id':task['id'],'expected_revision':task['revision'],'outcome':'accepted','evidence':'Сопоставлено с целью'})

    def test_search_pins_constraints_and_transitive_bases(self):
        self.record('base');self.record('child',basis=[{'type':'record','id':'base','revision':1}]);self.record('mandatory',kind='constraint')
        context=retrieve(self.root,self.memory,'Другая задача',ids=['child'])
        self.assertIn('mandatory',context['mandatory_ids'])
        self.assertEqual({r['id'] for r in context['references'].values() if r['type']=='record'},{'base','child','mandatory'})

    def test_search_whole_section_preserves_condition_and_parent(self):
        context=retrieve(self.root,self.memory,'локально',limit=3)
        quotes=[r['quote'] for r in context['references'].values() if r['type']=='source']
        self.assertTrue(any('Условие: только после принятия человеком.' in q for q in quotes))
        self.assertTrue(any('Вводная связь.' in q for q in quotes))

    def test_budget_does_not_truncate_required_record(self):
        r=self.record('long');self.memory.save({**r,'statement':'Длинное основание. '*200,'expected_revision':1})
        with self.assertRaises(ValueError):retrieve(self.root,self.memory,'Хранение',ids=['long'],budget=500)

    def test_stale_pinned_memory_blocks_assembly(self):
        r=self.record('base');self.record('child',basis=[{'type':'record','id':'base','revision':1}])
        self.memory.save({**r,'statement':'Изменённое основание','expected_revision':1})
        with self.assertRaises(ValueError):retrieve(self.root,self.memory,'Хранение',ids=['child'])

    def test_new_constraint_invalidates_saved_context(self):
        context=retrieve(self.root,self.memory,'Хранение')
        self.record('new-policy',kind='constraint')
        self.assertTrue(changed_context(self.root,self.memory,context))

    def test_script_mode_connected_to_request_result_and_review(self):
        self.editor.call.return_value={'text':json.dumps({'claims':[{'type':'source','ref_id':'s_task','quote':'Исходные сведения.'}],
                    'transitions':[],'calculations':[], 'coverage':[{'criterion_id':'k1','state':'addressed','claim_ids':['c1'],'note':None}]},ensure_ascii=False),
                    'input_tokens':3,'output_tokens':4}
        task=self.run_task({**self.payload,'script_mode':True,'use_memory':True})
        self.assertEqual(task['status'],'awaiting_review')
        self.assertEqual(task['checks']['structured_status'],'pass')
        self.assertTrue(self.editor.call.call_args.args[0]['json_mode'])
        self.assertEqual(task['events'][-1]['kind'],'answer_checks')
        self.accepted(task)
        (self.root/'memory/STATE.md').write_text('# Новая исходная точка\n',encoding='utf-8')
        self.assertTrue(self.store.tasks()[0]['requires_recheck'])
        with self.assertRaises(SourceConflict):self.accepted(self.store.get(task['id']))
        self.assertEqual(self.store.prepare(self.payload)['experience_ids'],[])

    def test_plain_wrong_arithmetic_is_also_blocked(self):
        self.editor.call.return_value={'text':'120 / 3 = 50.'}
        task=self.run_task()
        self.assertTrue(task['checks']['blocking'])
        with self.assertRaises(ValueError):self.accepted(task)

    def test_invalid_structured_answer_is_kept_and_not_accepted(self):
        task=self.run_task({**self.payload,'script_mode':True,'use_memory':False})
        self.assertEqual(task['raw_answer'],'Результат.')
        self.assertEqual(task['checks']['structured_status'],'failed')
        with self.assertRaises(ValueError):self.accepted(task)

    def test_selected_logic_is_in_request_and_controls_admission(self):
        from protocol_atlas.logic import select
        from scripts.run_logic_demo import candidate
        contract=json.loads((Path(__file__).resolve().parents[1]/'examples/logic/syllogism.json').read_text(encoding='utf-8'))
        response=candidate(select(contract))
        self.editor.call.return_value={'text':json.dumps(response)}
        task=self.run_task({**self.payload,'logic_contract':contract})
        self.assertTrue(task['checks']['logic']['admitted'])
        self.assertEqual(task['answer'],'Все S являются P.')
        request=json.loads(self.editor.call.call_args.args[1][1]['content'])
        self.assertEqual(request['logic_selection']['contract'],contract)
        self.assertIn('barbara',request['logic_profile']['rules'])
        self.assertTrue(self.editor.call.call_args.args[0]['json_mode'])
        self.accepted(task)

    def test_selected_logic_cannot_fall_back_to_prose_or_allow_symbol_drift(self):
        from protocol_atlas.logic import select
        from scripts.run_logic_demo import candidate
        contract=json.loads((Path(__file__).resolve().parents[1]/'examples/logic/syllogism.json').read_text(encoding='utf-8'))
        response=candidate(select(contract));response['steps'][0]['formula'][1]='G'
        for raw in (json.dumps(response), 'Все G являются P.'):
            self.editor.call.return_value={'text':raw}
            task=self.run_task({**self.payload,'logic_contract':contract})
            self.assertEqual(task['raw_answer'],raw)
            self.assertFalse(task['checks']['logic']['admitted'])
            self.assertTrue(task['checks']['blocking'])
            with self.assertRaises(ValueError):self.accepted(task)

    def test_logic_schema_is_explicit_and_checker_changes_require_recheck(self):
        from protocol_atlas.logic import select
        from scripts.run_logic_demo import candidate
        contract=json.loads((Path(__file__).resolve().parents[1]/'examples/logic/syllogism.json').read_text(encoding='utf-8'))
        with self.assertRaises(ValueError):self.store.prepare({**self.payload,'logic_contract':contract,'script_mode':True})
        self.editor.call.return_value={'text':json.dumps(candidate(select(contract)))}
        task=self.run_task({**self.payload,'logic_contract':contract})
        with patch('protocol_atlas.adaptive.checker_version',return_value='changed'):
            self.assertTrue(self.store.context_changes(task))

    def test_known_reader_terms_do_not_equal_dictionary_membership(self):
        self.assertEqual(len(analyze_text(self.root,'Рекурсия управляет работой.')['terms']),1)
        self.assertEqual(analyze_text(self.root,'Рекурсия управляет работой.',['Рекурсия'])['terms'],[])

    def test_plan_blocks_dependent_stage_until_acceptance_and_after_reversal(self):
        plan=self.store.save_plan({'goal':'Связанные результаты','approved':True,
             'stages':[{'id':'first','title':'Основание','requires':[]},{'id':'next','title':'Продолжение','requires':['first']}]})
        next_payload={**self.payload,'plan_id':plan['id'],'stage_id':'next'}
        with self.assertRaises(ValueError):self.store.prepare(next_payload)
        first=self.run_task({**self.payload,'plan_id':plan['id'],'stage_id':'first'})
        with self.assertRaises(ValueError):self.store.prepare(next_payload)
        first=self.accepted(first)
        prepared=self.store.prepare(next_payload)
        self.assertEqual(prepared['stage_inputs'],[{'id':first['id'],'revision':first['revision']}])
        following=self.run_task(next_payload);self.accepted(following)
        self.store.review({'id':first['id'],'expected_revision':first['revision'],'outcome':'revise','evidence':'Расхождение','error':'Основание неполно'})
        self.assertTrue(self.store.context_changes(self.store.get(following['id'])))
        self.assertEqual(self.store.plans()[0]['stages'][1]['status'],'needs_recheck')
        with self.assertRaises(ValueError):self.store.prepare(next_payload)

    def test_plan_cycles_and_unapproved_plan_are_rejected(self):
        with self.assertRaises(ValueError):validate_plan([{'id':'a','title':'A','requires':['a']}])
        with self.assertRaises(ValueError):self.store.save_plan({'goal':'Цель','stages':[{'id':'a','title':'A','requires':[]}]})

    def test_optional_analysis_keeps_cost_and_does_not_change_acceptance(self):
        task=self.accepted(self.run_task())
        self.editor.call.return_value={'text':json.dumps({'issues':[{'quote':'Результат.','problem':'Недостаточно показаны основания.',
                                                                  'basis_refs':[],'question':'Что подтверждает результат?'}]},ensure_ascii=False),
                                       'input_tokens':10,'output_tokens':20}
        critique=self.store.critique({'id':task['id'],'expected_revision':task['revision']})
        self.assertEqual(critique['status'],'completed')
        self.assertEqual(critique['usage']['input_tokens'],10)
        self.assertEqual(self.store.get(task['id'])['review']['outcome'],'accepted')

    def test_invalid_critic_quote_does_not_become_valid_issue(self):
        task=self.run_task()
        self.editor.call.return_value={'text':json.dumps({'issues':[{'quote':'Выдуманное','problem':'Ошибка','basis_refs':[],'question':'Проверка?'}]})}
        self.assertEqual(self.store.critique({'id':task['id'],'expected_revision':task['revision']})['status'],'invalid_response')

    def test_diagnostics_keep_unresolved_errors_and_input_results(self):
        task=self.run_task()
        self.store.review({'id':task['id'],'expected_revision':task['revision'],'outcome':'rejected','evidence':'Проверка','error':'Потеряно условие','next_method':'Сохранить условия.'})
        report=self.store.diagnostics()
        self.assertIn(task['id'],report['retention']['protected_task_ids'])
        self.assertEqual(report['retention']['mode'],'preview_only')
        self.assertEqual(report['groups'][0]['reviewed'],1)

    def test_query_is_data_and_rejected_memory_is_not_auto_selected(self):
        self.record('old',status='rejected')
        context=retrieve(self.root,self.memory,'Локальное хранение')
        self.assertNotIn('old',[r.get('id') for r in context['references'].values()])
        self.assertEqual(search_items([{'title':'Локально','text':'Исходные записи'}],"' OR 1=1 -- локально")[0]['title'],'Локально')

    def test_current_project_check_can_back_claim_but_old_check_cannot(self):
        from protocol_atlas.project_checks import code_snapshot
        check={'id':'check1','status':'pass','count':9,'snapshot':code_snapshot(self.root),
               'scope':'Только выполненные тесты.','output':'OK','at':'test'}
        with self.store.db() as db:db.execute('INSERT INTO program_checks VALUES (?,?)',('check1',json.dumps(check)))
        prepared=self.store.prepare({**self.payload,'script_mode':True,'use_memory':False,'use_project_check':True})
        self.assertEqual(prepared['evidence_events'][-1]['id'],'e_project')
        (self.root/'PROTOCOL.md').write_text('Изменённое основание.',encoding='utf-8')
        self.assertTrue(self.store.context_changes(prepared))
        with self.assertRaises(ValueError):self.store.prepare({**self.payload,'use_project_check':True})

    def test_false_equation_in_source_quote_is_not_asserted_as_true(self):
        payload={**self.payload,'materials':'Пример ошибки: 120/3 = 50.','script_mode':True,'use_memory':False}
        response={'claims':[{'type':'source','ref_id':'s_task','quote':payload['materials']}],
                  'transitions':[],'calculations':[],
                  'coverage':[{'criterion_id':'k1','state':'addressed','claim_ids':['c1'],'note':None}]}
        self.editor.call.return_value={'text':json.dumps(response)}
        task=self.run_task(payload)
        self.assertFalse(task['checks']['blocking'])

    def test_program_check_uses_fixed_command_and_keeps_failed_run(self):
        completed=Mock(stdout='',stderr='Ran 7 tests in 0.1s\n\nOK\n',returncode=0)
        with patch('protocol_atlas.project_checks.subprocess.run',return_value=completed) as runner:
            check=self.store.check_program()
        self.assertEqual(runner.call_args.args[0][1:],['-m','unittest','discover','-s','tests'])
        self.assertEqual(check['status'],'pass')
        self.assertEqual(check['count'],7)
        completed.returncode=1;completed.stderr='Ran 7 tests in 0.1s\n\nFAILED (failures=1)\n'
        with patch('protocol_atlas.project_checks.subprocess.run',return_value=completed):self.store.check_program()
        with self.assertRaises(ValueError):self.store.prepare({**self.payload,'use_project_check':True})

    def test_http_search_plan_diagnostics_and_checked_task(self):
        from http.client import HTTPConnection
        from http.server import ThreadingHTTPServer
        import threading
        from urllib.parse import quote
        from protocol_atlas.server import handler_for
        self.editor.adaptive=self.store
        handler=handler_for(self.root,ai_editor=self.editor);handler.log_message=lambda *a:None
        server=ThreadingHTTPServer(('127.0.0.1',0),handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def request(path,payload=None):
            connection=HTTPConnection('127.0.0.1',server.server_address[1],timeout=10)
            connection.request('POST' if payload is not None else 'GET',path,
                               body=json.dumps(payload).encode() if payload is not None else None,
                               headers={'Content-Type':'application/json'} if payload is not None else {})
            response=connection.getresponse();body=json.loads(response.read());connection.close()
            self.assertEqual(response.status,200,body)
            return body
        try:
            self.assertTrue(request('/api/memory/search?q='+quote('локально'))['references'])
            plan=request('/api/adaptive/plan',{'goal':'Последовательность','approved':True,
                         'stages':[{'id':'a','title':'Результат','requires':[]}]})
            self.assertEqual(request('/api/adaptive')['plans'][0]['id'],plan['id'])
            prepared=request('/api/adaptive/prepare',{**self.payload,'script_mode':True,'use_memory':True})
            self.assertIn('s_task',prepared['references'])
            self.assertEqual(request('/api/adaptive/diagnostics')['retention']['mode'],'preview_only')
        finally:
            server.shutdown();server.server_close();thread.join(timeout=3)


if __name__ == '__main__':
    unittest.main()
