# Contributing

Use Python 3.10 or newer. The Python application and offline tests use the standard library; no pip installation is required.

Run from the repository root:

```sh
python -X utf8 -m unittest discover -s tests
python -X utf8 scripts/verify_logic_core.py --quick
python -X utf8 scripts/verify_execution_protocol.py
```

On Windows, use `py -3` if `python` is unavailable. These commands do not require API credentials or paid model calls. Browser automation in `tests/portal_smoke.cjs` is a separate optional check.

Describe the problem, your change, and the actual checks performed in each pull request. Preserve the distinction between a protocol requirement, its implementation, and evidence that it works. A formal inference check establishes derivability within its supported profile; it does not establish the truth of premises or correct interpretation of arbitrary prose.

Do not commit API keys, `.env`, local databases, generated runs, or machine-specific agent configuration. Use `.env.example` for optional configuration names.

The protocol and most project documentation are currently in Russian. English UI resources are in `locales/en/`.
