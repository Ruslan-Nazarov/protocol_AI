from pathlib import Path
import unittest

from protocol_atlas.translations import TranslationStore


class EnglishProtocolTests(unittest.TestCase):
    def test_public_protocol_matches_complete_current_translation(self):
        root = Path(__file__).resolve().parents[1]
        doc = TranslationStore(root).read('PROTOCOL.md')
        self.assertEqual(doc['pending'], 0)
        expected = ''.join(unit['translation'] for unit in doc['units']).rstrip() + '\n'
        self.assertEqual((root / 'PROTOCOL.en.md').read_text(encoding='utf-8'), expected)
