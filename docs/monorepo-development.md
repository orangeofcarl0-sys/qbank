# qbank 单仓库开发指南

## 目录与职责

```text
qbank/
├─ src/qbank/
│  ├─ application/       # 用例和端口
│  ├─ domain/            # 领域契约
│  ├─ infrastructure/    # Markdown、SQLite、Ipe 等适配器
│  ├─ commands/          # CLI presentation
│  ├─ mcp/               # MCP presentation
│  ├─ studio_sidecar/    # Studio Protocol 本地适配器
│  └─ legacy_qt/         # QBank Studio Legacy
├─ apps/studio/
│  ├─ src/               # Tauri WebView presentation
│  ├─ src-tauri/         # Rust 壳、权限和安装配置
│  └─ tests/             # TypeScript 与浏览器测试
├─ protocol/             # Studio Protocol v1
├─ scripts/
│  ├─ check.py
│  ├─ build.py
│  └─ change-impact.json
└─ docs/
```

现代 Studio、CLI、MCP、Codex Skill 和 Qt Legacy 是同一 qbank 产品的不同入口。
`qbank.studio_sidecar` 只把 Protocol 请求转换为 qbank application service 调用，不拥有
Question、Paper、Schema、项目锁、事务、历史或索引实现。

## 统一版本

- Python 包版本：`0.3.0b1`
- 对外产品版本：`0.3.0-beta.1`
- Studio Protocol：`1.0`
- Question、Asset、Paper Schema：`1.0`
- 上一发布线：`v0.2.0`；已发布 tag 保持对应原发布提交

Python wheel、Studio 安装器和便携包必须由同一干净 Git 提交生成。生成的 manifest 记录
提交、依赖锁哈希和各制品 SHA-256。

## 三级检查

### fast

```powershell
python scripts/check.py fast
```

读取工作区改动并按 `scripts/change-impact.json` 选择受影响的 Python、Qt Legacy、
sidecar、Protocol、Studio、构建或文档单元。普通修改默认只运行这一层；也可用
`--scope studio` 等参数显式限定。

### integration

```powershell
python scripts/check.py integration
```

只在 Protocol、sidecar、权威写入、Vditor、MathJax、Tauri 权限或安装边界改变时运行。
Studio integration 包含前端构建、Protocol/sidecar 合同、Rust 开发检查和一条
打开—编辑—保存—公式预览—图片操作 smoke。

### release

```powershell
python scripts/check.py release
```

只用于版本冻结和正式发布，包括全量测试、安装验收、安全审计、真实 UAT 和制品检查。
普通实现细节调整不得无理由重跑发布级证据。

## 变更影响与证据复用

`scripts/change-impact.json` 是检查范围的权威映射。发布证据只有在 Git commit、Python
依赖锁、Node 依赖锁、Cargo 依赖锁和 artifact SHA-256 全部匹配时才可复用；任一绑定
变化都需要重建对应证据。行为未变化且绑定仍有效时，不重复生成万题基准、完整 UAT 或
安装矩阵。

## 统一构建

```powershell
python scripts/build.py wheel
python scripts/build.py studio
python scripts/build.py all
```

`wheel` 生成 Python wheel；`studio` 先从同一 wheel 构建固定 sidecar，再生成 Tauri
安装器和便携包；`all` 生成全部制品。默认拒绝从脏工作区执行可复现构建。输出位于
`build/unified/`，不进入源码包。

Windows Studio 构建默认使用官方 MSVC Rust target，并要求已安装 Visual Studio Build
Tools 与 Windows SDK。构建脚本不会为检测目的自动安装备用工具链；确有交叉目标需求时，
由维护者通过 `--target` 或 `QBANK_STUDIO_RUST_TARGET` 明确选择并预先准备工具链。

项目不使用 Nx、Turborepo 或后台构建服务。Node、Cargo 和 Python 仍使用各自原生锁文件。

## Qt Legacy 维护边界

`qbank desktop` 启动 QBank Studio Legacy。Legacy 与现代 Studio 使用相同题库格式和
application services，但只接受数据损坏、安全或严重兼容性修复。新交互默认进入现代
Studio，不对题库执行不可逆迁移。
