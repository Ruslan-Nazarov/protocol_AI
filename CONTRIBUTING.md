# Contributing

Use Python 3.10 or newer. The Python application and offline tests use the standard library; no pip installation is required.

Run from the repository root:

```sh
python -X utf8 -m unittest discover -s tests
python -X utf8 scripts/verify_logic_core.py --quick
python -c "from pathlib import Path; from protocol_atlas.runtime_install import install; install(Path('.'), 'api', Path('.'))"
python -X utf8 scripts/verify_execution_protocol.py
```

On Windows, use `py -3` if `python` is unavailable. These commands do not require API credentials or paid model calls. Browser automation in `tests/portal_smoke.cjs` is a separate optional check.

The execution-protocol audit compares repository files with an installed runtime. The setup command creates the ignored `.protocol/` directory locally. Git preserves exact file bytes through `.gitattributes` because source evidence includes checksums.

Describe the problem, your change, and the actual checks performed in each pull request. Preserve the distinction between a protocol requirement, its implementation, and evidence that it works. A formal inference check establishes derivability within its supported profile; it does not establish the truth of premises or correct interpretation of arbitrary prose.

Do not commit API keys, `.env`, local databases, generated runs, or machine-specific agent configuration. Use `.env.example` for optional configuration names.

English is the primary README and default interface language. The complete reader-facing protocol is in `PROTOCOL.en.md`; its Russian source and linked English catalog are retained for runtime checks. When the protocol changes, update its linked translations and run `python scripts/export_english_protocol.py` to refresh the English Markdown. Do not approve stale translations merely to make an export pass. Additional research notes may remain in Russian.
