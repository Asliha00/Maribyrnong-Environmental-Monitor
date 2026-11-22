// Starts Swagger UI for /api/docs. Kept as a separate file (not an inline <script>) so the
// page works under the site's Content-Security-Policy "script-src 'self'" (SEC-22).
window.addEventListener("load", function () {
  window.ui = SwaggerUIBundle({
    url: "/api/openapi.json",
    dom_id: "#swagger-ui",
    deepLinking: true,
    tryItOutEnabled: false,
  });
});
