---
name: oss-readiness
description: Audit a repository before first open-source publication. Use when Codex is asked to open source, sanitize, make public, assess repository disclosure risk, review licenses or distributable contents, or prepare a public README. Scan the current tree and Git history without deleting or modifying suspicious content.
---

# OSS readiness

Audit before changing public-facing content or preparing a release. Treat every finding as
evidence to review, not permission to delete data.

## Run the audit

1. Work at the repository root and preserve the current worktree.
2. Read [references/policy.md](references/policy.md) for severity and qbank-specific rules.
3. Run:

   ```powershell
   python .agents/skills/oss-readiness/scripts/audit.py --root .
   ```

4. Inspect all files under `build/oss-audit/`. Never paste a full detected credential into a
   report, terminal, issue, or chat.
5. Classify every HIGH or CRITICAL finding as confirmed, false positive, or remediated. Do not
   alter or remove suspicious content unless the user separately authorizes remediation.
6. Report missing deterministic tools as degraded coverage. Do not describe a degraded scan as
   comprehensive.

The script prefers gitleaks, trufflehog, pip-audit, deptry, and REUSE when installed. Its local
fallback scans tracked, untracked, ignored-risk, archive, media, package, and full Git-history
surfaces and stores only redacted evidence hashes.

## Required outputs

Require these files before declaring readiness:

- `build/oss-audit/readiness-report.md`
- `build/oss-audit/findings.json`
- `build/oss-audit/tracked-files.txt`
- `build/oss-audit/distributable-files.txt`
- `build/oss-audit/license-report.json`
- `build/oss-audit/secret-scan-report.json`

GREEN means no unresolved HIGH or CRITICAL finding and no required scan failure. Warnings about
missing optional tools remain visible. Never publish based solely on a GREEN summary; review the
actual distributable file list.
