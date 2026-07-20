# ADR 0001: Markdown is authoritative

- Status: accepted
- Date: 2026-07-19

## Context

qbank needs transparent local editing, durable review history, full-text
search, previews, and export formats. Treating both Markdown and SQLite as
authoritative would create two competing states and ambiguous recovery.

## Decision

Question Markdown and `qbank.yaml` are authoritative. SQLite, previews, paper
builds, and exports are projections. Read operations never initialize or
repair a projection. Mutations commit Markdown/history first, then update the
index; index failure marks the projection dirty without rolling back
authoritative files.

## Consequences

Search refuses missing, corrupt, stale, or dirty enabled indexes. Rebuild is
explicit and replace-on-success. Recovery always starts from Markdown.

