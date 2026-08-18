# Security

CLI package verification rejects path traversal, non-regular files, checksum mismatches,
and non-passing reports. The notes below apply to the optional HTTP API/bridge.


- Bearer auth via `LABELOS_API_TOKEN` / `LABELOS_BRIDGE_TOKEN`
- Constant-time token compare (`secrets.compare_digest`)
- No hardcoded credentials
- Path traversal checks on storage destinations and templates
- Sanitized SKU, revision, job id, template, and filenames
- Subprocess/COM calls use argument arrays / COM APIs — not shell-interpolated strings
- Existing package destinations are never overwritten
- Secrets are redacted from structured logs
- `/health` is public; all mutating/diagnostic routes require auth
