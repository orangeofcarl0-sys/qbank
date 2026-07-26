# qbank user guide

[简体中文](../zh-CN/user-guide.md) · [English documentation](README.md)

This guide covers the qbank `0.3.0-beta.2` project layout, data boundaries, and primary
command-line workflows. Data Schemas remain at `1.0`. Run each command with `--help` for its
complete option contract and see the [installation guide](installation.md) for deployment.

## Project layout

`qbank init [DIR]` creates a local question bank. Commands search upward from the working directory
for `qbank.yaml`, so they can be run from any subdirectory of the bank.

| Path | Purpose | Data role |
| --- | --- | --- |
| `questions/` | Question Markdown | Authoritative |
| `assets/` | Local resources and logical-asset manifests | Authoritative |
| `taxonomy.yaml` | Tag registry | Authoritative |
| `views.yaml` | Saved query views | Authoritative |
| `papers/` | Paper definitions | User-maintained |
| `templates/` | Paper templates and optional reference DOCX | User-maintained |
| `.qbank/history/` | Authoritative write summaries | Committed with Markdown |
| `.qbank/index.sqlite` | Full-text search projection | Rebuildable |
| `build/` | Temporary build and AI exchange files | Disposable |
| `exports/` | Final exports | Rebuildable output |

Initialization preflights every managed file. If any target exists, it exits with code 5 and writes
nothing. Only explicit `--force` permits replacement of initialization resources.

```powershell
qbank init demo-bank
Set-Location demo-bank
qbank doctor --format json
```

## Question format and Schemas

Questions are stored at `questions/<subject>/<ID>.md`. YAML front matter contains short metadata;
ordered Markdown sections contain the stem, choices, answer, solution, rubric, and review notes.
`schema_version`, a non-empty stem, and at least one valid topic are model requirements.

Read the relevant Schema before producing exchange data:

```powershell
qbank schema --kind question --format json
qbank schema --kind paper --format json
qbank schema --kind patch --format json
qbank schema --kind asset-package --format json
```

JSON and JSONL are exchange formats, not another authoritative bank. Timestamps require a timezone
and are normalized to UTC.

## Authoritative writes

Except for initialization, preview question, tag, view, and asset writes with `--dry-run`; then run
the identical committed operation and validate the bank.

```powershell
qbank ingest build\ai\source.jsonl --dry-run --format json
qbank ingest build\ai\source.jsonl --format json
qbank validate --format json
```

Batch ingestion is all-or-nothing by default. Use `--continue-on-error` only when skipping invalid
lines is explicitly acceptable; `line`, `skipped`, and diagnostic fields identify input problems.
Use a structured patch for revisions:

```powershell
qbank patch OPT-INT-0001 --file build\ai\OPT-INT-0001.patch.json `
  --dry-run --format json
qbank patch OPT-INT-0001 --file build\ai\OPT-INT-0001.patch.json --format json
qbank validate --format json
```

Neither ordinary writes nor `--upsert` may replace unparseable Markdown. Repair that source manually,
or delete it only after confirming the intended ID.

## Structured queries and full-text search

Structured queries filter the repository snapshot by subject, chapter, topic, type, status, year,
and difficulty. Full-text search and complete reads can then refine the candidate set.

```powershell
qbank query --subject optics --status reviewed `
  --fields id,title,subject,chapter,topics,type,difficulty,status `
  --format json
qbank search "optical path" --format json
qbank get OPT-INT-0001 --format json
```

Queries of two or fewer characters or containing short terms use parameterized SQLite `LIKE`; longer
queries use trigram FTS5. Read-only search never creates an index and fails clearly when the index is
missing, corrupt, stale, or dirty.

## Tags and saved views

`taxonomy.yaml` stores canonical slugs, display names, aliases, colors, descriptions, and parent tags.
It does not store question/tag relationships; those come only from each question's `topics` field.

```powershell
qbank tag list --format json
qbank tag stats --format json
qbank tag cooccur --top-n 12 --format json
qbank tag rename old-slug canonical-slug --dry-run --format json
qbank tag rename old-slug canonical-slug --format json
qbank validate --format json
```

Rename, merge, delete, and normalization commit taxonomy, question Markdown, and history as one
authoritative unit. `views.yaml` stores visible filter combinations; views do not mutate questions or
add hidden data constraints.

## Local resources and logical assets

A local image must use a bank-relative path, remain under the configured assets directory, exist,
and appear both in body references and the YAML `assets` declaration. HTTP, HTTPS, and protocol-relative
URIs are allowed with warnings. Absolute paths, `file:`, `data:`, and escaping paths are rejected.

Logical assets use stable IDs for original references, editable sources, and PDF/SVG/PNG renders.
New Markdown uses `qbank-asset:<asset-id>`; TeX uses `\qbankasset{<asset-id>}`.

```powershell
qbank asset show OPT-INT-0001 figure-1 --format json
qbank asset ingest OPT-INT-0001 build\ai\asset-package.json --dry-run --format json
qbank asset ingest OPT-INT-0001 build\ai\asset-package.json --format json
qbank asset render OPT-INT-0001 figure-1 --dry-run --format json
qbank asset render OPT-INT-0001 figure-1 --format json
qbank asset validate --format json
```

Replacement appends content-addressed versions instead of overwriting representations. Ipe editing,
rerendering, preferred-representation changes, and `final` status are explicit. External resources
are never downloaded automatically.

## Papers, export, and preview

Paper definitions live in `papers/`; generated definitions should use `papers/generated/`. Validate
before producing student or solution variants.

```powershell
qbank paper validate papers\generated\optics-test.yaml --format json
qbank paper build papers\generated\optics-test.yaml --format md `
  --output exports\optics-test-student.md
qbank paper build papers\generated\optics-test.yaml --format md `
  --with-solutions --output exports\optics-test-solutions.md
```

Paired flags override paper defaults in either direction: `--with-answers/--without-answers`,
`--with-solutions/--without-solutions`, `--with-rubric/--without-rubric`, and
`--show-ids/--hide-ids`.

```powershell
qbank export --subject optics --status reviewed --format jsonl `
  --output exports\optics-reviewed.jsonl
qbank preview
```

The system Pandoc executable produces DOCX. If unavailable, DOCX exits with code 7 while Markdown
and HTML remain available. `qbank preview --serve` and `qbank desktop` are interactive blocking
commands and must not be launched silently by unattended automation.

## Diagnostics and index maintenance

```powershell
qbank status --format json
qbank doctor --format json
qbank validate --format json
qbank index rebuild --format json
```

The SQLite index updates only after authoritative commit. If synchronization fails, Markdown remains
committed, `.qbank/index.dirty` is written, and a warning is returned. A successful atomic rebuild
clears the marker. A deliberately disabled index is not dirty.

## Exit codes

| Code | Meaning |
| ---: | --- |
| 0 | Success |
| 1 | General error or project not found |
| 2 | CLI argument error |
| 3 | Data, question, query, or paper validation failure |
| 4 | Question not found |
| 5 | Conflict or duplicate ID |
| 6 | Export failure |
| 7 | Missing external dependency such as Pandoc |
