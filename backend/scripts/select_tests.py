"""Which tests should run for this change? Prints the commands; changes nothing, adds no dependency.

    python scripts/select_tests.py                  # uncommitted + untracked changes vs HEAD
    python scripts/select_tests.py --base master    # everything since master (committed + uncommitted)
    python scripts/select_tests.py --files app/services/leads_service.py frontend/src/components/x.tsx
    python scripts/select_tests.py --run            # also run the selected backend tests on SQLite

How a backend source file maps to tests (no test is guessed, every rule is visible in the output):
  1. a changed test file runs as is;
  2. every test file that IMPORTS the changed module (``from app.services import leads_service``, ``app.services.leads_service``);
  3. every test file whose name contains the module name (``test_leads_service*.py``).
Risky areas (migrations, models, auth, tenant context, RLS, audit) add the tenant-isolation and migration tests and say so.
A big or cross-cutting change prints "FULL SUITE" instead of a list: see the testing guide in CLAUDE.md.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
TESTS = BACKEND / "tests"

# Mirrors .github/workflows/tenant-isolation.yml: the files CI treats as the isolation gate.
ISOLATION = [
    "tests/test_cross_tenant_matrix.py", "tests/test_rls_postgres.py", "tests/test_audit_concurrency_postgres.py",
    "tests/test_call_score_status.py", "tests/test_migration_117_postgres.py", "tests/test_verify_rls_isolation.py",
]
RISKY = re.compile(r"(alembic/|app/models/|app/core/(security|database|audit)|api/v1/deps|authz_service|workspace_context|set_tenant_context|rls)", re.I)
CROSS_CUTTING = re.compile(r"(^backend/tests/conftest\.py|^backend/requirements|^backend/pytest\.ini|^backend/app/main\.py|^backend/app/core/config\.py|^backend/alembic/env\.py)")
FULL_SUITE_BACKEND_FILES = 25          # more changed backend source files than this = treat as cross-module


def git(*args: str) -> list[str]:
    out = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line.strip()]


def changed_files(base: str | None) -> list[str]:
    files = set(git("diff", "--name-only", base) if base else git("diff", "--name-only", "HEAD"))
    files |= set(git("diff", "--name-only", "--cached"))
    files |= set(git("ls-files", "--others", "--exclude-standard"))
    return sorted(f for f in files if not f.endswith((".pyc", ".db", ".log")) and "__pycache__" not in f)


def dotted(rel: str) -> str:
    return rel.removesuffix(".py").replace("/", ".")


def tests_for_module(rel: str, test_texts: dict[Path, str]) -> list[str]:
    """Test files that import or are named after backend/app/<rel>."""
    stem = Path(rel).stem
    if stem == "__init__":
        return []
    full = dotted(rel)                                  # app.services.leads_service
    pkg = full.rsplit(".", 1)[0]                        # app.services
    imp = re.compile(rf"(\b{re.escape(full)}\b|from\s+{re.escape(pkg)}\s+import\s+[^\n]*\b{re.escape(stem)}\b)")
    hits = []
    for path, text in test_texts.items():
        if imp.search(text) or stem in path.stem:
            hits.append(path.relative_to(BACKEND).as_posix())
    return sorted(hits)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", help="compare against this ref instead of HEAD (e.g. master)")
    ap.add_argument("--files", nargs="*", help="paths relative to the repo root or to backend/ (skips git)")
    ap.add_argument("--run", action="store_true", help="run the selected backend tests on SQLite")
    args = ap.parse_args()

    files = [f.replace("\\", "/") for f in (args.files if args.files is not None else changed_files(args.base))]
    files = [f if f.startswith(("backend/", "frontend/", "docs/", ".github/", "CLAUDE.md")) else f"backend/{f}" for f in files]
    if not files:
        print("No changes found: nothing to test.")
        return 0

    backend_src = [f for f in files if f.startswith("backend/app/") and f.endswith(".py")]
    backend_tests = [f for f in files if f.startswith("backend/tests/") and f.endswith(".py")]
    migrations = [f for f in files if f.startswith("backend/alembic/versions/")]
    frontend = [f for f in files if f.startswith("frontend/src/") and f.endswith((".ts", ".tsx", ".css"))]
    other_backend = [f for f in files if f.startswith("backend/") and f not in backend_src + backend_tests + migrations]
    docs_only = all(f.startswith("docs/") or f.endswith(".md") for f in files)

    print(f"Changed: {len(backend_src)} backend source, {len(backend_tests)} backend test, {len(migrations)} migration, {len(frontend)} frontend file(s)\n")
    if docs_only:
        print("Docs only: no tests.")
        return 0

    full_reasons = []
    if len(backend_src) > FULL_SUITE_BACKEND_FILES:
        full_reasons.append(f"{len(backend_src)} backend source files changed (more than {FULL_SUITE_BACKEND_FILES})")
    full_reasons += [f"cross-cutting file changed: {f}" for f in files if CROSS_CUTTING.search(f)]
    if len(migrations) > 1:
        full_reasons.append("more than one migration (or a migration merge)")

    commands: list[str] = []
    selected: list[str] = []
    if backend_src or backend_tests or migrations or other_backend:
        test_texts = {p: p.read_text(encoding="utf-8", errors="ignore") for p in TESTS.rglob("test_*.py")}
        selected = [t.removeprefix("backend/") for t in backend_tests]
        for f in backend_src:
            found = tests_for_module(f.removeprefix("backend/"), test_texts)
            shown = ", ".join(found[:6]) + (f" ... (+{len(found) - 6} more)" if len(found) > 6 else "")
            print(f"  {f}\n    -> {shown if found else 'NO TEST imports or is named after this module (read the code and add one)'}")
            selected += found
        risky = [f for f in files if RISKY.search(f)] + ([f"{m} (migration)" for m in migrations])
        if risky:
            print("\nRISK: database / migration / auth / tenant-isolation area touched:")
            for f in risky:
                print(f"  - {f}")
            selected += ISOLATION
        selected = sorted(set(selected))
        print(f"\nBackend tests selected: {len(selected)} file(s)")
        if selected:
            commands.append("cd backend && python -m pytest " + " ".join(selected) + " -q -p no:cacheprovider")
        if risky:
            commands.append("# then the same files on PostgreSQL (see CLAUDE.md, Testing): DATABASE_URL=postgresql://... REQUIRE_POSTGRES_TESTS=1 python -m pytest <same files> -q")
        if migrations:
            commands.append("cd backend && python -m alembic heads   # exactly one head; then upgrade a FRESH PostgreSQL database, downgrade one step, upgrade again")
    if frontend:
        commands.append("cd frontend && npx tsc --noEmit --skipLibCheck")
        commands.append("cd frontend && npx vitest related " + " ".join(f.removeprefix("frontend/") for f in frontend) + " --run   # related tests only")
        print(f"Frontend files changed: {len(frontend)}: type check + related vitest tests; then ONE browser check of the affected screen at the affected width.")
    if not backend_src and not backend_tests and not migrations and not other_backend:
        print("Backend untouched: do not run the backend suite.")

    if full_reasons:
        print("\nFULL SUITE RECOMMENDED:")
        for r in full_reasons:
            print(f"  - {r}")
        print("  Run SQLite and PostgreSQL ONE AFTER THE OTHER (never in parallel on a shared database file).")
    print("\nCommands:")
    for c in commands:
        print("  " + c)

    if args.run and selected:
        return subprocess.call([sys.executable, "-m", "pytest", *selected, "-q", "-p", "no:cacheprovider"], cwd=BACKEND)
    return 0


if __name__ == "__main__":
    sys.exit(main())
