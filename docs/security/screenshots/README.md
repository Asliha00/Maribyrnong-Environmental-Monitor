# Platform evidence screenshots

PLATFORM controls (BUILD_PROMPT §7) are proven with screenshots of the provider settings.
Name files `YYYY-MM-DD_<what>.png`. Check every screenshot for secrets before committing:
no connection strings, tokens, passwords or full API keys.

| File | Shows | SEC | Captured by |
|---|---|---|---|
| `2026-10-27_neon_data_api_disabled.png` | Neon → Settings → Postgres: Data API offers **"Enable Data API"**, so it is off | SEC-13 | TODO (team member) |
| `2026-10-27_neon_project_region_sydney.png` | Neon project `maribyrnong-db`: region **AWS Asia Pacific 2 (Sydney)**, Free plan | SEC-17 (data in Australia, APP 8) | TODO (team member) |
| `2026-10-27_vercel_blob_store_private.png` | Vercel Blob store `maribyrnong-raw`: **Private**, connected to project `maribyrnong-environmental-monitor` | SEC-15 | TODO (team member) |
| `2026-10-27_github_ci_green_3e65db9.png` | GitHub Actions `ci` run #41 on commit `3e65db9`: `backend` and `frontend` passed, Vitest 9/9 | Phase 0 "CI green", SEC-26 | TODO (team member) |
| `2026-10-28_github_security_green_36657ea.png` | GitHub Actions `security` run #46 (manual) on `36657ea`: gitleaks, dependency-audit and verify-database all passed (verify-database connects to live Neon from GitHub; the owner-only check is skipped there by design) | SEC-13/14/16/26 | TODO (team member) |
| `2026-10-28_neon_three_branches.png` | Neon branches: `main` (default, production), `dev` and `restore-scratch` (both from `main`) | SEC-30, SEC-18 | TODO (team member) |
| `2026-10-28_vercel_deployment_protection.png` | Vercel Authentication, Require Log In = on, **Standard Protection** (preview and generated deployment URLs need a Vercel login) | SEC-30 | TODO (team member) |
| `2026-10-28_vercel_env_var_scopes.png` | Environment variables with values masked: separate Preview and Production `APP_DATABASE_URL` / `ENVIRONMENT`; Neon owner variables (`DATABASE_URL_UNPOOLED`, `POSTGRES_*`) scoped to **Development only** | SEC-14, SEC-16, SEC-30 | TODO (team member) |
| `2026-10-28_ssl_labs_report.png` | Qualys SSL Labs for `maribyrnong-environmental-monitor.vercel.app` (2026-10-28 00:50 UTC, results hidden from public boards): grade **A+** on edge server 1, **A** on edge server 2 | SEC-01 | TODO (team member) |
| `2026-10-28_vercel_firewall_login_rule.png` | Vercel Firewall project rule "Login rate limit" (Rate Limit, 429), enabled; behaviour verified in `../firewall_login_rule_2026-10-28.md` | SEC-23 | TODO (team member) |
| `2026-10-28_prod_general_user_dashboard.png` | Production: `demo_user` (General User) signed in; Administration link not shown | SEC-10/11, UC1 | TODO (team member) |
| `2026-10-28_prod_admin_redirected_to_mfa.png` | Production: `demo_admin` signed in and sent straight to two-factor set-up (not enrolled, by design until Phase 8) | SEC-07, UC1 | TODO (team member) |
| `2026-10-28_preview_admin_after_mfa.png` | Preview (Neon `dev`): `demo_admin` after enrolling an authenticator app and verifying a code; dashboard reached with the Administration link. Database confirmed `mfa_enabled`, Fernet-encrypted secret, time step recorded; audit: login_success → mfa_setup_started → mfa_enabled | SEC-07, UC1 | TODO (team member) |

## Notes for readers of this evidence
- **General User screenshots are historical.** `2026-10-28_prod_general_user_dashboard.png` shows the
  former demo General User. That role was retired on 2026-11-03 (DECISIONS.md D-035) and the account
  deactivated. For the video and current evidence, use an Analyst for the "You do not have
  permission to access this page." moment.
- **"Branches: 1"** in the Neon project screenshot was captured before the `dev` and `restore-scratch`
  branches were created; `2026-10-28_neon_three_branches.png` shows all three.
- **"IP restrictions: None set"** is an accepted risk (DECISIONS.md D-022): the endpoint is reachable
  from the internet, but every connection needs a role password, TLS is enforced (plaintext refused,
  SEC-02) and each role is least-privilege (SEC-14).
- **SSL Labs grades differ by edge server** (A+ and A). Both are top grades; the servers are Vercel's
  (PLATFORM, SEC-01). Report the result as "A+ / A", not just A+.

## Still to capture
- [x] Neon project panel showing all three branches (retake)
- [x] Vercel → Settings → Deployment Protection (SEC-30)
- [x] Vercel → Settings → Environment Variables, showing scopes (names only, values hidden) (SEC-16/30)
- [x] SSL Labs report for the production domain (SEC-01)
- [ ] MFA enabled on each team member's Vercel, Neon and GitHub account (Essential Eight: MFA)
- [ ] GitHub branch protection / rulesets on `main`: **not available on the free plan for a private repo** (`../github_plan_limits_2026-10-28.md`, D-024); capture after a GitHub Pro upgrade (Student Developer Pack)
- [x] GitHub Actions: green `nightly-backup` run with artifact (SEC-18)
