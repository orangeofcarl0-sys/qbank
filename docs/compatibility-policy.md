# Compatibility policy

qbank is at version 0.2.0 and is not yet released, but the repository treats
the documented CLI and data formats as compatibility-sensitive.

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
