# Preview environment separation (SEC-30), 2026-10-27

Preview deployments use the Neon **dev** branch (endpoint `ep-withered-shadow-a7j9ipg3`); Production uses **main**
(`ep-misty-resonance-a708y9zl`). Endpoint IDs are not secrets. Raw output below, unedited.

## Branches are separate copies
```
main: timeline=4307bd89719c5676b45c69006307cf4f endpoint=ep-misty-resonance-a708y9zl readings=192256 rls_tables=15 roles=['app_user', 'backup_user', 'neon_service', 'pipeline_user']
dev: timeline=dc6b7f864d62500ba9d066610505723f endpoint=ep-withered-shadow-a7j9ipg3 readings=192256 rls_tables=15 roles=['app_user', 'backup_user', 'neon_service', 'pipeline_user']
```

## Each branch has its own application credentials
The dev branch's `app_user`, `pipeline_user` and `backup_user` were given new random passwords after branching.
```
dev app_user  -> dev : login OK
prod app_user -> prod: login OK
prod app_user -> dev : refused (password authentication failed)
dev app_user  -> prod: refused (password authentication failed)
```

## Security verification on the dev branch
`verify_security.py`: **30 passed, 0 failed, 0 skipped** (`database_verification_dev_branch.md`).

## Vercel environment variables (names and scopes only)
| Variable | Production | Preview |
|---|---|---|
| `APP_DATABASE_URL` | app_user @ main pooled (Sensitive) | app_user @ dev pooled (Sensitive) |
| `ENVIRONMENT` | `production` | `production` |
| `JWT_SECRET`, `MFA_ENCRYPTION_KEY` | own values (Sensitive) | different values (Sensitive) |
| Neon owner URLs (`DATABASE_URL`, `PG*`, …) | absent | absent (Development only) |

## Preview deployment check
```
Preview https://maribyrnong-environmental-monitor-jo868w43k-asli6.vercel.app
anonymous GET /api/health: 302            (Deployment Protection: redirect to Vercel login)
vercel curl /api/health (authenticated bypass):
HTTP/1.1 200 OK
X-Vercel-Id: syd1::syd1::mxbz6-1793084373045-0a78b489c5fe
{"status":"ok","database":"ok"}
```
Production at the same time: `{"status":"ok","database":"ok"}`.
