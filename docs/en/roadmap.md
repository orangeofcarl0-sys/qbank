# qbank roadmap

[简体中文](../zh-CN/roadmap.md) · [English documentation](README.md)

This roadmap describes priorities after the current `0.3.x` work and promises no release dates.
Before implementation, each direction still requires a feature document or issue summary and must
follow the [feature lifecycle](../feature-lifecycle.md), including bilingual documentation, tests,
compatibility, and limitations.

![qbank roadmap from the unified bank core to agent interoperability, lightweight source ingestion, and lightweight TeX delivery workflows](../assets/readme/roadmap.en.svg)

## Current foundation

qbank already has stable boundaries for controlled extension:

- question Markdown, logical assets, and project definitions are authoritative files;
- Studio, CLI, Skills, and optional MCP share one application core;
- writes use dry-run, revision checks, a repository lock, transactions, history, and recovery;
- MCP already provides search, get, Schema, prepare, commit, and validation;
- `$qbank-digitize` provides field policy, classification mapping, representative samples, and a
  read-only exchange check;
- `$qbank-deliver` provides read-only snapshots, controlled TeX, an original Chinese template,
  and atomic PDF output;
- public examples and tests contain no real examination or user data.

The current release contains no OCR engine and never writes OCR output directly into authoritative
questions.

## Direction A: more agent and host interoperability tests

The goal is to verify that different hosts understand the same qbank contract, not to embed one
agent product in the core:

- provide tested generic STDIO MCP configuration and troubleshooting examples;
- cover tool discovery, Schema reads, resources, and two-phase writes;
- verify missing authority, operation expiry, revision conflicts, lost responses, and server
  restart;
- use cross-project handoff fixtures that preserve the target bank, sources, and write authority;
- record only host versions, operating systems, and limitations that have actually been tested.

## Direction B: lightweight source → qbank

The first lightweight vertical slice is implemented and prefers existing MinerU output:

1. MinerU performs extraction in the source project.
2. AI and `$qbank-digitize` identify boundaries, formulas, answers, classification, and figure
   ownership.
3. They generate `questions.jsonl`, existing-Schema Asset packages, and a `review.md` containing
   only unresolved items.
4. Existing MCP performs `prepare → inspect → commit → validate`.
5. Uncertain content remains `draft`, with source file, page or range, and printed number
   traceable.

qbank does not embed MinerU, create a generic Candidate database or job platform, or add MCP tools.

## Direction C: lightweight qbank → formal deliverables

The first lightweight vertical slice is implemented by `$qbank-deliver`; orchestration remains in
the delivery project:

1. Search and read questions through existing MCP.
2. AI and `$qbank-deliver` generate an explicit `selection.yaml` and controlled TeX.
3. A fixed template defines page, fonts, numbering, answer space, and content variants.
4. `latexmk` / XeLaTeX builds PDF or another deliverable in an isolated directory.
5. The build treats qbank as read-only and checks mathematics, figures, readability, and answer
   leakage.

`selection.yaml` and TeX remain project conventions rather than a new Paper Schema. See
[Source → qbank → formal deliverables](source-qbank-deliverables.md) for the complete requirements.

## Optional future research

`CandidateBlock`, `DigitizationDecisionPacket`, `DeliveryProfile`, a complete `BuildManifest`,
durable job platforms, and automatic page-by-page publishing acceptance are not current goals.
Only multiple independent projects proving that lightweight file conventions are insufficient can
justify a focused new proposal. qbank does not promise a generic OCR platform or complete
publishing system.

## Cross-cutting direction: MCP clarity and observability

- maintain a dedicated [MCP guide](mcp-guide.md);
- validate tool, resource, and access-level documentation from the capability manifest;
- expose operation revision, expiry, warnings, and recovery actions clearly to hosts;
- run client-contract and restart-recovery smoke tests with a public synthetic bank;
- keep MCP optional so CLI, Studio, and data formats never depend on one agent;
- reuse existing tools for digitization and TeX builds without adding arbitrary file or process
  execution.

## Shared definition of done

A roadmap capability becomes implemented only after it has a clear user goal, boundaries, failure
behavior, bilingual documentation, public synthetic fixtures, deterministic contracts, and
recovery tests. Source content must remain distinguishable from AI inference, uncertain content
must never be promoted silently, and one project must not justify expanding qbank core.
