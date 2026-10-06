import json
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from protocol_atlas.laboratory import CRITERIA, TASKS, Laboratory, episode, structural_checks
from protocol_atlas.providers import call_model, credentials, public_providers
from protocol_atlas.episodes import synthetic, manifest, read_sources

ROOT = Path(__file__).resolve().parents[1]


def answer():
    return json.dumps({'answers': [{'task_id': task['id'], 'answer': 'Основание сохранено.',
                                   'source_paths': ['memory/STATE.md']} for task in TASKS]}, ensure_ascii=False)


def fake_model(root, provider, model, messages, max_output):
    continuation = 'ЗАДАНИЯ:' in messages[-1]['content']
    return {'text': answer() if continuation else 'Краткая память.', 'actual_model': 'actual-model',
            'finish_reason': 'stop', 'usage_raw': {}, 'input_tokens': None, 'output_tokens': None}


class LaboratoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'project'
        self.root.mkdir()
        for name in ('PROTOCOL.md', 'check_answer.py', 'memory', 'atlas', 'docs'):
            source, destination = ROOT / name, self.root / name
            if source.is_dir():
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)
        self.lab = Laboratory(self.root, fake_model)

    def tearDown(self):
        self.temp.cleanup()

    def payload(self, **changes):
        return {'provider': 'groq', 'model': 'test-model', 'repeats': 1, 'summary_characters': 4000,
                'catalog_revision': episode(self.root)['catalog_revision'], **changes}

    def finish(self, run):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = self.lab.get(run['id'])
            if result['status'] not in ('prepared', 'running'):
                return result
            time.sleep(.01)
        self.fail('Mock run did not finish')

    def test_three_contexts_five_calls_and_no_criteria_in_prompts(self):
        result = self.finish(self.lab.start(self.payload()))
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['calls'], 5)
        self.assertEqual([r['condition'] for r in result['results']], ['full', 'summary', 'structured'])
        messages = json.dumps([event['messages'] for event in result['events']], ensure_ascii=False)
        for criterion in CRITERIA:
            self.assertNotIn(criterion['text'], messages)
        for event in result['events']:
            self.assertIsNone(event['input_tokens'])
        self.assertIsNone(result['cost'])
        self.assertEqual(result['results'][0]['checks']['meaning'], 'unknown')
        restored = Laboratory(self.root).get(result['id'])
        self.assertEqual(restored, result)

    def test_attention_positions_change_only_order_and_keep_memory_equal(self):
        cases=[synthetic('attention-'+position) for position in ('start','middle','end')]
        for case,index in zip(cases,(0,2,4)):
            self.assertEqual(case['sources'][index]['path'],'synthetic/decision.md')
            self.assertEqual({s['sha256'] for s in case['sources']},{s['sha256'] for s in cases[0]['sources']})
            self.assertEqual(case['record_context'],cases[0]['record_context'])
            self.assertEqual(case['tasks'],cases[0]['tasks'])
        self.assertEqual(len({case['catalog_revision'] for case in cases}),3)

    def test_exact_context_resolves_snapshots_without_compression_or_hidden_rubric(self):
        def exact_model(root,provider,model,messages,max_output):
            text=json.dumps({'answers':[{'task_id':task['id'],'claims':[{'type':'inference',
                'text':'Учебный вывод','basis_refs':['u1','r1'],'scope':'R','uncertainties':'Проверить смысл'}],
                'uncertainties':'Не проверено'} for task in synthetic('revision')['tasks']]},ensure_ascii=False)
            return {'text':text,'actual_model':'test','finish_reason':'stop','input_tokens':10,'output_tokens':20}
        self.lab=Laboratory(self.root,exact_model)
        material=synthetic('long-revision')
        result=self.finish(self.lab.start(self.payload(episode_id=material['id'],catalog_revision=material['catalog_revision'],conditions=['exact'],summary_characters=6000)))
        self.assertEqual(result['calls'],1)
        self.assertEqual(result['results'][0]['checks']['references'],'pass')
        self.assertEqual(result['results'][0]['resolved_response']['answers'][0]['claims'][0]['status'],'unverified')
        prompts=json.dumps(result['events'][0]['messages'],ensure_ascii=False)
        for criterion in result['criteria']:self.assertNotIn(criterion['text'],prompts)
        self.assertNotIn('long-archive',prompts)

    def test_exact_unknown_reference_fails_without_retry_or_rewriting_response(self):
        def bad_model(*args):
            return {'text':json.dumps({'answers':[{'task_id':task['id'],'claims':[{'type':'record','ref_id':'r999'}],
                'uncertainties':''} for task in synthetic('contradiction')['tasks']]}),
                'actual_model':'test','finish_reason':'stop','input_tokens':10,'output_tokens':20}
        self.lab=Laboratory(self.root,bad_model)
        material=synthetic('contradiction')
        result=self.finish(self.lab.start(self.payload(episode_id=material['id'],catalog_revision=material['catalog_revision'],conditions=['exact'])))
        self.assertEqual(result['calls'],1)
        self.assertEqual(result['results'][0]['status'],'validation_failed')
        self.assertIn('r999',result['results'][0]['response'])
        self.assertIsNone(result['results'][0]['resolved_response'])

    def test_overflow_preserved_and_not_given_to_continuation(self):
        def overflow(*args):
            result = fake_model(*args)
            if 'ЗАДАНИЯ:' not in args[3][-1]['content']:
                result['text'] = 'X' * 1600
            return result
        self.lab.model_call = overflow
        result = self.finish(self.lab.start(self.payload(summary_characters=1500)))
        self.assertEqual(result['calls'], 3)
        self.assertEqual(len(result['results'][1]['context']), 1600)
        self.assertEqual(result['results'][1]['status'], 'preparation_failed')
        self.assertEqual(result['results'][2]['checks']['budget'], 'fail')

    def test_same_snapshot_can_be_repeated_after_sources_change(self):
        original = self.finish(self.lab.start(self.payload()))
        state = self.root / 'memory/STATE.md'
        state.write_text(state.read_text(encoding='utf-8') + '\nНовое состояние\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'изменился'):
            self.lab.start(self.payload(catalog_revision=original['episode']['catalog_revision']))
        repeated = self.finish(self.lab.start(self.payload(snapshot_run_id=original['id'],
                              catalog_revision=original['episode']['catalog_revision'])))
        self.assertEqual(repeated['episode'], original['episode'])
        self.assertNotIn('Новое состояние', repeated['episode']['material'])

    def test_review_requires_quote_and_survives_reload(self):
        result = self.finish(self.lab.start(self.payload()))
        payload = {'result_key': '1:summary', 'criterion': 'continue', 'verdict': 'pass', 'quote': 'invented'}
        with self.assertRaisesRegex(ValueError, 'цитата'):
            self.lab.review(result['id'], payload)
        self.lab.review(result['id'], {**payload, 'quote': 'Основание сохранено.'})
        restored = Laboratory(self.root).get(result['id'])
        self.assertEqual(restored['review']['1:summary']['continue']['quote'], 'Основание сохранено.')

    def test_cancel_preserves_inflight_call_without_starting_another(self):
        entered, release = threading.Event(), threading.Event()
        def waiting(*args):
            entered.set()
            release.wait(3)
            return fake_model(*args)
        self.lab.model_call = waiting
        run = self.lab.start(self.payload())
        self.assertTrue(entered.wait(3))
        with self.assertRaisesRegex(ValueError, 'уже выполняется'):
            self.lab.start(self.payload())
        with self.assertRaisesRegex(ValueError, 'после завершения'):
            self.lab.review(run['id'], {})
        self.lab.cancel(run['id'])
        release.set()
        result = self.finish(run)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['calls'], 1)
        self.assertEqual(result['events'][0]['status'], 'completed')

    def test_failed_and_truncated_calls_remain_in_history(self):
        for truncated in (False, True):
            def failure(*args):
                if not truncated:
                    raise RuntimeError('Service unavailable')
                return {**fake_model(*args), 'finish_reason': 'length'}
            self.lab.model_call = failure
            result = self.finish(self.lab.start(self.payload()))
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['calls'], 1)
            self.assertEqual(result['results'], [])
            self.assertEqual(len(result['events']), 1)

    def test_cancel_during_pacing_does_not_start_next_call(self):
        run = self.lab.start(self.payload(min_interval_seconds=60))
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current = self.lab.get(run['id'])
            if current.get('waiting_until'):
                break
            time.sleep(.01)
        self.assertIn('waiting_until', current)
        self.lab.cancel(run['id'])
        result = self.finish(run)
        self.assertEqual(result['calls'], 1)
        self.assertEqual(result['status'], 'cancelled')
        self.assertNotIn('waiting_until', result)

    def test_structural_checks_do_not_infer_semantics(self):
        sources = episode(self.root)['sources']
        self.assertEqual(structural_checks(answer(), sources)['meaning'], 'unknown')
        for text in ('invalid', '{"answers":null}', '{"answers":[null]}', '{"answers":{}}',
                     '{"answers":[{"task_id":[],"source_paths":[{}]}]}'):
            self.assertEqual(structural_checks(text, sources)['json'], 'fail')
        value = json.loads(answer())
        value['answers'][0]['source_paths'] = ['.env']
        self.assertEqual(structural_checks(json.dumps(value), sources)['source_paths'], 'fail')

    def test_limits_invalid_inputs_and_paths(self):
        for changes in ({'provider': []}, {'model': '../x?y'}, {'repeats': True},
                        {'summary_characters': 10}, {'snapshot_run_id': 42}):
            with self.assertRaises(ValueError):
                self.lab.start(self.payload(**changes))
        with self.assertRaises(ValueError):
            self.lab.get('../other')

    def test_independent_scenarios_and_retrieval_calls_are_counted(self):
        material = synthetic('revision')
        def model(root, provider, model, messages, max_output):
            if 'read_sources' in messages[0]['content']:
                text = json.dumps({'read_sources': [{'source_id': item['source_id']} for item in manifest(material)]})
            elif 'ЗАДАНИЯ:' in messages[-1]['content']:
                text = json.dumps({'answers': [{'task_id': t['id'], 'answer': 'Ответ по данным.', 'source_paths': ['synthetic/conclusions.md']} for t in material['tasks']]})
            else:
                text = 'Краткая история A@1, B@1, C@1.'
            return {**fake_model(root, provider, model, messages, max_output), 'text': text}
        self.lab.model_call = model
        result = self.finish(self.lab.start(self.payload(episode_id='revision', catalog_revision=material['catalog_revision'],
                             conditions=['full','summary','structured','records','retrieval'])))
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['calls'], 8)
        self.assertEqual(len(result['read_events']), 1)
        self.assertEqual(result['results'][-1]['checks']['json'], 'pass')
        messages = json.dumps([e['messages'] for e in result['events']], ensure_ascii=False)
        for criterion in material['criteria']:
            self.assertNotIn(criterion['text'], messages)
        groups = self.lab.comparison()['groups']
        self.assertEqual(len(groups), 5)
        self.assertEqual(next(g for g in groups if g['condition']=='retrieval')['calls'], 3)
        self.assertTrue(all(g['meaning']['unknown'] == 3 for g in groups))

    def test_retrieval_cannot_read_secret_or_truncate_outside_budget(self):
        material = synthetic('revision')
        for request in ([{'source_id': '.env'}], [{'source_id':'s0','start_line':0}], [{'source_id':'s0','end_line':999}]):
            with self.assertRaises(ValueError):
                read_sources(material, request, 12000)
        with self.assertRaisesRegex(ValueError, 'бюджет'):
            read_sources(material, [{'source_id': 's0'}], 10)

    def test_new_evidence_does_not_reduce_historical_memory_budget(self):
        material = synthetic('revision')
        def model(*args):
            output = fake_model(*args)
            if 'ЗАДАНИЯ:' not in args[3][-1]['content']:
                output['text'] = 'X' * 1499
            return output
        self.lab.model_call = model
        result = self.finish(self.lab.start(self.payload(episode_id='revision', catalog_revision=material['catalog_revision'],
                             summary_characters=1500, conditions=['summary'])))
        self.assertEqual(result['results'][0]['status'], 'completed')
        self.assertEqual(result['results'][0]['retained_memory_characters'], 1499)
        self.assertGreater(result['results'][0]['characters'], 1500)

    def test_bad_read_request_saved_without_calling_final_answer(self):
        material = synthetic('contradiction')
        def model(*args):
            return {**fake_model(*args), 'text': '{"read_sources":[{"source_id":".env"}]}'}
        self.lab.model_call = model
        result = self.finish(self.lab.start(self.payload(episode_id='contradiction', catalog_revision=material['catalog_revision'], conditions=['retrieval'])))
        self.assertEqual(result['calls'], 2)
        self.assertEqual(result['read_events'][0]['status'], 'failed')
        self.assertEqual(result['results'][0]['status'], 'retrieval_failed')

    def test_oversized_structure_is_not_given_to_read_planner(self):
        material = synthetic('revision')
        def model(*args):
            return {**fake_model(*args), 'text': 'X' * 1600}
        self.lab.model_call = model
        result = self.finish(self.lab.start(self.payload(episode_id='revision', catalog_revision=material['catalog_revision'],
                             summary_characters=1500, conditions=['retrieval'])))
        self.assertEqual(result['calls'], 1)
        self.assertEqual(result['results'][0]['status'], 'preparation_failed')
        self.assertEqual(result['read_events'], [])


class ProviderTests(unittest.TestCase):
    def test_neighbor_credentials_filtered_and_project_takes_precedence(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict('os.environ', {}, clear=True):
            root = Path(temp) / 'project'
            root.mkdir()
            neighbor = root.parent / 'dialecticalai'
            neighbor.mkdir()
            (neighbor / '.env').write_text('GROQ_API_KEY=neighbor-secret\nGROQ_MODEL=oss\nUNRELATED_SECRET=hidden', encoding='utf-8')
            (root / '.env').write_text('GROQ_API_KEY="local-secret"', encoding='utf-8')
            values = credentials(root)
            self.assertEqual(values['GROQ_API_KEY'], 'local-secret')
            self.assertNotIn('UNRELATED_SECRET', values)
            public = json.dumps(public_providers(root))
            self.assertNotIn('secret', public)
            self.assertTrue(public_providers(root)[0]['configured'])

    def test_missing_usage_is_unknown_and_output_limit_is_sent(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return json.dumps({'model': 'actual', 'choices': [{'message': {'content': 'OK'}, 'finish_reason': 'stop'}]}).encode()
        with patch('protocol_atlas.providers.credentials', return_value={'GROQ_API_KEY': 'secret'}), patch('urllib.request.urlopen', return_value=Response()) as send:
            output = call_model(ROOT, 'groq', 'oss', [{'role': 'user', 'content': 'test'}], 120)
            self.assertIsNone(output['input_tokens'])
            self.assertIsNone(output['output_tokens'])
            payload = json.loads(send.call_args[0][0].data)
            self.assertEqual(send.call_args[0][0].get_header('User-agent'), 'protocol-atlas/0.1')
            self.assertEqual(payload['max_completion_tokens'], 120)
            self.assertEqual(output['actual_model'], 'actual')

    def test_json_mode_and_reasoning_format_are_explicit_and_recorded(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return json.dumps({'model': 'gpt-oss-120b', 'choices': [{'message': {'content': '{}'}, 'finish_reason':'stop'}]}).encode()
        with patch('protocol_atlas.providers.credentials', return_value={'CEREBRAS_API_KEY': 'secret'}), patch('urllib.request.urlopen', return_value=Response()) as send:
            result = call_model(ROOT, 'cerebras', 'gpt-oss-120b', [{'role':'user','content':'JSON'}], 100, json_mode=True)
            payload = json.loads(send.call_args[0][0].data)
            self.assertEqual(payload['response_format'], {'type':'json_object'})
            self.assertEqual(payload['reasoning_format'], 'parsed')
            self.assertNotIn('secret', json.dumps(result))

    def test_provider_echo_cannot_put_credentials_into_history(self):
        secret = 'test-provider-secret-key'
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return json.dumps({'model':'m','choices':[{'message':{'content':secret,'reasoning':secret},'finish_reason':'stop'}]}).encode()
        with patch('protocol_atlas.providers.credentials', return_value={'GROQ_API_KEY':secret}), patch('urllib.request.urlopen',return_value=Response()):
            result = call_model(ROOT,'groq','m',[{'role':'user','content':'test'}],100)
            self.assertNotIn(secret,json.dumps(result))
            self.assertTrue(result['credentials_redacted'])


if __name__ == '__main__':
    unittest.main()
