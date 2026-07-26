# Lightweight source-to-delivery example

This public fixture contains only synthetic questions and a generated one-pixel PNG.
It demonstrates the two independent workspaces used by `$qbank-digitize` and
`$qbank-deliver`.

Use a Python environment in which qbank is installed. When working from the qbank
implementation repository, activate `.venv` first. Validate the source exchange:

```console
python .agents/skills/qbank-digitize/scripts/check_exchange.py examples/workflows/lightweight/digitize
```

Run the deterministic end-to-end demonstration in a new destination. It initializes
an isolated qbank, performs the real MCP prepare/commit/read sequence, freezes a
delivery snapshot, and compiles the solution PDF:

```console
python examples/workflows/lightweight/run_demo.py build/workflows/lightweight-demo
```

Use `--skip-tex` when XeLaTeX is unavailable. The authoritative sequence is
`schema_get → asset_ingest_prepare → operation_commit → ingest_prepare →
operation_commit → question_validate → question_search → question_get → asset_get`.
Asset and question commits are separate operations, so any partial success must be
reported. The destination must be absent or empty; the script never reads or writes
an existing question bank.

For an already prepared workspace, run the builder from the target qbank root:

```console
python .agents/skills/qbank-deliver/scripts/build_delivery.py build/deliver/demo --qbank-root .
```

Each successful edition is written below `output/<variant>/`. `--validate-only`
performs a read-only contract check and does not write to the delivery workspace.
