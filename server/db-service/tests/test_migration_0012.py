"""Phase C — masters.fonts_assets column.

Same shape as test_migration_0010/0011: walk the alembic revision graph
and confirm the migration chains correctly and the SQL it emits adds the
expected DDL. Real upgrade behaviour against a Postgres pool is covered
by the repository test which exercises insert + read with the new
column.
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


def test_0012_chains_off_0011() -> None:
    sd = _scripts()
    rev = sd.get_revision("0012")
    assert rev is not None, "revision 0012 not found"
    assert rev.down_revision == "0011"
    assert "fonts" in (rev.doc or "").lower()


def test_0012_adds_fonts_assets_column() -> None:
    sd = _scripts()
    rev = sd.get_revision("0012")
    src = Path(rev.path).read_text()

    assert "ALTER TABLE masters" in src
    assert "fonts_assets" in src
    assert "JSONB" in src
    assert "DEFAULT '[]'::jsonb" in src
    assert "DROP COLUMN IF EXISTS fonts_assets" in src
