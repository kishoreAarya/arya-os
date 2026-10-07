"""Phase 54B-I1 — publication-manifest migration tests.

Two layers:

1. STATIC (always runs, no database): AST-level checks that the new
   migration is additive-only in upgrade(), touches only Phase 54B-I1
   objects in downgrade(), and chains onto the real current head.

2. LIVE (opt-in only): applies the full Alembic chain to a brand-new
   EPHEMERAL database on the configured server, asserts the resulting
   schema, then drops the ephemeral database. Never runs against the
   configured application database itself; skipped unless
   ARYA_I1_LIVE_MIGRATION_TEST=1 — an uncertain or production database
   must never be migrated from a test.
"""

import ast
import importlib.util
import os
from pathlib import Path

import pytest

_MIGRATION_FILE = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "a7b8c9d0e1f2_add_publication_manifests.py"
)
_PARENT_REVISION = "f6a7b8c9d0e1"
_REVISION = "a7b8c9d0e1f2"

_NEW_TABLE = "publication_manifests"
_NEW_COLUMNS = {
    "approval_checkpoints": ("publication_manifest_id",),
    "publication_attempts": ("manifest_id", "manifest_digest"),
}
_PRE_54B_TABLES = (
    "workflow_runs",
    "videos",
    "approval_checkpoints",
    "approval_decisions",
    "approval_ttl_policies",
    "publication_attempts",
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("i1_migration", _MIGRATION_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _op_calls(function_node):
    """Yield ('create_table', args...) style tuples for every alembic
    `op.<name>(...)` call inside a function, in source order."""
    for node in ast.walk(function_node):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "op"
        ):
            first_arg = None
            if node.args and isinstance(node.args[0], ast.Constant):
                first_arg = node.args[0].value
            yield func.attr, first_arg


# ---------------------------------------------------------------------------
# Static structure checks (no database)
# ---------------------------------------------------------------------------


def test_migration_file_exists_and_chains_onto_current_head():
    assert _MIGRATION_FILE.exists(), f"missing migration file: {_MIGRATION_FILE}"
    module = _load_migration()
    assert module.revision == _REVISION
    assert module.down_revision == _PARENT_REVISION
    # The parent must be the actual current head of the versions tree.
    versions_dir = _MIGRATION_FILE.parent
    child_revisions = set()
    for path in versions_dir.glob("*.py"):
        if path == _MIGRATION_FILE:
            continue
        src = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(src):
            # Both `revision = "x"` (ast.Assign) and the annotated
            # `revision: str = "x"` (ast.AnnAssign) forms.
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.FunctionDef):
                continue
            if (
                not targets
                and isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
            ):
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id == "revision":
                    value = getattr(node, "value", None)
                    if isinstance(value, ast.Constant):
                        child_revisions.add(value.value)
    assert (
        module.down_revision in child_revisions
    ), "down_revision is not a known revision — the chain is broken"
    # Nothing else builds on this new revision yet (linear chain).
    assert _REVISION not in child_revisions


def test_upgrade_is_additive_only():
    src = ast.parse(_MIGRATION_FILE.read_text(encoding="utf-8"))
    upgrade = next(
        n for n in src.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade"
    )
    calls = list(_op_calls(upgrade))
    created_tables = {arg for name, arg in calls if name == "create_table"}
    assert created_tables == {_NEW_TABLE}, "upgrade must create exactly the new table"
    for name, _arg in calls:
        assert not name.startswith("drop"), "upgrade() must not drop anything"
        assert name not in {
            "alter_column",
            "rename_table",
        }, f"upgrade() uses a non-additive op: {name!r}"


def test_upgrade_adds_the_approved_columns_and_constraints():
    src = ast.parse(_MIGRATION_FILE.read_text(encoding="utf-8"))
    upgrade = next(
        n for n in src.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade"
    )
    calls = list(_op_calls(upgrade))
    add_column_tables = [arg for name, arg in calls if name == "add_column"]
    expected_columns = [c for cols in _NEW_COLUMNS.values() for c in cols]
    assert sorted(add_column_tables) == sorted(
        [t for t, cols in _NEW_COLUMNS.items() for _ in cols]
    )
    assert len(add_column_tables) == len(expected_columns)
    create_fk = [arg for name, arg in calls if name == "create_foreign_key"]
    assert len(create_fk) == 2, "both nullable FK bindings must be created"


def test_downgrade_touches_only_phase_i1_objects():
    src = ast.parse(_MIGRATION_FILE.read_text(encoding="utf-8"))
    downgrade = next(
        n for n in src.body if isinstance(n, ast.FunctionDef) and n.name == "downgrade"
    )
    calls = list(_op_calls(downgrade))
    dropped_tables = {arg for name, arg in calls if name == "drop_table"}
    assert dropped_tables == {_NEW_TABLE}, "downgrade must drop only the new table"
    for name, arg in calls:
        if name == "drop_column":
            assert arg in _NEW_COLUMNS, f"downgrade drops a non-I1 column on {arg}"


# ---------------------------------------------------------------------------
# Live ephemeral-database check (opt-in)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_migration_additive_schema_on_ephemeral_database():
    if os.environ.get("ARYA_I1_LIVE_MIGRATION_TEST") != "1":
        pytest.skip(
            "live migration check is opt-in (ARYA_I1_LIVE_MIGRATION_TEST=1) — "
            "never migrate an unverified database from a test"
        )

    import subprocess
    import sys
    import uuid as uuid_mod
    from urllib.parse import quote, unquote, urlparse

    import asyncpg
    from app.core.config import get_settings
    from sqlalchemy import inspect
    from sqlalchemy.ext.asyncio import create_async_engine

    # NOTE: SQLAlchemy's str(URL) MASKS the password ('***'), so both the
    # asyncpg admin DSN and the subprocess env URL are rebuilt with
    # urllib (parse once, re-quote properly). Never printed.
    parsed = urlparse(
        get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    )
    _user = quote(unquote(parsed.username or ""), safe="")
    _password = quote(unquote(parsed.password or ""), safe="")
    _host = parsed.hostname or "localhost"
    _port = parsed.port or 5432
    admin_dsn = f"postgresql://{_user}:{_password}@{_host}:{_port}/postgres"
    ephemeral_name = f"arya_i1_migration_test_{uuid_mod.uuid4().hex[:8]}"
    repo_root = _MIGRATION_FILE.parents[2]

    async def _admin_execute(sql: str) -> None:
        conn = await asyncpg.connect(dsn=admin_dsn)
        try:
            await conn.execute(sql)
        finally:
            await conn.close()

    try:
        await _admin_execute(f'CREATE DATABASE "{ephemeral_name}"')
    except Exception as exc:  # noqa: BLE001 — insufficient CREATEDB privilege etc.
        pytest.skip(
            f"cannot create the ephemeral database on the configured server: {exc}"
        )

    ephemeral_url = (
        f"postgresql+asyncpg://{_user}:{_password}@{_host}:{_port}/{ephemeral_name}"
    )
    env = dict(os.environ)
    env["DATABASE_URL"] = ephemeral_url  # never printed

    def _alembic(*args: str):
        # python -m alembic: independent of the ambient PATH. check is
        # False by intent: returncode is asserted by the caller per step.
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )

    try:
        upgraded = _alembic("upgrade", "head")
        assert upgraded.returncode == 0, (
            f"alembic upgrade head failed on the ephemeral database "
            f"(stderr tail: {upgraded.stderr[-400:]})"
        )

        check_engine = create_async_engine(ephemeral_url)
        try:
            async with check_engine.connect() as conn:

                def _inspect(sync_conn):
                    insp = inspect(sync_conn)
                    return (
                        set(insp.get_table_names()),
                        {
                            c["name"]: c["nullable"]
                            for c in insp.get_columns(_NEW_TABLE)
                        },
                        {
                            c["name"]: c["nullable"]
                            for c in insp.get_columns("approval_checkpoints")
                        },
                        {
                            c["name"]: c["nullable"]
                            for c in insp.get_columns("publication_attempts")
                        },
                        {u["name"] for u in insp.get_unique_constraints(_NEW_TABLE)},
                        {
                            fk["referred_table"]
                            for fk in insp.get_foreign_keys(_NEW_TABLE)
                        },
                    )

                (
                    tables,
                    manifest_nullable,
                    checkpoint_nullable,
                    attempt_nullable,
                    unique_names,
                    manifest_fks,
                ) = await conn.run_sync(_inspect)

            for table in _PRE_54B_TABLES:
                assert (
                    table in tables
                ), f"pre-existing table missing after upgrade: {table}"
            assert _NEW_TABLE in tables

            assert set(manifest_nullable) == {
                "id",
                "schema_version",
                "workflow_run_id",
                "video_id",
                "canonical_bytes",
                "manifest_digest",
                "video_storage_path",
                "video_sha256",
                "video_size_bytes",
                "thumbnail_storage_path",
                "thumbnail_sha256",
                "thumbnail_size_bytes",
                "created_at",
                "updated_at",
            }
            for optional in (
                "thumbnail_storage_path",
                "thumbnail_sha256",
                "thumbnail_size_bytes",
            ):
                assert manifest_nullable[optional] is True

            assert "publication_manifest_id" in checkpoint_nullable
            assert checkpoint_nullable["publication_manifest_id"] is True
            assert attempt_nullable.get("manifest_id") is True
            assert attempt_nullable.get("manifest_digest") is True
            assert "uq_publication_manifests_digest" in unique_names
            assert {"workflow_runs", "videos"} <= manifest_fks

            # Round-trip downgrade -> upgrade on the EPHEMERAL database only.
            downgraded = _alembic("downgrade", _PARENT_REVISION)
            assert downgraded.returncode == 0, (
                f"alembic downgrade failed on the ephemeral database "
                f"(stderr tail: {downgraded.stderr[-400:]})"
            )
            async with check_engine.connect() as conn:
                post_down = await conn.run_sync(
                    lambda sync_conn: (
                        set(inspect(sync_conn).get_table_names()),
                        {
                            c["name"]
                            for c in inspect(sync_conn).get_columns(
                                "approval_checkpoints"
                            )
                        },
                    )
                )
            assert _NEW_TABLE not in post_down[0]
            assert "publication_manifest_id" not in post_down[1]
            re_up = _alembic("upgrade", "head")
            assert re_up.returncode == 0, re_up.stderr[-400:]
        finally:
            await check_engine.dispose()
    finally:
        try:
            await _admin_execute(f'DROP DATABASE IF EXISTS "{ephemeral_name}"')
        except Exception:  # noqa: BLE001, S110 — best-effort cleanup
            pass
