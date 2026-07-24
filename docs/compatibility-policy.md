# Compatibility policy

qbank treats the documented CLI and data formats as compatibility-sensitive.
The `v0.2.0` tag is an immutable release baseline and must never be moved or
recreated.

## Release lines and independent versions

- Blocking compatibility and security fixes for 0.2.x are developed on
  `release/0.2` and released as `0.2.1` or a later patch.
- New functionality targets `0.3.0`.
- The Python package version is independent from Question, Asset, Paper,
  taxonomy, and view Schema versions. A package release does not imply a
  Schema change, and a Schema change must be versioned and documented
  separately.

## Frozen release and later documentation

The existing `v0.2.0` tag and its wheel, sdist, checksums, and provenance
remain bound to the original frozen commit. Documentation-maintenance commits
made after that tag belong to the candidate `main` history and do not alter the
0.2.0 artifact identity.

GitHub's automatically generated source archives are derived from the selected
tag. The `v0.2.0` source archives therefore do not contain documentation added
after the tag. The repository default branch may show newer maintenance
documentation while the Release continues to attach the previously verified
0.2.0 wheel, sdist, and checksums.

## Preserved interfaces

The following require regression tests when changed:

- command names, option names, defaults, and exit codes;
- JSON field names, nesting, optional-field emission, and diagnostic codes;
- question, paper, and patch JSON Schemas;
- asset and asset-package JSON Schemas, logical `asset:` URI meaning, and
  legacy string asset-path reading;
- accepted Markdown front matter and ordered body sections;
- Python compatibility adapters documented or imported by tests;
- project layout and initialization resources.

New fields may be added only when existing consumers continue to parse output.
Removing or changing a field, command, option, enum value, diagnostic code, or
Markdown meaning requires an explicit compatibility decision and CHANGELOG
entry.

Configuration or Schema changes also require:

1. an updated compatibility or migration document;
2. a feature document that states the data impact;
3. tests for reading supported existing data;
4. an explicit migration procedure, or an explicit statement that migration
   is unnecessary.

## Canonical round trip

For a valid question, this invariant must hold after timestamp normalization:

```text
Question -> exchange JSON -> Question -> Markdown -> Question -> exchange JSON
```

The two exchange JSON values must be equal. JSON Schema is generated directly
from the Pydantic models; stored root schemas must match that output exactly.

## Failure compatibility

Compatibility includes failure behavior. Invalid filters, malformed source
files, unavailable indexes, output conflicts, and invalid exchange data must
retain their documented exit class and stable diagnostic code. JSON mode must
remain parseable and must not mix human warnings into stdout.

## Deprecation

Before release, an internal API may move behind a compatibility adapter.
The adapter must be thin, tested, and documented as such. A user-facing
breaking change requires:

1. an ADR explaining why compatibility cannot be preserved;
2. a CHANGELOG entry;
3. updated schemas and examples;
4. focused migration instructions or an explicit statement that migration is
   unnecessary.

The documentation synchronization gate is part of release preparation.
Missing user documentation, migration guidance, or CHANGELOG coverage blocks
publication even when runtime tests pass.
