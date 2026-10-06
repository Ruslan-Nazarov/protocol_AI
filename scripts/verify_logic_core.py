"""Executable checks for explicit logic and its application integration."""
from pathlib import Path
import sys
import unittest
import argparse
import io
import json
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--quick', action='store_true', help='Small deterministic smoke test; no model/API calls')
args = parser.parse_args()
names = (
    'test_logic.LogicTests.test_valid_proof_has_conditional_scope_and_generated_text',
    'test_logic.LogicTests.test_all_injected_faults_are_caught_with_original_preserved',
    'test_logic.LogicTests.test_quoted_G_is_not_a_global_ban',
    'test_logic.LogicTests.test_propositional_choice_executes_different_language_and_rule',
    'test_logic.RuntimeLogicTests.test_agent_review_cannot_replace_logic_check',
    'test_logic.RuntimeLogicTests.test_latest_failure_blocks_and_keeps_original',
    'test_logic.RuntimeLogicTests.test_imported_success_requires_local_check',
    'test_script_runtime.RuntimeIntegrationTests.test_selected_logic_cannot_fall_back_to_prose_or_allow_symbol_drift',
) if args.quick else ('test_logic', 'test_script_runtime')
suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in names)
output = io.StringIO()
started = time.monotonic()
result = unittest.TextTestRunner(stream=output, verbosity=1).run(suite)
print(json.dumps({'status':'pass' if result.wasSuccessful() else 'fail', 'tests':result.testsRun,
                  'seconds':round(time.monotonic()-started, 3), 'model_calls':0, 'api_tokens':0,
                  'scope':'deterministic checks; not a live-model reliability estimate'}))
if not result.wasSuccessful():print(output.getvalue(), file=sys.stderr)
raise SystemExit(not result.wasSuccessful())
