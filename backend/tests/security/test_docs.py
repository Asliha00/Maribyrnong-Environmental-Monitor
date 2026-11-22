"""SEC-22: /api/docs works under the strict CSP: no inline script, no third-party origin."""
import re


def test_docs_page_has_no_inline_or_external_scripts(client):
    r = client.get("/api/docs")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    scripts = re.findall(r"<script([^>]*)>(.*?)</script>", r.text, flags=re.S)
    assert scripts, "expected script tags"
    for attrs, body in scripts:
        assert 'src="/api/docs/static/' in attrs, f"non-local script: {attrs}"
        assert body.strip() == "", "inline script would be blocked by script-src 'self'"
    assert "http://" not in r.text and "https://" not in r.text, "no third-party origins"
    assert "script-src 'self'" in r.headers["content-security-policy"]


def test_docs_assets_served_same_origin(client):
    for name, kind in (("swagger-ui-bundle.js", "javascript"), ("swagger-ui.css", "css"), ("init.js", "javascript")):
        r = client.get(f"/api/docs/static/{name}")
        assert r.status_code == 200 and kind in r.headers["content-type"], name
        assert "content-security-policy" in r.headers


def test_docs_static_mount_does_not_serve_outside_its_folder(client):
    assert client.get("/api/docs/static/../../config.py").status_code == 404
    assert client.get("/api/docs/static/%2e%2e/%2e%2e/config.py").status_code == 404
