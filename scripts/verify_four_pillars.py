"""Read-only coherence audit and complete local regression, without API calls."""
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    for command in ([sys.executable,'-X','utf8','scripts/verify_correctness_revision.py'],
                    [sys.executable,'-X','utf8','-m','unittest','discover','-s','tests','-q']):
        result=subprocess.run(command,cwd=ROOT)
        if result.returncode:return result.returncode
    return 0


if __name__=='__main__':raise SystemExit(main())
