# qbank 0.3.0-beta.1 已知限制

[English](../en/known-limitations-0.3.0-beta.1.md) · [中文文档](README.md)

- Windows Studio 制品尚未代码签名，SmartScreen 可能警告；必须核对 SHA-256。
- Studio 当前提供 Windows x64 安装器和便携包，需要可用的 Microsoft Edge WebView2。
- qbank 面向本机常规文件系统；网络盘、同步目录和多机共享写入不在安全承诺内。
- Pandoc、Ipe 和 Git 属于可选外部工具；缺失时对应 DOCX、Ipe 或版本控制能力降级。
- HTTP/HTTPS 图片允许但始终产生 warning，不会被 Studio 自动下载。
- 这是 beta，不承诺稳定的第三方 Python API；已记录 CLI、Markdown、Schema、Protocol 和
  JSON 字段仍按兼容策略处理。
- 不提供在线考试、账号、自动判题、OCR、模型托管或多人协同服务器。
