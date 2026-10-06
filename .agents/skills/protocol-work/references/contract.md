# Project operation contract

Use `runner.py ACTION --project . --input payload.json`. The input file is JSON; shell quoting is not needed for its contents. All writes except initial `init` require `expected_revision`. A stable `request_id` makes a retry idempotent and rejects different content under that id. Read `context` or `status` after a write.

`start`: `goal`, optional `stages`, optional `executor` with `client` and `model`. Use `unknown` for an unidentified model. With no stages the task is planning and the next action is `plan`. Result contains `operation.task_id`. Scoped experience appears in context; it does not establish universal capability scores.

`plan`: `task_id`, `stages`. A stage has `id`, `title`, `requires` (stage IDs), `type`, `volume`, `complexity`, `criteria` and optional `gate` (`automatic` or `human`). Criteria contain `id`, `text`, `kind` (`command`, `agent_review`, `human`). A plan is an agent proposal, not a human decision. Dependencies must be acyclic.

`begin_stage`: `task_id`, `stage_id`. Current verified input stages are required; a human gate requires actual acceptance of that input.

`logic_profiles`: read-only list of supported formal languages, semantics, rules and checker fingerprint; no expected_revision required.

`select_logic`: `task_id`, `stage_id`, `contract`. Contract fields: id, version, profile, scope, selection_reason, alternatives, enabled_rules, symbols, sources, premises. The choice is recorded as agent-authored. Changes require `change_reason`; a changed contract keeps its id and increases version. Existing checks become stale. Context restores both the contract and the implemented profile. Unsupported profiles/rules are rejected rather than approximated.

`check_logic`: `task_id`, `stage_id`, `candidate_path`, `artifacts`. Requires a running stage with selected logic. The raw JSON candidate is a workspace artifact up to 64000 UTF-8 bytes, included in artifacts. The fixed checker saves the original, violations, canonical conclusion and scope. A check report cannot be supplied by the agent. All final artifacts must be bound to the latest successful local logical check and the candidate must be included in the final result. Ordinary criteria still apply. Imports require local rechecking. This gate covers registered formal results, not arbitrary external actions or semantic truth.

`check`: `task_id`, `stage_id`, `criterion_id`, `artifacts` (relative paths). For `command`, add `argv` (executable and arguments, no shell syntax), optional `timeout` (1–120 seconds). A nonzero exit or changed artifact during the check fails. For `agent_review` or `human`, add `passed` and `evidence`; those origins are explicit. All final stage artifacts must be bound to each applicable check. Use artifact sets that genuinely match the criterion; split stages when their checks concern different outputs.

`complete_stage`: `task_id`, `stage_id`, `summary`, `artifacts`. Current evidence is required for every criterion. It produces technical `verified`, never human `accepted`.

`review`: `task_id`, `outcome` (`accepted`, `revise`, `rejected`), `human_message`; optionally `stage_ids`. Acceptance requires current verified results. A correction invalidates target stages and their dependents. Example: a caption correction targets render, not validated data.

`observe`: `task_id`, `kind`, `summary`, optional `details`, `origin`, `event_id`. This is a report, not executable evidence. Host hooks store observations separately, without changing workflow revisions.

`interrupt`: `task_id`, optional `reason`. The previous result and unfinished stage remain available.

`export`: emits a package with `schema_version`, project ID, `base_revision`, state, continuation text and `operations`, plus `sha256` of canonical JSON excluding that field. `import` receives `package` and `expected_revision`. Canonical JSON is UTF-8, sorted keys, ensure_ascii=False, compact comma/colon separators. File clients add operations as `{action, payload}` and recalculate the checksum. Command checks from packages are not executed automatically. Import rejects another project's package or a stale base. On a new destination initialize through import with expected revision 0 and no operations. Imported checks remain imported and need local confirmation.

`storage`: `host_event_limit` (0–100000), optional `workflow_event_limit` (100–100000) and `command_output` (`none`, `errors`, `all`). Defaults: 2000/2000/errors. The current state is retained; old changes and their retry receipts expire at the history limit. An expired request with an old expected revision is rejected. Logs store deltas and artifact hashes, not repeated artifact copies.

For a text-only file client, read `agent_instructions` and return `reply_template` from the exported package with operations filled in. This is an internal JSON response created by the agent; the human only transfers the file. `import` accepts that `reply` without recalculating the original package's checksum. Project and base revision are still required and checked; embedded commands remain disabled. Full snapshot import continues to require its checksum. Include the actual human feedback only when it was provided.

Relative artifact paths must stay in the project, excluding `.protocol`, `.git`, `.env` and `.env.*`. The check subprocess has the permissions of the Python process; cwd is not a filesystem sandbox. Apply the client's ordinary permissions to tool calls.
