# Vercel hello-world deployment check

Captured 2026-10-27T05:33:54Z against `https://maribyrnong-environmental-monitor.vercel.app` (commit `d85d010`) with curl. Raw output, unedited.

Stage: Phase 0 hello-world, `ENVIRONMENT=test` and no database connected yet (DECISIONS D-013).

## GET /api/health (response headers + body)
```
HTTP/1.1 200 OK
Cache-Control: private, no-store
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https://*.tile.openstreetmap.org; font-src 'self'; connect-src 'self' https://vercel.com/api/blob https://*.blob.vercel-storage.com; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'
Content-Type: application/json
Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()
Referrer-Policy: strict-origin-when-cross-origin
Server: Vercel
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-Request-Id: 7a26ad5b97194b4e9dbf39680f95353d
X-Vercel-Id: syd1::syd1::zc5zj-1793079233261-77a573987f71

{"status":"degraded","database":"unavailable"}

```

## GET / (frontend, response headers)
```
HTTP/1.1 200 OK
Access-Control-Allow-Origin: *
Cache-Control: public, max-age=0, must-revalidate
Content-Disposition: inline
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https://*.tile.openstreetmap.org; font-src 'self'; connect-src 'self' https://vercel.com/api/blob https://*.blob.vercel-storage.com; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'
Content-Type: text/html; charset=utf-8
Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()
Referrer-Policy: strict-origin-when-cross-origin
Server: Vercel
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-Vercel-Id: syd1::slrd4-1793079233437-7016bbe3b9a4

```

## Other checks
```
GET /insights (SPA deep link): 200
GET /api/nope: {"error":{"code":"http_404","message":"The requested resource was not found.","correlation_id":"6cf9c8900bf6444fb7592fc6e837b07a"}} [404]
Access-Control-Allow-Origin headers for Origin: https://evil.example -> 0
http:// -> 308 https://maribyrnong-environmental-monitor.vercel.app/
Generated deployment URL (Deployment Protection): 302 (302 = redirect to Vercel login)
```

Browser check (same day): `/insights` rendered, no console errors or CSP violations.
