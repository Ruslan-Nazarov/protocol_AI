---
name: protocol-work
description: Organize substantive work in a project with an installed .protocol runtime. Record agent-authored stages, artifact checks, real human feedback and continuation without sending the user to the atlas. Use when .protocol/engine/runner.py is present. Ordinary status questions and brief acknowledgments do not need a new task.
---

The user's working chat is the working interface. Use the installed engine in this workspace; never import the atlas project's memory. Read the current state with `python .protocol/engine/runner.py context --project .` (Windows can use `py -3`). CLI, MCP and HTTP operate on the same state. If MCP tools are connected, prefer them.

Keep API credentials in the project's intended secret storage, not task goals, feedback, command arguments or evidence. Checks should read credentials from that storage or environment variables; do not print them.

For substantive reasoning, make the choice of logic explicit: scope, reason, alternatives, premises, definitions and notation. Read `logic_profiles` for the available executable fragments. Where a fragment fits, pin a stage contract through `select_logic`, then `begin_stage` and `check_logic` on a saved raw candidate before consuming its conclusion. Include the candidate in checked and final artifacts. A versioned contract change needs `change_reason`; restore the exact selection through `context`. An unsupported logic may be discussed or used in explicitly unverified work, but must not be labelled mechanically verified. Valid inference does not prove premise truth or faithful translation from natural language. Arbitrary external tools and prose remain outside this gate.

When developing this protocol repository, the small offline smoke test is `python -X utf8 scripts/verify_logic_core.py --quick`. It uses no model/API calls and emits a compact result. Use the broader suite after relevant changes; do not launch paid model trials merely to test a deterministic trap.

For a substantive new goal, register `start`; the agent supplies the plan, not the human. For an existing goal, continue the current task. Ask only for missing information that materially changes the result. In the absence of blocking information, perform authorized investigation while clarifying. Show a short proposed plan in chat; do not require a form or approval for every internal step.

Read [the operation contract](references/contract.md) when creating a plan or recording evidence. Supply `expected_revision` from a fresh state for mutations and a unique `request_id` for retries. JSON is internal data: write it to a temporary file and call the runner with `--input path`, or call the MCP tool. Resolve a conflict by rereading state and retaining the human's correction.

Choose stages only when the task needs them. For each stage describe its task type, required content and relationships, preliminary complexity with a reason, and criteria for readiness. These descriptions must change the approach: context selection, stage size, order or checks. A simple change can use one stage. Do not invent numeric capability scores. On start, record executor.client and executor.model when the environment identifies them; use unknown otherwise. Read experience recommendations in context. After an actual failure or correction, reduce the next stage's scope and check the cause. Never transfer calibration to another model or task type.

Use `begin_stage` before working on the available stage so progress is visible before its checks finish. Execute work with the client's normal tools and permissions. `check` runs an argument-list command for a command criterion and binds it to current files. Put calculations and data validation in executable checks. An agent inspection or human judgment is recorded with its actual origin; never present an assertion as a tool-run check. Preserve current evidence before `complete_stage`. Technically verified inputs open dependent stages; human-gated choices remain distinct.

Before presenting a finished result, complete the applicable artifact checks. Report the result, relevant evidence and remaining gaps in ordinary language. A created image is not proof that its data is correct, and a created image alone is not a completed application. Update the engine as part of the work, without asking the user to request memory saving.

Record `review` only from an actual human message about an identifiable presented result. Resolve ambiguous acceptance with a brief question; do not manufacture it. A design correction targets the design stage; changed data invalidates dependent calculations and visuals. Keep the user's exact feedback and its scope. Acceptance of an artifact does not authorize publication.

If work is interrupted or waiting for information, use `interrupt` and retain the unfinished stage. On a new session or after compaction, restore context and verify changed artifacts before continuing. `.protocol/STATE.md` and `state.json` are generated views; use operations to update the database. File-only clients return an updated portable package with the result; imported command reports need local confirmation.

A textual instruction to use logic does not guarantee actual application. Distinguish a description, output conformance, and actual application. Bind evidence to a specific property and scope; preserve unchecked and unsupported cases separately from success. The strong starting position is that AI errs; correctness must be established through justification and practice, within the available evidence. Version comparisons must disclose conditions, assessment origins, misses, false alarms, delay, tested coverage, and cost; unmeasured quantities remain unknown. More rejections alone do not establish improved task performance.

For new substantive stages, explicitly choose a verification mode with `set_verification`: criteria, formal, empirical, or manual, and record the reason. A mode change versions the requirement and needs fresh checks. Use formal only with a supported logic contract; empirical needs an executed command criterion. Read computed `evidence_summary` property by property. Use `admit_result` when presenting a registered formal conclusion; it returns checked conclusions rather than certifying arbitrary prose. This gate covers the registered runtime operation, not unrestricted external actions. Preserve raw experiment responses; report unknown denominators and costs as unknown, and keep paired replays separate from additional model calls.

The starting position is: AI errs; seek out correct answers. Every answer must
have an explicit logical justification and a confrontation with practice.
Choose the logic before construction, preserve observable transformations, and
present evidence afterwards; a post-hoc narrative does not prove hidden model
reasoning. Before observing practice, specify the claim, conditions, supporting
and refuting observations and alternative causes. Record actual observations and
their scope. A checking AI also errs. Distinguish an established error from a
missing check, even under this strong starting position. Admit only the supported
part; missing evidence remains unfinished work. Runtime verification modes do
not waive either obligation, and current formal admission is not a universal
logic-plus-practice gate.

Use compiled, versioned instructions and explicitly selected rule packs for
paid task requests. Do not inject the entire protocol or repeat full logs by
default. Preserve mandatory core requirements, exact task constraints and
accessible references. The compiler rejects rule assemblies above 12000
characters; this is not an exact token limit. Check whole-request limits and
output/attempt/spend budgets before calls. Never truncate requirements silently
or assume caching will pay for excess context. Measure usage and check costs.


The four pillars are logic, a world picture, development, and checking against
reality. Pin objects, relations, conditions, scale and limits; unfold development
of the subject itself, not just successive drafts or agent actions. A definition,
instruction or declaration must not substitute for this construction; they may
follow from content already developed. Constrain AI choice without sacrificing
quality: test rejection of wrong variants AND retention of correct ones. No silent
skipping, changed premises, weakened checks or fabricated observations. Version
necessary contract changes and recheck. The local file-append adapter is a bounded
example, not universal admission for arbitrary prose or hidden model reasoning.


For protocol v0.5, follow the execution stages from receiving the task to saving
the final state. Every rule belongs to a stage and has an action, a checking method,
and pass/fail/unavailable outcomes. Read the current-stage details when needed;
do not turn definitions or examples into separate preliminary lectures. Record
actual evidence and its origin. A stage selector only selects instructions, not
evidence or admission. If a required check is unavailable, stop its dependent
transition and preserve the missing observation and a continuation. On a changed
premise, recheck from the earliest affected step. Preserve edits made by the human
while synchronizing the schema and compiled instructions to the saved document.
