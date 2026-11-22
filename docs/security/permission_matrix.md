# Permission matrix (SEC-11, proposal risk R19)

Source of truth: `roles.permissions` in `database/01_schema.sql`. Enforced by
`require_permission(...)` in `backend/app/security.py` (proposal Algorithm 4).
Tested by `backend/tests/security/test_rbac.py`: **keep this file in sync with `MATRIX` there.**

## Roles → permissions

Two roles, the two actors of the proposal's use cases (DECISIONS.md D-035). The header shows
them as "Analyst" and "Administrator".

| Permission | Environmental Analyst | System Administrator |
|---|:-:|:-:|
| `view_data` | ✓ | ✓ |
| `filter_data` | ✓ | ✓ |
| `export_data` | ✓ | ✓ |
| `view_quality` | ✓ | ✓ |
| `manage_sensors` | | ✓ (with MFA) |
| `manage_users` | | ✓ (with MFA) |
| `manage_thresholds` | | ✓ (with MFA) |

Role 1 "General User" is **retired**. Its row stays in `roles` because old user records and
audit entries refer to it, but the API refuses it for new accounts and role changes (422,
`test_admin_users.py::test_retired_general_user_role_cannot_be_given`). The one account that
held it, the demo account, is deactivated, never deleted (SEC-12).

"With MFA": every `manage_*` permission also needs a session that passed TOTP
verification (SEC-07). An administrator without MFA gets 403 `mfa_required`.

## Endpoints → required permission

| Endpoint | Permission | Notes |
|---|---|---|
| `GET /api/health` | public | uptime check |
| `POST /api/auth/login` | public | rate limited 5/min/IP |
| `POST /api/auth/refresh` | public | authenticated by the refresh-token cookie; CSRF required |
| `POST /api/auth/logout` | public | only revokes the caller's own tokens; CSRF required |
| `GET /api/me` | any signed-in user | also allowed while a password change is pending |
| `POST /api/auth/change-password` | any signed-in user | also allowed while a password change is pending |
| `POST /api/auth/mfa/setup`, `/mfa/verify` | any signed-in user | |
| `POST /api/auth/mfa/recovery` | any signed-in user with 2FA set up | a single-use recovery code instead of the authenticator code (D-037); shares the 5/min/user 2FA limit; audited |
| `GET/POST /api/auth/mfa/recovery-codes` | signed-in user whose session passed 2FA | count of unused codes / a new set (cancels the old); never returns stored codes |
| `GET /api/auth/check?permission=` | any signed-in user | 200 or 403 for the named permission |
| `GET /api/meta` | `view_data` | filter-panel options |
| `GET /api/sensors`, `GET /api/sensors/{id}` | `view_data` | rate limited 120/min/user |
| `GET /api/readings` | `filter_data` | audited (`data_query`); rate limited 120/min/user |
| `GET /api/exceedances` | `view_data` | audited (`data_query`); rate limited 120/min/user |
| `GET /api/heatmap` | `filter_data` | hour-of-day × month grid; audited; rate limited 120/min/user |
| `POST /api/reports/export` | `export_data` | CSV/PDF (UC3); CSRF required; logged to `reports` + audit (`report_export`, `report_export_failed`); rate limited 10/min/user |
| `GET/POST /api/admin/sensors`, `PUT/DELETE /api/admin/sensors/{id}`, `POST …/{id}/device-key` | `manage_sensors` + MFA | UC5; audited; CSRF on writes; rate limited 60/min/admin |
| `GET/POST /api/admin/users`, `PUT /api/admin/users/{id}`, `POST …/{id}/reset-password`, `…/reset-mfa` | `manage_users` + MFA | no changes to one's own access; access changes sign the user out everywhere |
| `GET /api/admin/thresholds`, `PUT /api/admin/thresholds/{id}` | `manage_thresholds` + MFA | reason required; append-only history; exceedances recomputed |
| `POST /api/admin/ingest-upload` | `manage_sensors` + MFA | SEC-20 checks; 5 per 10 min per admin |
| `POST /api/blob-upload` (Node service) | `manage_sensors` + MFA, via `check` | presigned private upload, CSV only, 50 MB, 10 min (SEC-15) |
| `GET /api/quality/{completeness,errors,runs,flags}` | `view_quality` | data-quality page |
| `GET /api/quality/security` | `manage_users` + MFA | suspicious-login entries (SEC-27) |
| `GET /api/analysis/{summary,trends,diurnal,green-infrastructure,disparities,recommendations}` | `view_data` | Insights (Phase 6); one cached computation; rate limited 120/min/user |
| `POST /api/ingest` | device key (not a user) | live readings (SEC-03); CSRF-exempt; failures audited with IP and rate limited |

## Tested matrix (expected HTTP status)

| Request | anonymous | Analyst | Admin (no MFA) | Admin + MFA |
|---|:-:|:-:|:-:|:-:|
| `GET /api/me` | 401 | 200 | 200 | 200 |
| `check?permission=view_data` | 401 | 200 | 200 | 200 |
| `check?permission=export_data` | 401 | 200 | 200 | 200 |
| `check?permission=view_quality` | 401 | 200 | 200 | 200 |
| `check?permission=manage_sensors` | 401 | 403 | 403 | 200 |
| `check?permission=manage_users` | 401 | 403 | 403 | 200 |
| `check?permission=manage_thresholds` | 401 | 403 | 403 | 200 |
| `GET /api/meta`, `/api/sensors`, `/api/sensors/1` | 401 | 200 | 200 | 200 |
| `GET /api/readings?…` | 401 | 200 | 200 | 200 |
| `GET /api/exceedances` | 401 | 200 | 200 | 200 |
| `GET /api/heatmap?…` | 401 | 200 | 200 | 200 |
| `POST /api/reports/export` | 401 | 200 | 200 | 200¹ |
| `GET /api/admin/sensors`, `/api/admin/users`, `/api/admin/thresholds` | 401 | 403 | 403 | 200 |
| Admin writes (sensor register/edit/decommission/key, user create, threshold edit, ingest-upload)² | 401 | 403 | 403 | 200 |
| `GET /api/quality/completeness`, `/errors`, `/runs`, `/flags` | 401 | 200 | 200 | 200 |
| `GET /api/quality/security` | 401 | 403 | 403 | 200 |
| `GET /api/analysis/*` (all six) | 401 | 200 | 200 | 200 |

¹ The POST is tested separately in `backend/tests/test_export.py` (analyst, admin without MFA; a role whose permissions lack `export_data` gets 403); the administrator holds `export_data` with or without MFA.

² `test_admin_writes_are_refused_below_admin_with_mfa` sends each write with a valid body and checks that
nothing in the database changed; the successful admin+MFA cases are in `test_admin_*.py`.
`POST /api/ingest` is outside the user matrix: devices authenticate with their own key
(`backend/tests/security/test_ingest_security.py`).

Also tested: every route outside the public allow-list declares a guard
(`test_every_route_is_protected`), with a negative test proving an unguarded route
is detected. An Analyst cannot escalate their own role via `PUT /api/admin/users/{self}`
(`test_admin_users.py::test_analyst_cannot_escalate_their_own_role`). A deactivated account of
either role is refused at login with "Your account has been deactivated. Please contact your
administrator." and gets no session (`test_rbac.py::test_deactivated_account_cannot_log_in`,
`test_auth.py::test_deactivated_account_message`, and in the browser
`e2e/login.spec.ts`).
