"""Phase 2.3a — master_layouts schema migration.

Same harness pattern as ``test_migration_0010``: walk the alembic
script directory, assert revision id + down_revision, assert the
upgrade body contains the columns + indexes the repository will
rely on.
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


_ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def _scripts() -> ScriptDirectory:
    cfg = Config(str(_ALEMBIC_INI))
    return ScriptDirectory.from_config(cfg)


def test_revision_graph_still_has_single_head() -> None:
    sd = _scripts()
    heads = sd.get_heads()
    assert len(heads) == 1, f"expected single head, got {heads}"


def test_0011_chains_off_0010() -> None:
    sd = _scripts()
    rev = sd.get_revision("0011")
    assert rev is not None, "revision 0011 not found"
    assert rev.down_revision == "0010"
    assert "master_layouts" in (rev.doc or "").lower()


def test_0011_creates_master_layouts_table() -> None:
    sd = _scripts()
    rev = sd.get_revision("0011")
    src = Path(rev.path).read_text()

    assert "CREATE TABLE master_layouts" in src

    # Columns the repository + curation UI rely on
    expected_columns = [
        "id",
        "master_id",
        "master_index",
        "layout_index",
        "name",
        "auto_kind",
        "user_kind",
        "enabled",
        "is_default",
        "position",
        "notes",
        "preview_blob_url",
        "placeholders",
        "safe_area",
        "theme_index",
        "font_major",
        "font_minor",
        "palette",
        "created_at",
        "updated_at",
    ]
    for col in expected_columns:
        assert col in src, f"master_layouts.{col} missing from migration"

    # FK to masters with cascade — when a master is deleted, its rows
    # go too.
    assert "REFERENCES masters" in src
    assert "ON DELETE CASCADE" in src

    # Composite uniqueness so re-extraction can UPSERT cleanly.
    assert "uq_master_layouts_position" in src or "UNIQUE" in src

    # Default-per-kind constraint: at most one is_default=true per
    # (master_id, user_kind).
    assert "uq_master_layouts_default" in src or "WHERE is_default" in src
