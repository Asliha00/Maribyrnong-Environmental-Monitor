"""SEC-13 intruder classification in database/verify_security.py (no database needed).

The live negative tests (a real intruder role, and a direct grant to neon_service,
each making verify_security.py FAIL) are recorded in docs/security/.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import verify_security as vs  # noqa: E402

OURS = {"neondb_owner", "app_user", "pipeline_user", "backup_user"}


def test_unknown_role_is_an_intruder():
    assert vs.find_intruders(["app_user", "intruder"], OURS, {"neon_service"}) == ["intruder"]


def test_neon_platform_roles_are_not_intruders():
    assert vs.find_intruders(["neon_superuser", "cloud_admin"], OURS, set()) == []


def test_neon_service_exempt_only_when_access_is_via_neon_superuser():
    # neon_service_roles_ok() returned it: member of neon_superuser, no direct grants
    assert vs.find_intruders(["neon_service"], OURS, {"neon_service"}) == []


def test_neon_service_with_direct_grant_is_an_intruder():
    # neon_service_roles_ok() withheld it (e.g. someone ran GRANT USAGE ON SCHEMA app TO neon_service)
    assert vs.find_intruders(["neon_service"], OURS, set()) == ["neon_service"]


def test_exemption_is_by_exact_name_only():
    assert vs.find_intruders(["neon_service_evil", "neon_superuser2"], OURS, {"neon_service"}) == [
        "neon_service_evil", "neon_superuser2"]


# ---------- app_user privilege matrix (D-033) ----------
def test_matching_grants_report_nothing():
    assert vs.grant_differences(dict(vs.APP_USER_GRANTS), vs.APP_USER_GRANTS) == []


def test_extra_grant_is_reported():
    actual = {**vs.APP_USER_GRANTS, "readings": {"SELECT", "INSERT", "DELETE"}}
    assert vs.grant_differences(actual, vs.APP_USER_GRANTS) == ["unexpected DELETE on readings"]


def test_missing_grant_is_reported():
    actual = {**vs.APP_USER_GRANTS, "ingestion_runs": {"SELECT"}}
    assert vs.grant_differences(actual, vs.APP_USER_GRANTS) == ["missing INSERT on ingestion_runs",
                                                                "missing UPDATE on ingestion_runs"]


def test_expected_matrix_matches_the_sql_file():
    """The expected matrix and 02_security.sql must not drift apart."""
    import re

    sql = (Path(__file__).resolve().parents[1] / "02_security.sql").read_text(encoding="utf-8")
    parsed: dict[str, set[str]] = {}
    for privs, tables in re.findall(r"^GRANT ([A-Z, ]+?)\s+ON ([a-z_, ]+?)\s+TO app_user;", sql, re.M):
        for table in (t.strip() for t in tables.split(",")):
            parsed.setdefault(table, set()).update(p.strip() for p in privs.split(","))
    assert parsed == vs.APP_USER_GRANTS
    assert "DELETE" not in parsed["readings"] and "UPDATE" not in parsed["readings"]
    assert "DELETE" not in parsed["ingestion_runs"] and "DELETE" not in parsed["sensor_variables"]


def test_column_update_grants_match_the_sql_file():
    """Column-level UPDATE grants (D-037) are checked separately from the table matrix."""
    import re

    sql = (Path(__file__).resolve().parents[1] / "02_security.sql").read_text(encoding="utf-8")
    parsed = {table: {c.strip() for c in cols.split(",")}
              for cols, table in re.findall(r"^GRANT UPDATE \(([a-z_, ]+)\)\s+ON ([a-z_]+)\s+TO app_user;", sql, re.M)}
    assert parsed == vs.APP_USER_COLUMN_UPDATES
    assert "code_hash" not in parsed["mfa_recovery_codes"]
