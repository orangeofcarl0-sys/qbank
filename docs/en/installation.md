# qbank 0.3.0-beta.2 installation and upgrade

[简体中文](../zh-CN/installation.md) · [English documentation](README.md)

## Verify downloads

Download artifacts and `checksums.txt` from the same GitHub Release, then compare SHA-256:

```powershell
Get-FileHash .\qbank-0.3.0b2-py3-none-any.whl -Algorithm SHA256
Get-FileHash .\QBank-Studio-0.3.0-beta.2-x64-setup.exe -Algorithm SHA256
```

This beta is not code-signed and Windows SmartScreen may warn. Use only artifacts from this
repository's Release and do not install or run a file whose hash differs.

## CLI, Skills, and MCP

qbank requires Python 3.11:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install .\qbank-0.3.0b2-py3-none-any.whl
qbank --help
qbank schema --format json
```

MCP is optional. Install `qbank[mcp]` and follow the
[Codex and MCP guide](codex-integration.md) when project registration is required. Repository
Skills work independently and do not require a local Codex CLI.

## QBank Studio

- Installer: run `QBank-Studio-0.3.0-beta.2-x64-setup.exe` for a per-user installation.
- Portable: extract the complete ZIP and run `qbank-studio.exe`; do not copy only the executable.
- Legacy: install `qbank[desktop]` and run `qbank desktop`.

Modern Studio and Legacy use the same Markdown repository format and perform no data migration.
Back up the bank or place it under version control before first use.

## Upgrade from 0.2.0

Close every qbank and Studio process, install the new wheel or replace the complete portable
directory, then run:

```powershell
qbank doctor --format json
qbank validate --format json
qbank index rebuild --format json
```

Question, Asset, and Paper Schemas and Studio Protocol remain at `1.0`; valid 0.2.0 banks need no
migration. Remove the CLI by deleting its Python environment. Remove installed Studio through
Windows Installed Apps, or delete the portable directory. Neither method deletes question banks.
