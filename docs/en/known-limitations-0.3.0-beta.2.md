# qbank 0.3.0-beta.2 known limitations

[简体中文](../zh-CN/known-limitations-0.3.0-beta.2.md) · [English documentation](README.md)

- Windows Studio artifacts are not code-signed; SmartScreen may warn and SHA-256 verification is
  required.
- Studio currently ships for Windows x64 and requires a usable Microsoft Edge WebView2 runtime.
- The portable archive's text README retains legacy “alpha” wording. The executable, manifest,
  artifact names, and Python package metadata correctly identify `0.3.0-beta.2`.
- The current safe-preview policy may replace some declared local SVG files with a placeholder.
  Asset mutation, capability checks, and browser-rendering smoke remain unaffected.
- qbank targets ordinary local filesystems. Network shares, synchronized folders, and multi-host
  concurrent writes are outside its safety guarantee.
- Pandoc, Ipe, and Git are optional external tools. DOCX, Ipe, or version-control capabilities
  degrade when the corresponding tool is absent.
- HTTP/HTTPS images remain allowed with warnings and Studio does not download them automatically.
- This is a beta and does not promise a stable third-party Python API. Documented CLI, Markdown,
  Schema, Protocol, and JSON fields follow the compatibility policy.
- Online exams, accounts, automatic grading, OCR, hosted models, and a collaboration server are
  outside the product scope.
