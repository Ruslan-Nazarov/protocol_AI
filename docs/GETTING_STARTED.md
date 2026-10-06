# Getting started

[Project overview](../README.md) · [Complete English protocol](../PROTOCOL.en.md) · [Russian runtime reference](PROJECT_RUNTIME.md)

## Open the local application

Install Python 3.10 or newer, clone this repository, and run these commands from its root:

```sh
python -m protocol_atlas.server
```

Open <http://127.0.0.1:8765>. No external Python packages or API keys are needed for reading the protocol and preparing an external-client connection. English is the default interface language. The language selector also offers Russian and preserves your explicit selection.

## Connect an AI client to your project

Open **Connection** in the application, describe the goal, select your client, and copy the generated starting message into the AI chat of your working project. The agent works in that chat and prepares the plan, stages, and checks.

Alternatively, download the project runtime connection package, extract `protocol-runtime.zip` into your working project, and run:

```sh
python install_protocol.py install --client codex --project .
```

Other client values are `claude`, `gemini`, `generic`, `api`, and `files`. Existing client instructions are preserved; installation adds a protocol block. Client permissions still govern access and execution. Installed hooks may require the client's trust in the local code. Reinstall after moving a project to update machine-specific paths.

The package does not include this author's project database, API keys, or another project's private state. Your runtime stores its own state in `.protocol/` within your project.

## Continue in the same chat

Give goals and corrections in ordinary messages. The agent records plans and actual evidence. A new substantive goal needs a task; a brief status question does not need another plan.

Checks bind evidence to artifact hashes. Changes can invalidate prior checks and dependent results. `verified` means current criteria passed; `accepted` records an actual human acceptance message. Neither silence nor the agent's own assessment is human acceptance.

Inspect the state from your working project's root:

```sh
python .protocol/engine/runner.py context --project .
```

Do not edit generated state views by hand. Back up local databases and runs separately from Git. Use the [offline checks](../CONTRIBUTING.md) when changing this toolkit.

## Language and verification boundaries

The repository's primary reading path is English. The runtime keeps the Russian protocol source and source-linked English units so changes remain traceable. English downloads require current translations; missing evidence or a stale translation must remain visible. Some supporting research notes are still in Russian.

Formal checks prove derivability only within their selected supported profiles. They do not prove premise truth, natural-language interpretation, or unrestricted actions of an external AI agent.
