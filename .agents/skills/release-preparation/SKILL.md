---
name: release-preparation
description: Prepare and verify a Python repository release without publishing it. Use when Codex is asked to update release documentation or versions, run quality gates, build wheel and sdist artifacts, generate checksums or release notes, assess release readiness, or prepare a GitHub release draft.
---

# Release preparation

Prepare local release artifacts only. Never create a tag, push a branch, change repository
visibility, or create a GitHub Release.

## Workflow

1. Read `build/oss-audit/readiness-report.md`; run `$oss-readiness` first when it is missing or
   stale.
2. Read [references/release-checklist.md](references/release-checklist.md).
3. Check version consistency and edit README, CHANGELOG, and package version intentionally.
   README must cover positioning, features, installation, quick start, Studio, CLI, Codex Skill,
   MCP status, license, and known limitations. Never add machine paths or real exam material.
4. Run the project quality gates before building.
5. Run:

   ```powershell
   python .agents/skills/release-preparation/scripts/prepare_release.py --root .
   ```

6. Review `build/release/release-readiness.md`, `release-plan.json`, `release-notes.md`, artifact
   contents, and `checksums.txt`.
7. Report GREEN only when the script reports GREEN. A dirty worktree, failed audit, failed gate,
   incompatible version, unsafe README, bad archive content, or failed isolated smoke test is
   BLOCKED.

The script builds wheel and sdist in an isolated temporary environment, installs the wheel in a
second clean environment, and exercises `qbank --help`, schema output, and package imports. It
does not mutate source documentation or version files automatically.
