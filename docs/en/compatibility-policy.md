# Compatibility policy

[简体中文](../zh-CN/compatibility-policy.md) · [English documentation](README.md)

qbank treats its documented CLI and data formats as compatibility-sensitive. Published tags
identify their original releases and are not moved or recreated; fixes are delivered as new
versions.

## Release lines and independent versions

- Blocking compatibility and security fixes for 0.2.x are developed on `release/0.2` and released
  as `0.2.1` or a later patch.
- New functionality targets `0.3.0`.
- The Python package version is independent from Question, Asset, Paper, taxonomy, and view Schema
  versions. A package release does not imply a Schema change; every Schema change is versioned and
  documented separately.

## Published releases and later documentation

The `v0.2.0` tag and its wheel, sdist, checksums, and provenance remain associated with that release
commit. Documentation-maintenance commits made afterward belong to later `main` history and do not
change artifact identity. GitHub-generated source archives follow the selected tag and therefore do
not include later documentation.

## Preserved interfaces

Changes to the following require compatibility review and regression tests:

- command and option names, defaults, and exit codes;
- JSON field names, nesting, optional-field emission, and diagnostic codes;
- question, paper, patch, asset, and asset-package JSON Schemas;
- logical asset URI meaning and legacy asset-path reads;
- accepted Markdown front matter and ordered body sections;
- documented or tested Python compatibility adapters;
- project layout and initialization resources.

New fields may be added only when existing consumers continue to parse the result. Removing or
changing a field, command, option, enum, diagnostic code, or Markdown meaning requires an explicit
compatibility decision and CHANGELOG entry.

Configuration or Schema changes also require an updated compatibility or migration document, a
feature document stating the data impact, tests that read supported existing data, and either a
migration procedure or an explicit conclusion that no migration is required.

## Canonical round trip

After timestamp normalization, a valid question must preserve this invariant:

```text
Question -> exchange JSON -> Question -> Markdown -> Question -> exchange JSON
```

The exchange JSON values must be equal. JSON Schema is generated directly from Pydantic models, and
stored root Schemas must match that output exactly.

## Failure compatibility

Compatibility includes failure behavior. Invalid filters, malformed source, unavailable indexes,
output conflicts, and invalid exchange data retain documented exit classes and stable diagnostics.
JSON mode remains parseable and never mixes human warnings into stdout.

## Deprecation and documentation

Before release, an internal API may move behind a thin, tested compatibility adapter. A user-facing
breaking change requires an ADR, CHANGELOG entry, updated Schemas and examples, and focused migration
instructions or an explicit no-migration statement.

The documentation synchronization gate is part of release preparation. Missing user documentation,
translation parity, migration guidance, or CHANGELOG coverage blocks publication even if runtime
tests pass.
