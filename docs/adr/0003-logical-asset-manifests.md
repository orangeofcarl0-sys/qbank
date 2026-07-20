# ADR 0003: Logical assets are authoritative manifests with representations

## Status

Accepted.

## Context

A question diagram can have an original crop, a reconstructed Ipe source,
TikZ reference, and multiple target-specific renders.  Treating each file as
an unrelated `assets/...` attachment loses provenance and makes replacement or
export selection unsafe.  The 841 digitization project must remain an input
producer rather than a writer of qbank's authoritative store.

## Decision

Store one `asset.yaml` under `assets/<question-id>/<asset-id>/`.  It owns the
logical asset's status, preference pointers, provenance, review notes and
representation graph.  Local files are hash checked and contained under that
asset directory; remote URLs remain explicit representations.  Packages are
validated and normalized by qbank through asset ports and a transaction.

Legacy string paths remain readable.  A manifest can preserve their provenance
and `qbank asset normalize` can replace them with `asset:<asset-id>` after an
explicit mutation.  Paper/export/preview select a representation using a
target-specific ordered policy, emitting warnings for unfinished assets and
optionally rejecting them for papers.

## Consequences

The question Markdown format remains stable and does not embed Base64.  New
tools need only produce `asset-package.json`; Ipe discovery, rendering, safe
launching and history are qbank responsibilities.  Static preview remains
serverless; privileged asset buttons appear only in the localhost management
server.
