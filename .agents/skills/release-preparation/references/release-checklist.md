# Release checklist

## Source and compatibility

- Confirm the intended version in package metadata, changelog, tag plan, and release notes.
- Review public Python API, CLI help, JSON output, Schema, Markdown, and paper formats.
- Record intentional incompatibilities; never silently regenerate user data.

## Public README

Require sections for positioning, features, installation, quick start, Studio, CLI, Codex Skill,
MCP status, license, and known limitations. Use only synthetic examples and relative paths.

## Documentation synchronization

- Run `python scripts/check_docs_sync.py`.
- Confirm public CLI commands and MCP tools/resources have user documentation.
- Confirm the capability manifest, repository Skill, package resources, and documentation agree.
- Require compatibility and migration conclusions for Schema or configuration changes.
- Require CHANGELOG coverage for user-visible behavior.
- Require a feature document or equivalent issue summary before new functionality.
- Add an ADR for architecture boundaries, authoritative data, transactions, security, or
  dependency changes.
- Reject machine paths, private data, real questions, answers, and placeholder-only documents.

## Build and inspection

- Build wheel and sdist from the current source in a disposable environment.
- Inspect every archive member. Reject question banks, local databases, logs, caches, audit
  reports, machine paths, and undeclared third-party assets.
- Install the wheel into a separate clean environment and run smoke tests.
- Hash artifacts with SHA-256 and draft release notes without creating a tag or Release.

## Decision

Return BLOCKED for a dirty tree, non-GREEN OSS audit, failed documentation-sync or quality gate,
unsafe documentation, archive mismatch, missing required artifact, or smoke-test failure.
Otherwise return GREEN.
