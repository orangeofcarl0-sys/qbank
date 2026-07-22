# Open-source audit policy

## Severity

- CRITICAL: likely live credential, private key, authentication token, or secret in current files
  or Git history.
- HIGH: real question bank/exam material, personal data, private repository endpoint, distributable
  file with no redistribution basis, or release archive containing excluded data.
- MEDIUM: local absolute path, private network address, email, machine-specific tool path, binary
  metadata, unclear dependency license, logs, caches, databases, or build output.
- LOW: hygiene improvement that does not itself disclose private data.

Only CRITICAL/HIGH findings block GREEN. A failed required scan also blocks. Optional tool absence
must appear as a warning and lowers confidence.

## qbank exclusions

Treat these as presumptively private unless they are clearly synthetic and redistributable:

- real `questions/` trees and exam archives, especially material dated 2005 through 2022;
- answer keys, integration-pilot data, imported user libraries, SQLite indexes, histories and logs;
- screenshots containing questions, personal directories, or proprietary application chrome;
- local Ipe, Pandoc, Codex, Python, or editor installation paths;
- fonts, images, PDFs, and datasets without an explicit redistribution basis.

The public example must be small, fully authored for qbank, and contain no extracted exam text.

## Evidence handling

Never store the matched secret. Store category, file/commit location, line number when safe, a
short non-sensitive description, and a one-way SHA-256 fingerprint. Keep tool raw reports out of
the release archive.
