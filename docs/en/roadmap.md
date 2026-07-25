# qbank roadmap

[简体中文](../zh-CN/roadmap.md) · [English documentation](README.md)

This roadmap describes priorities and dependencies after the current `0.3.x` work. It does not
promise release dates. Before implementation, each direction requires a feature document or issue
summary and must follow the [feature lifecycle](../feature-lifecycle.md), including design,
bilingual documentation, tests, compatibility, and limitations.

![qbank roadmap from the unified bank core to broader agent interoperability, an OCR candidate layer, a complete digitization workflow, and MCP observability](../assets/readme/roadmap.en.svg)

## Current foundation

qbank already has the data boundary required for controlled extension:

- question Markdown, logical assets, and project definitions are authoritative files;
- Studio, CLI, Skills, and optional MCP share one application core;
- writes use dry-run, revision checks, a repository lock, transactions, history, and recovery;
- `$qbank-digitize` can define field policy, taxonomy mapping, and representative samples before a
  real digitization project begins;
- current public examples and tests contain no real examination or user data.

The current release has no OCR engine and never writes OCR text directly into authoritative
questions.

## Direction A: more agent and host interoperability tests

The goal is not to embed a specific agent product in qbank. It is to verify that different hosts
understand the same contract.

Planned work:

- minimal project configuration and troubleshooting examples for generic STDIO MCP hosts;
- contract tests for tool discovery, Schema reads, resources, and two-phase writes;
- missing authority, operation expiry, revision conflicts, lost responses, and server restart;
- cross-project handoff fixtures that preserve target bank, source locations, and write authority;
- an evidence table of tested host versions, operating systems, and limitations, with no support
  claim for untested combinations.

Acceptance focuses on protocol and data safety, not duplicated business logic per host.

## Direction B: OCR mediation for documents, images, and PDF

OCR belongs to source adaptation and candidate generation, not the authoritative qbank repository.
The planned mediation layer includes:

- source packages with hashes, media type, page, region, and license/authority notes;
- replaceable OCR adapters, without binding the core to one cloud service or local engine;
- candidate blocks containing source text, recognized text, confidence, layout region, formulas,
  tables, and figure references;
- provenance from every candidate field to a page or region, separating source from inference;
- classification mapping from project-specific tables to qbank subject, chapter, topics, or an
  explicit ignore policy;
- calibration batches that review representative pages before bulk work is authorized;
- uncertainty rules that keep low-confidence, answerless, ambiguous-boundary, or incomplete-source
  content as candidates or `draft`.

An OCR adapter may output candidate exchange data only. It must never create
`questions/**/*.md` or write a logical-asset directory directly.

## Direction C: complete digitization workflow

The complete implementation should connect the existing `$qbank-digitize` decision process to the
candidate layer through a recoverable pipeline:

1. Register source and authority.
2. Parse pages and generate OCR/layout candidates.
3. Identify question boundaries, subquestions, options, answers, formulas, tables, and figures.
4. Apply approved field and classification policy.
5. Calibrate representative samples and inspect batch quality.
6. Generate qbank JSON/JSONL and asset packages.
7. Preview through `$qbank` or MCP prepare.
8. Review diffs, then commit as `draft` or an explicitly confirmed status.
9. Validate, detect duplicates, check provenance completeness, and accept the batch.
10. Retain retryable state, failure reports, and recovery paths.

Mixed Chinese/English text, mathematics, cross-page questions, scan noise, complex tables,
question-figure binding, and answer-book alignment require separate evidence. Until that evidence
exists, the project will not claim one-click PDF ingestion.

## Cross-cutting direction: MCP clarity and observability

MCP work proceeds alongside agent testing, OCR, and digitization:

- maintain a dedicated [MCP guide](mcp-guide.md);
- generate or validate tool, resource, and access-level documentation from the capability manifest;
- provide host configuration only after it has been tested;
- expose operation lifecycle, revision, expiry, warnings, and recovery actions clearly to hosts;
- run client contract and restart-recovery smoke tests against a public synthetic bank;
- keep MCP optional so CLI, Studio, and data formats never depend on one agent.

## Shared definition of done

A roadmap capability becomes implemented only when it has:

- a user goal, boundary, failure behavior, compatibility, and migration conclusion;
- Simplified Chinese and English user documentation;
- a public synthetic fixture with no real exam, local path, or user data;
- deterministic Schema, error-code, or Protocol contracts;
- success, conflict, cancel, timeout, and recovery tests;
- a visible distinction between source content and AI/OCR inference;
- no silent promotion of uncertain content to confirmed fact;
- synchronized README, CHANGELOG, capability matrix, Skills, and known limitations where affected.
