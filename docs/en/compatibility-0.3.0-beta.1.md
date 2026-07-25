# qbank 0.3.0-beta.1 compatibility matrix

[简体中文](../zh-CN/compatibility-0.3.0-beta.1.md) · [English documentation](README.md)

| Contract or entry point | Frozen value | Compatibility conclusion |
| --- | --- | --- |
| Product version | `0.3.0-beta.1` | Pre-release; unstable surfaces may be corrected in later betas |
| Python package | `0.3.0b1`, Python 3.11 | Shared by CLI, MCP, sidecar, and Legacy |
| Studio Protocol | `1.0` | Tauri Studio and sidecar retain v1 behavior |
| Question / Asset / Paper Schema | `1.0` | Independent from software version; no data migration |
| Authoritative data | Markdown | SQLite, previews, and exports are rebuildable |
| Default desktop entry | Tauri QBank Studio | Windows x64 installer and portable package |
| Fallback desktop entry | `qbank desktop` | QBank Studio Legacy for severe maintenance only |
| Codex | CLI, repository Skills, optional MCP | All reuse qbank application services |

`v0.2.0` remains an immutable baseline. The 0.3 beta neither moves the old tag, replaces its
artifacts, nor automatically changes a question bank.
