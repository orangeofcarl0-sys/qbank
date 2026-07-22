# Manual acceptance

1. Add a temporary ignored fixture containing a Windows absolute path and confirm a finding.
2. Add a fake token and confirm the report contains only a redacted fingerprint.
3. Add a `questions/2005-2022/` fixture and confirm it is HIGH.
4. Add an image/font without redistribution notes and confirm a license-risk finding.
5. Confirm README and every Skill contain no machine-specific path.
6. Compare wheel and sdist members with `distributable-files.txt`.
7. Run the audit twice and compare stable report fields.
8. Remove fixtures and confirm the repository itself was not modified by the audit outside
   `build/oss-audit/`.
