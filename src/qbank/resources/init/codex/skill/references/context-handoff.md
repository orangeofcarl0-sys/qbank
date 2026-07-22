# qbank context and handoff protocol

Use this protocol whenever the active directory is not the target question bank,
source material lives in another project, a task is resumed from a handoff, or the
conversation does not contain reliable project context.

## Classify the invocation

- **Local:** the working directory is the target qbank root or one of its descendants.
- **Cross-project:** the source or active project is elsewhere, while qbank is the
  destination or system of record.
- **Detached:** a handoff describes prior work, but the current environment has not
  verified the target qbank root.

In cross-project and detached modes, do not infer the target from repository names,
recent conversations, or nearby directories.

## Establish the minimum context

Record these fields before acting:

```yaml
objective: <requested outcome>
target_project_root: <verified qbank root>
source_locations: [<explicit input paths or URLs>]
workflow: <import|revise|select|paper|assets|taxonomy|maintenance>
authorization: <read_only|dry_run_only|write_authorized>
acceptance_criteria: [<observable completion conditions>]
unresolved_questions: []
```

Derive fields from visible repository evidence when safe. Ask only for information
that materially changes the target, write scope, or result. If the target root or
authorization cannot be established, stop before running a mutation.

## Bootstrap the target

1. Verify that `<target_project_root>/qbank.yaml` exists.
2. Run commands with `<target_project_root>` as their working directory; do not rely
   on the caller's active directory.
3. Run `qbank codex check --format json`.
4. Run `qbank codex instructions --format json` and compare
   `integration_revision` with the handoff when one is present.
5. Read only the Schema, summaries, and source files needed for the selected workflow.

Treat every non-qbank source project as read-only unless the user separately and
explicitly authorizes writes there. Write qbank exchange data under the target bank's
`build/ai/`, not beside the foreign source.

## Interpret authorization

- `read_only`: inspect and report; create no files and perform no mutations.
- `dry_run_only`: temporary exchange files under `build/ai/` are allowed, but no
  authoritative qbank mutation may be committed.
- `write_authorized`: perform only the requested workflow, still using dry-run first
  and validation after each committed mutation.

Destructive and interactive operations always require their own explicit request;
`write_authorized` alone does not authorize deletion or launching a blocking UI.

## Produce a completion handoff

When work may continue in another task or project, report:

```yaml
integration_revision: <number from codex instructions>
target_project_root: <verified qbank root>
source_locations: []
workflow: <selected workflow>
authorization: <effective authorization>
commands_executed: []
writes: []
validation: <result or not-run reason>
outputs: []
warnings: []
next_step: <single concrete continuation or complete>
```

Record facts and unresolved decisions, not hidden reasoning. A receiving Codex task
must verify the target root and integration revision before continuing a write.
