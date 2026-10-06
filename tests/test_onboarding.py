import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import shutil
from unittest.mock import Mock, patch

from protocol_atlas.adaptive import AdaptiveTasks
from protocol_atlas.onboarding import Onboarding
from protocol_atlas.source_editor import SourceConflict


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ('PROTOCOL.md', 'check_answer.py'):
            shutil.copyfile(Path(__file__).resolve().parents[1]/name, self.root/name)
        self.editor = Mock(root=self.root)
        self.editor.data_path.side_effect = lambda name: self.root / 'data' / name
        self.editor.settings.return_value = dict(configured=True, model='test', api_key='secret')
        self.adaptive = AdaptiveTasks(self.root, self.editor)
        self.store = Onboarding(self.editor, self.adaptive)
        self.proposal = dict(message='Что уже есть?', purpose='Инфографика конференции',
                             requirements='', starting_point='', questions=['Что уже есть?'])
        self.editor.call.return_value = dict(text=json.dumps(self.proposal), input_tokens=12, output_tokens=8)
        runtime = patch('protocol_atlas.onboarding.compile_rules', return_value={'text': 'Protocol core'})
        runtime.start()
        self.addCleanup(runtime.stop)

    def test_freeform_followup_preserves_context_and_needs_human_acceptance(self):
        first = self.store.converse(dict(answer='Хочу инфографику', expected_revision=0))
        self.assertFalse(self.adaptive.profile()['configured'])
        self.proposal.update(starting_point='Кода нет, есть API', message='Описание готово', questions=[])
        self.editor.call.return_value = {'text': json.dumps(self.proposal)}
        second = self.store.converse(dict(answer='Кода нет, есть API', expected_revision=1))
        messages = self.editor.call.call_args.args[1]
        self.assertEqual([m['content'] for m in messages if m['role'] == 'user'], ['Хочу инфографику', 'Кода нет, есть API'])
        self.assertEqual(Onboarding(self.editor, self.adaptive).read()['revision'], 2)
        with self.assertRaises(SourceConflict):
            self.store.accept(dict(expected_revision=first['revision'], expected_profile_revision=0))
        profile = self.store.accept(dict(expected_revision=second['revision'], expected_profile_revision=0))
        self.assertEqual(profile['starting_point'], 'Кода нет, есть API')
        self.assertIn('не установлены', profile['requirements'])

    def test_invalid_api_response_or_missing_connection_does_not_change_saved_state(self):
        self.editor.settings.return_value['configured'] = False
        with self.assertRaises(ValueError):
            self.store.converse(dict(answer='Проект', expected_revision=0))
        self.editor.call.assert_not_called()
        self.editor.settings.return_value['configured'] = True
        self.editor.call.return_value = {'text': '{broken'}
        with self.assertRaises(ValueError):
            self.store.converse(dict(answer='Проект', expected_revision=0))
        self.assertEqual(self.store.read()['revision'], 0)

    def test_model_key_is_redacted_and_stale_revision_cannot_send_request(self):
        self.proposal['message'] = 'secret'
        self.editor.call.return_value = {'text': json.dumps(self.proposal)}
        response = self.store.converse(dict(answer='Проект', expected_revision=0))
        self.assertNotIn('secret', json.dumps(response))
        self.editor.call.reset_mock()
        with self.assertRaises(SourceConflict):
            self.store.converse(dict(answer='Поправка', expected_revision=0))
        self.editor.call.assert_not_called()
