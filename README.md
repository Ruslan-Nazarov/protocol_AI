# AI Work Protocol

**English** · [Русский](README.ru.md)

A protocol and local toolkit for human–AI collaboration, with explicit reasoning, versioned memory, evidence checks, and task orchestration.

**AI makes mistakes. We seek out correct answers.** The protocol requires explicit logical justification and checks against practice. It connects each rule to its implementation, observable evidence, and the next permitted task transition.

The current edition is **v0.5**: ten execution stages and 32 rules. Each rule specifies an action, a check, and pass, fail, or unavailable outcomes. This is an experimental project: documented requirements and implemented guarantees are kept distinct.

## Start here

- [Read the complete protocol in English](PROTOCOL.en.md).
- [Getting started: application and AI-client setup](docs/GETTING_STARTED.md).
- [Contributing and offline checks](CONTRIBUTING.md).
- [Russian protocol source](PROTOCOL.md) and [Russian README](README.ru.md).

## Run locally

Python **3.10 or newer** is required. The Python application uses the standard library; no pip installation is needed.

```sh
git clone https://github.com/Ruslan-Nazarov/protocol_AI.git
cd protocol_AI
python -m protocol_atlas.server
```

Open <http://127.0.0.1:8765>. The interface starts in English; use the language selector for Russian. An explicitly saved language preference is preserved. Stop the server with Ctrl+C. Use `--port 8766` to change the port.

On Windows, use `py -3` instead of `python` if needed. On Linux or macOS, your executable may be named `python3`.

API credentials are optional. Reading the protocol, connecting an external AI client, and offline checks do not require model calls. Additional AI features use server-side credentials; [.env.example](.env.example) lists the supported settings. Never commit actual keys.

## What the toolkit does

The local application provides four main areas: Protocol, Connection, Results and memory, and Improvement. It supports reading and editing rules, inspecting implementation boundaries, connecting an AI client, and reviewing results and project memory.

The installed project runtime records tasks, stages, artifact hashes, verification evidence, and human feedback. Checks are bound to the files they examined. Changed inputs require dependent results to be checked again. A technically verified result and human acceptance are separate states.

AI agents work in their own project chat. The agent supplies the plan and criteria; human corrections and acceptance come from actual human messages. Local CLI, MCP, and HTTP interfaces share the same project state. Generated state views should not be edited by hand.

The four pillars are logic, a world picture, development, and checking against reality. Development concerns the subject itself, not merely successive drafts. The toolkit includes a bounded example that combines a prediction about a file change, formal inference, and an actual read after the change.

## Verification and limits

Two supported formal profiles check derivability: universal syllogistic reasoning and classical propositional logic. A versioned contract records the selected profile, premises, rules, symbols, scope, and reasons for selection.

Derivability does not establish the truth of sources, faithful interpretation of natural language, or correct execution by an arbitrary external agent. Structural checks, formal checks, empirical observations, and human judgment have different scopes. The project does not automatically control all actions of an external AI client.

The optional laboratory compares bounded memory and continuation scenarios. Its measurements apply to their recorded conditions; preparing memory and invoking models have costs. Offline tests do not invoke paid models.

## Offline checks

```sh
python -X utf8 -m unittest discover -s tests
python -X utf8 scripts/verify_logic_core.py --quick
```

GitHub Actions runs these checks on Windows and Linux with Python 3.10 and 3.12. Browser checks are separate; see [CONTRIBUTING.md](CONTRIBUTING.md).

The execution-protocol audit also checks a locally installed runtime. Its setup and command are documented in [CONTRIBUTING.md](CONTRIBUTING.md).

## Repository layout

| Path | Purpose |
| --- | --- |
| `PROTOCOL.en.md` | Complete English protocol for readers |
| `PROTOCOL.md` | Russian source used by the runtime and linked translation checks |
| `protocol_atlas/` | Catalog, local server, interface, runtime, and laboratory |
| `atlas/` | Rule mappings and implementation annotations |
| `locales/en/` | English interface and source-linked document translations |
| `memory/` | Project history, decisions, errors, and reader profile |
| `docs/` | Guides, implementation boundaries, and experiment reports |
| `scripts/`, `tests/` | Offline verification and examples |

English is the primary entry point and the default interface language. Russian source documents and research notes remain available. Linked translations are checked against their source fingerprints; untranslated or changed units are shown explicitly rather than silently treated as current.

Local `.protocol/`, `data/`, `runs/`, `build/`, `.env`, and machine-specific `.codex/` files are excluded from Git. Back up project databases and runs separately with the server stopped; a Git commit does not preserve them.

## License

[MIT](LICENSE) · Copyright (c) 2026 Ruslan Nazarov.
