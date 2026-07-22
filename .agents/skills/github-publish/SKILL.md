---
name: github-publish
description: Publish an already approved open-source release to GitHub with strict two-phase safeguards. Use only after the user explicitly asks for formal publication, pushing to a public repository, creating a version tag, or creating a GitHub Release. Do not trigger for audits, planning, local builds, or release drafts.
---

# GitHub publish

Perform remote publication only after explicit user authorization in the current conversation.
Never infer approval from an earlier audit or release-preparation request.

## Prepare phase

Run the read-only phase first:

```powershell
python .agents/skills/github-publish/scripts/publish.py prepare --root . \
  --repository OWNER/REPO --tag vX.Y.Z --visibility public
```

Show the generated plan: repository, visibility, branch, commit, tag, Release title, and every
attachment with its hash. Preparing must not create commits, tags, pushes, repositories, or
Releases.

## Commit phase

Proceed only if all are true:

- OSS readiness is GREEN.
- Release preparation is GREEN.
- The worktree is clean.
- Version, unused tag, target repository, and public visibility are explicit.
- The user explicitly confirms public remote writes after seeing the plan.

Then run the exact command printed by prepare, including `--confirm-publish`. The script refuses
commit without that flag. Never force push, delete a remote, overwrite a tag, or reuse an existing
Release. After publication, download or install the published artifact, smoke-test it, and retain
the actual URL, tag, commit, attachment names, and SHA-256 values in the publication record.

## Manual acceptance

1. Run prepare against a disposable local fixture and confirm the Git HEAD and tag list do not
   change and no `gh` write command runs.
2. Run commit without `--confirm-publish` and confirm exit code 5 before any remote probe or write.
3. Use a mocked GitHub boundary to exercise existing tag, failed atomic push, failed Release,
   download mismatch, and successful installed-wheel smoke paths.
4. Perform a live publication only in a disposable repository after separate explicit approval;
   verify the recorded URL, commit, tag, attachments, and hashes.
