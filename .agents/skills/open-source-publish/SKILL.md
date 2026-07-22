---
name: open-source-publish
description: Orchestrate a repository's complete open-source preparation and publication workflow. Use when Codex is asked to take a private project toward open source across auditing, remediation, release preparation, approval, and GitHub publication. It delegates to the specialized repository Skills and never duplicates their scanning, building, or publishing logic.
---

# Open-source publish

Coordinate these repository Skills in order:

1. Run `$oss-readiness` and review all evidence.
2. Remediate confirmed blockers only within the user's authorized scope, then rerun
   `$oss-readiness` until GREEN.
3. Run `$release-preparation` and review archives, checksums, notes, and its GREEN/BLOCKED result.
4. Stop and show the complete remote publication plan. Obtain explicit user approval to make the
   repository public, push code and tag, and create the GitHub Release.
5. Only after that approval, run `$github-publish` prepare and then its confirmation-gated commit
   phase.

Do not implement scans, builds, Git operations, or GitHub calls here. Do not interpret a request
to prepare, audit, clean, document, or plan as permission to publish.

## Manual acceptance

Walk through the orchestration with a deliberately BLOCKED audit and confirm it stops before
release preparation or publication as appropriate. With synthetic GREEN fixture reports, confirm
it shows the GitHub prepare plan and pauses for explicit approval. Without that approval, verify
there is no new commit, tag, push, visibility change, repository, or Release.
