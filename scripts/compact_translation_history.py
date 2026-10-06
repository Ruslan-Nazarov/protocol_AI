"""Compact old translation backups, verifying all bytes before removing originals."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from protocol_atlas.translation_history import TranslationHistory
from protocol_atlas.catalog import digest
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--apply',action='store_true',help='Remove verified old JSON copies after archiving')
parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
args=parser.parse_args()
root=args.root.resolve()
active={p:digest(p.read_bytes()) for p in (root/'locales').rglob('*.json')}
def verify_active():
    if any(not p.is_file() or digest(p.read_bytes())!=sha for p,sha in active.items()):
        raise RuntimeError('Active translations changed during migration; originals retained.')
report=TranslationHistory(root).migration(remove=args.apply,before_remove=verify_active)
verify_active()
print(json.dumps(report,ensure_ascii=False))
