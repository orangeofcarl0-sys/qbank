# qbank

[简体中文](README.md) · [English](README.en.md) · [Documentation](docs/README.md)

`qbank` is a local-first structured question-bank system for reliable human–AI collaboration.
Questions are durable Markdown files with YAML front matter; JSON and JSONL are exchange formats;
SQLite is only a rebuildable search projection; and `paper.yaml` describes reviewable, reproducible
papers.

> **Version status:** `0.2.0` is the current frozen release baseline and requires Python 3.11 or
> later. Markdown is the sole authority for question content; indexes, previews, and exports are
> rebuildable.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/studio-main-dark.png">
  <img src="docs/assets/readme/studio-main-light.png" alt="qbank Studio with question navigation, Markdown source, live preview, and structured Inspector" width="1680">
</picture>

| Interface | Best for | Start with |
| --- | --- | --- |
| Studio | Browsing, editing, tags, assets, and paper composition | `qbank desktop` |
| CLI | Batch import, validation, queries, export, and automation | `qbank --help` |
| Codex Skill / MCP | Codex collaboration under the same data boundary | `qbank codex integration-status --format json` |

## Purpose and capabilities

qbank serves individuals and small teams who want questions to remain ordinary, versionable files
while desktop editing, command-line automation, and AI tools share the same validation and transaction
rules. It provides structured questions, deterministic validation, filters and full-text search,
managed assets, reproducible paper variants, and multiple export formats. It is not an online exam
service, account system, learning-record store, automatic grader, OCR engine, or embedded model service.

## Studio desktop editor

Studio is an optional local Qt application with no Web backend and no second question store. The
left column provides navigation and filters, the center provides source and live preview, and the
right Inspector provides properties, assets, provenance, and history.

![Studio asset and question details in dark mode](docs/assets/readme/studio-assets-dark.png)

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -U pip setuptools wheel
pip install -e ".[desktop]"
qbank desktop
```

On Windows, standard CPython avoids common Qt DLL conflicts from other Python distributions. See
the [Studio guide](docs/en/desktop-editor.md) and [design system](docs/ui/design-system.md).

## Quick start

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -U pip setuptools wheel
pip install .

qbank init demo-bank
Set-Location demo-bank
qbank doctor --format json
```

`examples/public-demo/` is entirely self-authored and contains no real examination or user-bank
material. Verify a Release wheel against the Release checksum before installing it:

```powershell
Get-FileHash .\qbank-0.2.0-py3-none-any.whl -Algorithm SHA256
pip install .\qbank-0.2.0-py3-none-any.whl
```

For development, install all quality and Studio test dependencies with
`pip install -e ".[dev,studio-dev]"`.

## Safe write workflow

![qbank safe write flow from project check and Schema through dry-run, commit, validation, and index recovery](docs/assets/readme/safe-workflow.svg)

Every authoritative write follows one sequence: inspect the Schema or current record, run a dry-run,
review the result, commit the identical operation, and validate. Index synchronization follows the
Markdown/history commit. An index failure leaves authoritative content committed, creates a dirty
marker, and requires explicit rebuild.

```powershell
qbank schema --format json
qbank ingest ..\examples\questions.jsonl --dry-run --format json
qbank ingest ..\examples\questions.jsonl --format json
qbank validate --format json
```

Do not edit `questions/**/*.md` directly by default and never edit `.qbank/index.sqlite` manually.
Ordinary writes and `--upsert` do not overwrite damaged Markdown.

## Data boundary

![qbank data architecture with authoritative Markdown and logical assets plus rebuildable projections](docs/assets/readme/data-architecture.svg)

- `questions/` contains authoritative question Markdown.
- `assets/` contains managed local resources and logical-asset manifests.
- `.qbank/history/` commits with Markdown as one authority unit.
- `.qbank/index.sqlite` is a rebuildable search projection.
- `papers/` contains definitions; `exports/` contains final output; `build/` contains temporary output.
- JSON Schema is generated from Pydantic models rather than maintained separately.

HTTP, HTTPS, and `//host` images are allowed with `external_asset` warnings. Absolute, `file:`,
`data:`, and escaping paths are rejected. Jinja templates execute in a sandbox, but custom templates
remain a user-reviewed trust boundary.

## Common workflows

```powershell
qbank query --subject optics --status reviewed `
  --fields id,title,subject,chapter,topics,type,difficulty,status `
  --format json
qbank search "optical path" --format json
qbank get OPT-INT-0001 --format json

qbank tag list --format json
qbank view list --format json

qbank schema --kind asset-package --format json
qbank asset ingest OPT-INT-0001 build\ai\asset-package.json --dry-run --format json
qbank asset validate --format json

qbank paper validate papers\generated\optics-test.yaml --format json
qbank paper build papers\generated\optics-test.yaml --format md `
  --output exports\optics-test-student.md
```

DOCX uses the system Pandoc executable; Markdown and HTML remain available when Pandoc is missing.

## Codex integration

New banks include `$qbank`, the deterministic repository communication protocol, and the separate
optional `$qbank-digitize` domain guide for PDF/scan field policy and calibration. Codex Desktop,
IDE, or CLI can use these rules with local commands, or call the same services through optional
STDIO MCP. qbank itself needs no OpenAI API key.

```powershell
qbank codex check --format json
qbank codex instructions --format markdown
qbank codex install-skill --skill qbank --user --dry-run --format json
qbank codex install-skill --skill qbank-digitize --user --dry-run --format json
qbank codex install-mcp --project --dry-run --format json
qbank codex integration-status --format json
```

MCP writes use a revision-checked prepare/commit protocol. Prepared operations persist under
`.qbank/mcp-operations/`; replaying a committed operation returns its first result without writing
twice. See the [Codex and MCP guide](docs/en/codex-integration.md).

## Documentation

| Document | Contents |
| --- | --- |
| [English documentation home](docs/en/README.md) | Complete English navigation |
| [User guide](docs/en/user-guide.md) | Daily data and command workflows |
| [CLI reference](docs/en/cli-reference.md) | Public commands and automation boundaries |
| [Studio guide](docs/en/desktop-editor.md) | Desktop interaction and resource behavior |
| [Codex and MCP](docs/en/codex-integration.md) | Skills, cross-project context, MCP, and authorization |
| [0.2.0 compatibility baseline](docs/en/compatibility-0.2.0.md) | Frozen CLI, Schema, MCP, diagnostics, and capabilities |
| [Compatibility policy](docs/en/compatibility-policy.md) | Stable interfaces and release rules |
| [0.2.0 known limitations](docs/en/known-limitations-0.2.0.md) | Filesystem, transaction, performance, and product limits |
| [Architecture](docs/architecture.md) | Layers, ownership, transactions, and extension boundaries |

All commands provide `--help`. Machine-readable output belongs on stdout; human diagnostics belong
on stderr. Use `--format json` for automation.

## License

qbank is released under the [MIT License](LICENSE). Third-party frontend resources embedded in
Studio and their licenses are listed in
[`THIRD_PARTY_NOTICES.md`](src/qbank/resources/desktop/THIRD_PARTY_NOTICES.md).
