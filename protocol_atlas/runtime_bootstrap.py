"""Entrypoint callable by absolute path from any working project."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from protocol_atlas.runtime_cli import main

if __name__=='__main__':main()
