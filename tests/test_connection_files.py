from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from protocol_atlas.catalog import REQUIRED_SOURCES
from protocol_atlas.connection_files import connection_download, instruction_download
from protocol_atlas.source_editor import SourceConflict


class ConnectionFilesTests(unittest.TestCase):
    def test_first_message_attachment_preserves_materials_and_line_breaks(self):
        message = 'Прочитай протокол.\nAPI: https://example.com/programs/?page=1&page_size=10000\nИсследуй данные.'
        data, filename, media_type = instruction_download(message, 'FIRST_MESSAGE.md')
        self.assertEqual(data.decode('utf-8'), message+'\n')
        self.assertEqual(filename, 'FIRST_MESSAGE.md')
        self.assertEqual(media_type, 'text/markdown')

    def test_first_message_overflow_rejected_without_truncation(self):
        with self.assertRaises(ValueError):
            instruction_download('x'*8001, 'FIRST_MESSAGE.md')

    def test_missing_english_translation_blocks_download_without_modifying_source(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name in REQUIRED_SOURCES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'# Current source\n')
            source = (root / 'PROTOCOL.md').read_bytes()
            with self.assertRaises(SourceConflict):
                connection_download(root, 'en', 'PROTOCOL.md')
            self.assertEqual((root / 'PROTOCOL.md').read_bytes(), source)
