"""scripts/create_app_db_role.py (workspace redesign Phase 0): dry run by default, never prints the password, refuses to
apply without the admin URL and a strong password, and the role it makes cannot bypass row-level security."""

import importlib.util
import pathlib

import pytest

_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "create_app_db_role.py"
spec = importlib.util.spec_from_file_location("create_app_db_role", _PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_dry_run_prints_a_restricted_role_and_changes_nothing(capsys, monkeypatch):
    monkeypatch.setenv("APP_DB_PASSWORD", "s3cret-password-never-shown")
    assert mod.main([]) == 0
    out = capsys.readouterr().out
    assert "NOBYPASSRLS" in out and "NOSUPERUSER" in out and "Dry run" in out
    assert "s3cret" not in out and "<APP_DB_PASSWORD>" in out
    assert "CREATE TABLE" not in out and "ALL PRIVILEGES" not in out


def test_apply_needs_admin_url_and_a_strong_password(monkeypatch):
    monkeypatch.delenv("ADMIN_DATABASE_URL", raising=False)
    monkeypatch.setenv("APP_DB_PASSWORD", "x" * 20)
    assert mod.main(["--apply"]) == 2
    monkeypatch.setenv("ADMIN_DATABASE_URL", "postgresql://owner@localhost/db")
    monkeypatch.setenv("APP_DB_PASSWORD", "short")
    assert mod.main(["--apply"]) == 2


def test_role_name_is_checked():
    with pytest.raises(SystemExit):
        mod.plan("haip; DROP TABLE x", "db", exists=False, reset_password=False)
    assert mod.plan("haip_app", "db", exists=True, reset_password=False)[0] == f"ALTER ROLE haip_app {mod.ATTRS}"
