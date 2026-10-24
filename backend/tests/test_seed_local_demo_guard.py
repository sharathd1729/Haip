"""The local demo seed must never run against a remote database or a non-development environment."""
import importlib.util
import os

import pytest

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "seed_local_demo.py")
_spec = importlib.util.spec_from_file_location("seed_local_demo", _PATH)
seed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed)


@pytest.mark.parametrize("url", [
    "postgresql://u:p@db.example.supabase.co:5432/postgres",
    "postgresql://u:p@10.0.0.5/haip",
    "postgresql://u:p@localhost.evil.com/haip",
    "",
])
def test_refuses_non_local_host(url):
    with pytest.raises(SystemExit):
        seed.assert_local_target(url, "development")


@pytest.mark.parametrize("env", ["production", "staging", ""])
def test_refuses_non_development_env(env):
    with pytest.raises(SystemExit):
        seed.assert_local_target("postgresql://haip:haip@127.0.0.1:55432/haip_local", env)


@pytest.mark.parametrize("url", [
    "postgresql://haip:haip@127.0.0.1:55432/haip_local",
    "postgresql+psycopg2://haip:haip@localhost/haip_local",
    "postgresql://haip:haip@[::1]:55432/haip_local",
])
def test_accepts_local_development(url):
    seed.assert_local_target(url, "development")
