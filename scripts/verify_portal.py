"""Offline checks for portal navigation, client handoff and retained endpoints."""
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
node=shutil.which('node')
if not node:
    raise SystemExit('Node.js is required for the interface checks.')
for name in ('app.js','portal.js','project.js','onboarding.js','i18n.js'):
    subprocess.run([node,'--check',str(ROOT/'protocol_atlas/web'/name)],cwd=ROOT,check=True)
subprocess.run([node,'tests/portal_smoke.cjs'],cwd=ROOT,check=True)
subprocess.run([sys.executable,'-X','utf8','-m','unittest','tests.test_catalog','tests.test_server','tests.test_project_runtime'],cwd=ROOT,check=True)
subprocess.run([sys.executable,'-X','utf8','scripts/verify_execution_protocol.py'],cwd=ROOT,check=True)
print('Portal checks passed; no model/API calls.')
