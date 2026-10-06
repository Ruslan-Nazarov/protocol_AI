"""Read-only verification of runtime instruction bases; never auto-approves edits."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from protocol_atlas.runtime_rules import verify_registry

if __name__ == '__main__':
    try:
        runtime = verify_registry(ROOT)
        print(f"Verified {len(runtime['rules'])} instructions: {runtime['characters']} characters; source {runtime['full_characters']}.")
    except (ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
