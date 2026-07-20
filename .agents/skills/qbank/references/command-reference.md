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
```

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

## Stable paths

- Authoritative questions: `questions/`
- Local assets: `assets/`
- Temporary AI output: `build/ai/`
- Generated paper definitions: `papers/generated/`
- Final exports: `exports/`
- Rebuildable state: `.qbank/`
