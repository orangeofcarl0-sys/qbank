# Release checklist

## Source and compatibility

- Confirm the intended version in package metadata, changelog, tag plan, and release notes.
- Review public Python API, CLI help, JSON output, Schema, Markdown, and paper formats.
- Record intentional incompatibilities; never silently regenerate user data.

## Public README

Require sections for positioning, features, installation, quick start, Studio, CLI, Codex Skill,
MCP status, license, and known limitations. Use only synthetic examples and relative paths.

## Build and inspection

- Build wheel and sdist from the current source in a disposable environment.
- Inspect every archive member. Reject question banks, local databases, logs, caches, audit
  reports, machine paths, and undeclared third-party assets.
- Install the wheel into a separate clean environment and run smoke tests.
- Hash artifacts with SHA-256 and draft release notes without creating a tag or Release.

## Decision

Return BLOCKED for a dirty tree, non-GREEN OSS audit, failed quality gate, unsafe documentation,
archive mismatch, missing required artifact, or smoke-test failure. Otherwise return GREEN.
