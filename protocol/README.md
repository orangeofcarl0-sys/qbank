# Studio Protocol v1

Studio Protocol v1 is a private local transport between the Tauri process under
`apps/studio/` and the bundled `qbank.studio_sidecar` adapter in the same
repository. Each line on stdin or stdout contains exactly one UTF-8 JSON-RPC 2.0
object. Sidecar logs and tracebacks are written only to stderr.

The protocol is repository-bound after a successful `repository.open`. That method returns one
bootstrap result containing repository status, question summaries, tags, and saved views. The
sidecar changes its active repository only after all bootstrap reads succeed. `question.save` requires
the revision returned by `question.get`; stale revisions fail with a conflict. Asset
methods accept bytes rather than arbitrary source paths. Open/edit/reveal actions are
delegated to qbank's registered, containment-checked asset launcher.

`protocol/studio-protocol-v1.json` is the contract authority. TypeScript and Python
tests load the same file and reject method drift.

## Methods

Lifecycle methods are `initialize`, `repository.open`, `repository.rebuildIndex`,
`repository.status` and `application.shutdown`. `repository.rebuildIndex` is advertised through
`initialize.capabilities` and is a write method: clients call it only after explicit user
confirmation when open reports a repairable index diagnostic. Rebuild failure does not change the
active repository.

Question and taxonomy methods are `question.search`, `question.list`, `question.get`,
`question.validate`, `question.save`, `question.update`, `question.create`,
`question.copy`, `question.import`, `question.delete`, `question.bulkUpdate`,
`taxonomy.list`, `taxonomy.suggest`, `taxonomy.overview`, `taxonomy.update`,
`taxonomy.rename`, `taxonomy.merge`, `taxonomy.delete` and `taxonomy.bulkEdit`.

Saved-view methods are `view.list`, `view.apply`, `view.save`, `view.rename` and
`view.delete`.

Asset and history methods are `asset.list`, `asset.open`, `asset.create`,
`asset.replace`, `asset.render`, `asset.reconcile` and `history.list`.

`asset.list` retains its original fields and adds a reference classification, declaration and
existence state, stable diagnostic, controlled preview, and typed capabilities. The four
classifications are logical, local, external, and invalid. Absolute filesystem locations are not
part of the frontend contract. `asset.open` may receive a reference, but the sidecar recomputes the
current question inventory and opens it only when the exact reference is still allowed.

Paper methods are `paper.list`, `paper.get`, `paper.create`, `paper.save`,
`paper.addQuestions`, `paper.validate` and `paper.build`.

All write methods carry an expected repository revision or operate on the revision
returned by the immediately preceding read. The sidecar performs qbank dry-run before
commit. A stale revision is a conflict and must be reloaded rather than retried blindly.
Tag relation changes and bulk edits use qbank's atomic taxonomy, Markdown, history and
index transaction. Status and chapter bulk edits use qbank's atomic batch-ingest
service. Saved-view writes are protected by the repository lock and retain complete
validated `QueryFilters`, including conditions with no current match.

`repository.open` creates one qbank `RepositorySnapshot` and validates the SQLite projection before
activation. Missing, dirty, stale, and corrupt projections are reported without writes.
`repository.rebuildIndex` is the sole Studio open-time recovery path and performs the explicit
write before activation. `question.list` and
`question.search` use the verified SQLite projection; `question.get` uses that session
snapshot without rescanning all Markdown. Successful question writes refresh the
snapshot once. `repository.status` compares the current repository revision and
refreshes the snapshot when an external change is detected. No protocol field or
method changed incompatibly during the monorepo migration. Advanced-management additions remain
backward-compatible within Protocol 1.0: existing method names and payloads are
unchanged, and newer capabilities are advertised by `initialize.capabilities`.
