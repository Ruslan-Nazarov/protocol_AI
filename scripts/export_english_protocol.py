"""Export the complete, current source-linked English protocol for GitHub."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from protocol_atlas.translations import TranslationStore


def export(root=ROOT):
    document = TranslationStore(root).read('PROTOCOL.md')
    if document['pending']:
        raise ValueError('Update stale or missing English protocol units before export.')
    target = Path(root) / 'PROTOCOL.en.md'
    target.write_text(''.join(unit['translation'] for unit in document['units']).rstrip() + '\n', encoding='utf-8')
    return target


if __name__ == '__main__':
    print(export())
