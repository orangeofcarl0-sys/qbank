# qbank 0.3.0-beta.2 安装与升级

[English](../en/installation.md) · [中文文档](README.md)

## 校验下载

从 GitHub Release 下载制品后，将 `checksums.txt` 放在同一目录并核对 SHA-256：

```powershell
Get-FileHash .\qbank-0.3.0b2-py3-none-any.whl -Algorithm SHA256
Get-FileHash .\QBank-Studio-0.3.0-beta.2-x64-setup.exe -Algorithm SHA256
```

本 beta 尚未代码签名，Windows SmartScreen 可能警告。只使用本仓库 Release 中的制品；
哈希不一致时不要安装或运行。

## CLI、Skill 与 MCP

qbank 需要 Python 3.11：

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install .\qbank-0.3.0b2-py3-none-any.whl
qbank --help
qbank schema --format json
```

MCP 是可选组件。需要时安装 `qbank[mcp]`，再按
[Codex 与 MCP 接入](codex-integration.md)注册项目服务。仓库 Skill 可独立使用，不要求
本机存在 Codex CLI。

## QBank Studio

- 安装器：运行 `QBank-Studio-0.3.0-beta.2-x64-setup.exe`，按当前用户安装。
- 便携包：解压整个 ZIP 后运行 `qbank-studio.exe`，不要只复制主程序。
- Legacy：安装 `qbank[desktop]` 后运行 `qbank desktop`。

现代 Studio 与 Legacy 使用同一 Markdown 题库格式，不执行数据迁移。首次使用前建议备份
题库或置于版本控制中。

## 从 0.2.0 升级

退出所有 qbank/Studio 进程，安装新 wheel 或替换完整便携目录，然后运行：

```powershell
qbank doctor --format json
qbank validate --format json
qbank index rebuild --format json
```

Question、Asset、Paper Schema 和 Studio Protocol 均保持 `1.0`，合法的 0.2.0 题库无需迁移。
卸载 CLI 时删除对应 Python 环境；卸载 Studio 安装版使用 Windows“已安装的应用”，便携版
删除解压目录即可。题库目录不会被自动删除。
