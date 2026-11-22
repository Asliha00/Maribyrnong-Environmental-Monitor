"""Repository configuration that CI cannot afford to get wrong.

A workflow file with invalid YAML does not run at all: GitHub only shows a failed run
per push, and scheduled jobs (nightly backup) silently stop. Caught on 2026-10-27
(DECISIONS.md D-020).
"""
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_is_valid_yaml_with_jobs(path):
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(doc, dict) and doc.get("jobs"), f"{path.name} has no jobs"
    assert "name" in doc, f"{path.name} needs a name (GitHub shows the file path when parsing fails)"


def test_backup_and_restore_workflows_exist():
    names = {p.name for p in WORKFLOWS}
    assert {"nightly-backup.yml", "restore-test.yml", "ci.yml", "security.yml"} <= names


def test_dependabot_config_is_valid_yaml():
    assert yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))["updates"]


def test_vercel_json_is_valid():
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    assert config["regions"] == ["syd1"]
    assert {"web", "api"} <= set(config["services"])


def _csp_allows(source: str, url: str) -> bool:
    """CSP host-source matching for an https URL (scheme + host + path): a source path that
    ends in "/" matches as a prefix, otherwise it must match the URL's path exactly."""
    from urllib.parse import urlparse

    s, u = urlparse(source), urlparse(url)
    if (s.scheme, s.hostname) != (u.scheme, u.hostname):
        return False
    if not s.path:
        return True
    return u.path.startswith(s.path) if s.path.endswith("/") else u.path == s.path


def test_csp_allows_the_blob_upload_urls():
    """The admin upload sends the file from the browser to Vercel Blob's API. A source without
    a trailing slash ('https://vercel.com/api/blob') matches only that exact path, so the real
    upload URLs were blocked and the upload hung at 0% (2026-10-31)."""
    import json

    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    csp = next(h["value"] for rule in config["headers"] for h in rule["headers"]
               if h["key"] == "Content-Security-Policy")
    sources = next(d for d in csp.split(";") if d.strip().startswith("connect-src")).split()[1:]
    for url in ("https://vercel.com/api/blob/?pathname=uploads%2Fx.csv",       # single PUT
                "https://vercel.com/api/blob/mpu?pathname=uploads%2Fx.csv"):    # multipart (large files)
        assert any(_csp_allows(s, url) for s in sources), url
    assert not any(_csp_allows(s, "https://vercel.com/account") for s in sources)   # not all of vercel.com
