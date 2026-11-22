# Self-hosted Swagger UI (API documentation at /api/docs)

- `swagger-ui-bundle.js`, `swagger-ui.css`: from the npm package `swagger-ui-dist` **5.33.2**
  (published 2026-10-12), copied unchanged. Licence: Apache-2.0 (`LICENSE.swagger-ui`).
- `init.js`: ours; starts the UI from an external file because the CSP forbids inline scripts.
- Why self-hosted: FastAPI's default docs page loads these files from a CDN and starts them with an
  inline script, both blocked by our CSP (`script-src 'self'`). DECISIONS.md D-030.
- To upgrade: `npm pack swagger-ui-dist@<version>`, copy the two files, update the version above.
