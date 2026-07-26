# qbank command reference

## Project and schemas

```powershell
qbank doctor --format json
qbank status --format json
qbank schema --kind question --format json
qbank schema --kind paper --format json
qbank schema --kind patch --format json
qbank schema --kind asset-package --format json
qbank codex check --format json
qbank codex instructions --format json
qbank codex install-skill --user --dry-run --format json
qbank codex install-skill --project --update --dry-run --format json
qbank codex install-skill --skill qbank-digitize --user --dry-run --format json
qbank codex install-skill --skill qbank-digitize --project --update --dry-run --format json
qbank codex install-skill --skill qbank-deliver --user --dry-run --format json
qbank codex install-skill --skill qbank-deliver --project --update --dry-run --format json
qbank codex integration-status --format json
qbank codex mcp-check --format json
qbank codex install-mcp --project --dry-run --format json
```

`codex check` reports repository and Codex CLI readiness separately. Skill differences
are warnings until an explicit `install-skill --update` is confirmed. Project updates
back up the current Skill under `.qbank/codex-skill-backups/`; user updates use
`$HOME/.agents/.qbank-backups/skills/qbank/`.

`--skill qbank` is the backward-compatible default. Select `qbank-digitize` for
source calibration and exchange preparation, or `qbank-deliver` for read-only
selection snapshots and fixed-template TeX/PDF construction.

When the source task is in another repository, set the execution working directory to
the target qbank root before running these commands. Do not depend on a prior shell
location or write temporary exchange files into the source repository. The JSON from
`codex instructions` includes `context_protocol`, which defines the required handoff
fields, authorization modes, bootstrap commands, and completion record.

## Optional local MCP

Install the optional SDK with `pip install "qbank[mcp]"`. Project registration is
explicit, repository-bound, and dry-run-first:

```powershell
qbank codex install-mcp --project --dry-run --format json
qbank codex install-mcp --project --yes --format json
qbank codex mcp-check --format json
```

The managed server command is `qbank mcp --repository <absolute-qbank-root>`. Do not
start it manually in unattended shell automation; Codex owns its STDIO lifecycle.
Read tools never write. Mutations require a prepare result and a revision-matched
`operation_commit`; `operation_cancel` is safe to repeat. Remove only the managed block
with `qbank codex uninstall-mcp --project --dry-run` followed by a confirmed write.

## Read and search

```powershell
qbank query --subject optics `
  --fields id,title,subject,chapter,topics,type,difficulty,status `
  --format json
qbank search "光程差" --format json
qbank get OPT-INT-0001 --format json
```

Use `query` before `search`, and `get` only after narrowing candidate IDs.

## Create and import

```powershell
qbank add question.json --dry-run --format json
qbank add question.json --format json
qbank ingest build\ai\source.jsonl --dry-run --format json
qbank ingest build\ai\source.jsonl --format json
qbank validate --format json
```

Existing IDs fail unless `--upsert` is explicit. Do not use upsert to replace a malformed
source file.

## Patch

```powershell
qbank patch OPT-INT-0001 --file build\ai\OPT-INT-0001.patch.json `
  --dry-run --format json
qbank patch OPT-INT-0001 --file build\ai\OPT-INT-0001.patch.json --format json
qbank validate --format json
```

## Logical assets

```powershell
qbank asset ingest OPT-INT-0001 build\ai\asset-package.json --dry-run --format json
qbank asset ingest OPT-INT-0001 build\ai\asset-package.json --format json
qbank asset show OPT-INT-0001 figure-1 --format json
qbank asset render OPT-INT-0001 figure-1 --dry-run --format json
qbank asset render OPT-INT-0001 figure-1 --format json
qbank asset validate --format json
qbank preview --serve
qbank desktop
```

`preview --serve` and `desktop` are blocking interactive commands. Do not launch either
from unattended automation or without an explicit user request.

Use `qbank-asset:<asset-id>` in new Markdown and `\qbankasset{<asset-id>}` in
TeX. Legacy `asset:<asset-id>` remains readable after an explicit
`qbank asset normalize`.
Keep old path assets readable until their source relationship is confirmed.  The local
management page is bound only to localhost and delegates to the same registered-asset
operations as the CLI.

Install `qbank[desktop]` for the optional Qt editor. Its save path performs the
same structured patch dry-run and validation workflow. Ipe edits create a
versioned working copy; rerender and finalization remain explicit.

## Paper and export

```powershell
qbank paper validate papers\generated\optics-test.yaml --format json
qbank paper build papers\generated\optics-test.yaml --format md `
  --output exports\optics-test-student.md
qbank paper build papers\generated\optics-test.yaml --format md `
  --with-solutions --output exports\optics-test-solutions.md
qbank export --subject optics --status reviewed --format jsonl `
  --output exports\optics-reviewed.jsonl
```

Use `--without-answers`, `--without-solutions`, `--without-rubric`, and `--hide-ids`
when the paper YAML enables content that the requested student version must suppress.

## Tags and saved views

```powershell
qbank tag list --format json
qbank tag stats --format json
qbank view list --format json
qbank tag rename old-slug new-slug --dry-run --format json
qbank tag rename old-slug new-slug --format json
qbank validate --format json
```

Use the corresponding dry-run before tag merge, delete, or normalize operations. Saved
views affect only query results and must not silently change question data.

## Explicit maintenance

```powershell
qbank index rebuild --format json
qbank delete OPT-INT-0001 --dry-run --format json
qbank delete OPT-INT-0001 --yes --format json
```

Rebuild the disposable index only when reported unavailable or stale. Delete only after
the user confirms the exact ID and the dry-run result.

## Stable paths

- Authoritative questions: `questions/`
- Local assets: `assets/`
- Temporary AI output: `build/ai/`
- Generated paper definitions: `papers/generated/`
- Final exports: `exports/`
- Rebuildable state: `.qbank/`
