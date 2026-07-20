# ADR 0002: Explicit ports and one composition root

- Status: accepted
- Date: 2026-07-19

## Context

Direct construction of Markdown and SQLite implementations inside CLI and
application functions made read use cases difficult to reuse and test with a
different index implementation.

## Decision

Application services depend on small repository, validation, and index
protocols. `qbank.bootstrap` is the single place that wires the current
Markdown and SQLite adapters. These protocols are internal seams, not a
runtime plugin system.

## Consequences

Python callers may use the application service without Typer, Rich, or stdout.
Tests can supply in-memory fakes. CLI modules do not import storage or SQLite
implementations. Adding a backend changes its adapter, bootstrap registration,
and tests rather than core query or validation logic.

