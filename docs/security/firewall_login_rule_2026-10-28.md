# Vercel Firewall login rule (SEC-23 outer layer), 2026-10-28

Rule "Login rate limit" (Rate Limit, action 429), added by a team member in the Vercel dashboard:
`POST /api/auth/login`, fixed window 60 s, 10 requests per IP
(`screenshots/2026-10-28_vercel_firewall_login_rule.png`). It sits in front of the application's own
database-backed limit of 5 per minute per IP, so users normally see the app's message and the
firewall only stops floods before they reach the function or the database.

Probe from one IP against production, made-up account, 12 requests in a few seconds (raw output):

```
1: 401 application/json from=app
2: 401 application/json from=app
3: 401 application/json from=app
4: 401 application/json from=app
5: 401 application/json from=app
6: 429 application/json from=app
7: 429 application/json from=app
8: 429 application/json from=app
9: 429 application/json from=app
10: 429 application/json from=app
11: 429 application/json from=app X-Vercel-Mitigated: deny
12: 429 application/json from=app X-Vercel-Mitigated: deny
```

Requests 1-5: wrong credentials (401). 6-10: the application's rate limit (429, `rate_limited`).
From request 11: blocked at Vercel's edge (`X-Vercel-Mitigated: deny`) without reaching the app.
