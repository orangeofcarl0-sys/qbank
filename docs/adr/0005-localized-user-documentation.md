# ADR 0005: Localized user documentation uses paired locale trees

- Status: Accepted
- Date: 2026-07-24

## Context

qbank documentation had no explicit language boundary. Some pages were Chinese, some were
English, and some mixed both languages. Readers could not reliably discover an equivalent page
in another language, while moving every existing document would break established links.

## Decision

The default root README remains Simplified Chinese and gains a complete `README.en.md` peer.
User-facing documentation is maintained as explicit pairs under `docs/zh-CN/` and `docs/en/`.
`docs/README.md` is the language gateway. Established top-level document paths remain as small
compatibility pages that link to both localized versions.

The localization policy defines a managed coverage list. The deterministic docs-sync gate checks
that every listed pair exists, has language navigation, resolves local links, and—where relevant—
documents the same public CLI surface. Internal ADRs, architecture notes, code-review rules, and
design research may retain one working language until they enter the managed user-facing set.

## Alternatives considered

- Moving all existing pages into locale directories was rejected because it would break links.
- Keeping mixed-language pages was rejected because discoverability and maintenance ownership
  remain ambiguous.
- Machine-translating every internal note was rejected because nominal coverage would not ensure
  accurate or useful documentation.

## Consequences

User-facing changes must assess and update both locale peers. Reviewers can distinguish intentional
single-language maintainer material from missing user documentation. Adding a new supported locale
requires a locale index and complete coverage of the managed user-facing set before it is advertised.
