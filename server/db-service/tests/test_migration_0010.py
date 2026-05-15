"""Phase 1.0 — masters schema migration.

Guards the *shape* of the new migration without spinning up a real
Postgres. Uses Alembic's ScriptDirectory to walk the revision graph
and asserts:

  * the revision graph is well-formed (no orphans, cycles, or
    multiple heads — alembic refuses to upgrade when any of those
    are true; catching it here saves a deploy-time surprise)
  * 0010 chains correctly off 0009
  * 0010's SQL contains the DDL we rely on in the repository layer

Real upgrade-against-Postgres behaviour belongs in an integration
test that runs against a live DB. That lands later when we have
real data flowing.
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


_ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def _scripts() -> ScriptDirectory:
    cfg = Config(str(_ALEMBIC_INI))
    return ScriptDirectory.from_config(cfg)


def test_revision_graph_is_well_formed() -> None:
    sd = _scripts()
    heads = sd.get_heads()
    assert len(heads) == 1, f"expected single head, got {heads}"


def test_0010_chains_off_0009() -> None:
    sd = _scripts()
    rev = sd.get_revision("0010")
    assert rev is not None, "revision 0010 not found"
    assert rev.down_revision == "0009"
    assert "master" in (rev.doc or "").lower()


def test_0010_creates_masters_table() -> None:
    sd = _scripts()
    rev = sd.get_revision("0010")
    src = Path(rev.path).read_text()

    assert "CREATE TABLE masters" in src
    for col in (
        "id",
        "project_id",
        "name",
        "source_sha256",
        "manifest",
        "source_pptx_blob_url",
        "created_at",
        "updated_at",
    ):
        assert col in src, f"masters.{col} missing from migration"

    assert "uq_masters_project_sha" in src

    assert "active_master_id" in src
    assert "ALTER TABLE projects" in src

    assert "ALTER TABLE slides" in src
    assert "master_id" in src
    assert "scene_graph" in src
