# qbank 0.3.0-beta.2 compatibility matrix

[简体中文](../zh-CN/compatibility-0.3.0-beta.2.md) · [English documentation](README.md)

| Contract or entry point | Frozen value | Compatibility conclusion |
| --- | --- | --- |
| Product version | `0.3.0-beta.2` | Pre-release; unstable surfaces may be corrected in later betas |
| Python package | `0.3.0b2`, Python 3.11 | Shared by CLI, MCP, sidecar, and Legacy |
| Studio Protocol | `1.0` | Tauri Studio and sidecar retain v1 behavior |
| Question / Asset / Paper Schema | `1.0` | Independent from software version; no data migration |
| Authoritative data | Markdown | SQLite, previews, and exports are rebuildable |
| Default desktop entry | Tauri QBank Studio | Windows x64 installer and portable package |
| Fallback desktop entry | `qbank desktop` | QBank Studio Legacy for severe maintenance only |
| Codex | CLI, repository Skills, optional MCP | All reuse qbank application services |

`v0.2.0` remains available as the previous release. The 0.3 beta neither changes that tag or its
artifacts nor automatically modifies a question bank.

This development line extends Studio Protocol `1.0` compatibly: `repository.open` and `asset.list`
only add fields, existing fields remain, and `repository.rebuildIndex` is advertised through
`initialize.capabilities`. Question Markdown, the SQLite format, and public Schemas do not change,
so no migration is required.
