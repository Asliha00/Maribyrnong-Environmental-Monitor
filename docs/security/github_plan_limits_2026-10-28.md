# GitHub plan limits on this private repository (SEC-16, SEC-30), 2026-10-28

Checked with the GitHub CLI (authenticated as the repository owner). Raw output:

```
$ gh api repos/Asliha00/Maribyrnong-Environmental-Monitor/branches/main/protection
{"message":"Upgrade to GitHub Pro or make this repository public to enable this feature.","status":"403"}

$ gh api repos/Asliha00/Maribyrnong-Environmental-Monitor --jq '...security_and_analysis...'
private=true secret_scanning=n/a push_protection=n/a
```

| Control (BUILD_PROMPT) | Available now? | Compensating control in place |
|---|---|---|
| Branch protection on `main`, required CI checks (SEC-30) | No (needs GitHub Pro for a private repo) | `ci` and `security` run on every push; Vercel deploys production from `main`, and every deployment is visible and reversible (instant rollback) |
| GitHub secret scanning + push protection (SEC-16) | No (not offered for this private repo on this plan) | `gitleaks` scans the full git history on every push (`security.yml`); `.gitleaksignore` holds reviewed false positives only (D-023) |

Making the repository public is not acceptable (council project). GitHub Pro is free with the
GitHub Student Developer Pack; see DECISIONS.md D-024.
