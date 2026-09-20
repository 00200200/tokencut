# Security Policy

## Reporting a Vulnerability
tokencut runs locally on your machine and never transmits token content, logs, or codebase files to external servers.

If you discover a security vulnerability (such as a flaw in API key redaction or SQLite cache isolation), please open a security advisory or reach out directly via GitHub.

## Secret Redaction
tokencut includes automatic pattern matching to mask credentials (OpenAI keys, Anthropic keys, Google Gemini keys, GitHub tokens, database connection strings). If you encounter an unmasked credential pattern, please submit a pull request or issue to expand `src/tokencut/core/redactor.py`.
