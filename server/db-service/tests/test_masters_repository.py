"""Phase 1.1 — masters repository against real Postgres.

The repository is the only path that runs SQL against the masters
table. Tests cover the contract callers (router, the eventual upload
endpoint, the export tool) need:

  * ``create_master`` returns a typed row with the manifest preserved
    and a blob URL set when given.
  * Re-inserting with the same ``source_sha256`` upserts in place —
    same id, refreshed manifest, no duplicate row.
  * ``get_master`` and ``list_masters_by_project`` round-trip.
  * ``set_active_master`` updates ``projects.active_master_id`` and
    clears it on null.
  * ``delete_master`` removes the row and frees ``active_master_id``
    via ON DELETE SET NULL.

Each test runs against a fresh ``tmp_project`` fixture, so they never
share state. We use a manifest dict that resembles a real extraction
without pretending to be a full one — the repository doesn't validate
manifest contents; that's the extractor's job.
"""

from __future__ import annotations

import pytest

from app.db.masters.repository import (
    create_master,
    delete_master,
    get_master,
    list_masters_by_project,
    set_active_master,
)

pytestmark = pytest.mark.asyncio


def _manifest(name: str = "Test Master") -> dict:
    return {
        "name": name,
        "canvas": {"w": 1280, "h": 720},
        "theme": {
            "fonts": {"major": "Georgia", "minor": "Arial"},
            "colors": {
                "text": "#1A1A1A",
                "bg": "#FFFFFF",
                "primary": "#A32020",
                "secondary": "#888888",
                "neutral": [],
            },
        },
        "safe_area": {"x": 80, "y": 175, "w": 1120, "h": 470},
        "chrome": [],
        "layouts": [],
    }


async def test_create_master_returns_row(pool, tmp_project):
    m = await create_master(
        pool,
        project_id=tmp_project["id"],
        name="Strategy& 16:9",
        manifest=_manifest("Strategy& 16:9"),
        source_sha256="abc" * 21 + "x",
        source_pptx_blob_url="http://127.0.0.1:10000/devstoreaccount1/masters/foo/bar.pptx",
    )
    assert m.id is not None
    assert m.project_id == tmp_project["id"]
    assert m.name == "Strategy& 16:9"
    assert m.source_sha256 == "abc" * 21 + "x"
    assert m.source_pptx_blob_url.endswith("bar.pptx")
    assert isinstance(m.manifest, dict)
    assert m.manifest["canvas"] == {"w": 1280, "h": 720}


async def test_create_is_idempotent_by_sha(pool, tmp_project):
    """Same SHA into the same project upserts in place — same id,
    refreshed manifest. Catches the case where re-uploading the same
    .pptx silently creates a second row (which v2-old did)."""
    sha = "deadbeef" * 8
    first = await create_master(
        pool,
        project_id=tmp_project["id"],
        name="V1 name",
        manifest=_manifest("V1"),
        source_sha256=sha,
        source_pptx_blob_url="http://blob/x.pptx",
    )
    second = await create_master(
        pool,
        project_id=tmp_project["id"],
        name="V2 name (renamed)",
        manifest=_manifest("V2"),
        source_sha256=sha,
        source_pptx_blob_url="http://blob/x.pptx",
    )
    assert second.id == first.id
    assert second.name == "V2 name (renamed)"
    assert second.manifest["name"] == "V2"

    rows = await list_masters_by_project(pool, tmp_project["id"])
    assert len(rows) == 1


async def test_get_returns_created(pool, tmp_project):
    created = await create_master(
        pool,
        project_id=tmp_project["id"],
        name="Get me",
        manifest=_manifest(),
    )
    fetched = await get_master(pool, created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.name == "Get me"


async def test_get_returns_none_for_unknown(pool):
    import uuid

    assert await get_master(pool, uuid.uuid4()) is None


async def test_create_persists_fonts_assets(pool, tmp_project):
    """``fonts_assets`` round-trips as a list of dicts. Defaults to
    [] when the column is omitted from the call."""
    bare = await create_master(
        pool,
        project_id=tmp_project["id"],
        name="bare",
        manifest=_manifest(),
    )
    assert bare.fonts_assets == []

    fonts = [
        {
            "filename": "STCForward-Bold.ttf",
            "family": "STC Forward",
            "weight": 700,
            "style": "normal",
            "source": "uploaded",
            "blob_url": "http://blob/fonts/STCForward-Bold.ttf",
        },
        {
            "filename": "Fund-LightItalic.ttf",
            "family": "Fund",
            "weight": 300,
            "style": "italic",
            "source": "uploaded",
            "blob_url": "http://blob/fonts/Fund-LightItalic.ttf",
        },
    ]
    branded = await create_master(
        pool,
        project_id=tmp_project["id"],
        name="branded",
        manifest=_manifest(),
        fonts_assets=fonts,
    )
    assert isinstance(branded.fonts_assets, list)
    assert len(branded.fonts_assets) == 2
    assert {f["filename"] for f in branded.fonts_assets} == {
        "STCForward-Bold.ttf",
        "Fund-LightItalic.ttf",
    }
    assert branded.fonts_assets[0]["weight"] == 700
    assert branded.fonts_assets[1]["style"] == "italic"

    # Re-fetch via the read path to confirm the JSONB cast on read works.
    again = await get_master(pool, branded.id)
    assert again.fonts_assets[0]["family"] == "STC Forward"


async def test_upsert_refreshes_fonts_assets(pool, tmp_project):
    """Re-uploading the same template (same SHA) replaces the
    ``fonts_assets`` array — users can fix a typo by re-attaching."""
    sha = "feedface" * 8
    first = await create_master(
        pool,
        project_id=tmp_project["id"],
        name="first",
        manifest=_manifest(),
        source_sha256=sha,
        fonts_assets=[
            {
                "filename": "Wrong.ttf",
                "family": "Wrong",
                "weight": 400,
                "style": "normal",
                "source": "uploaded",
                "blob_url": "http://blob/fonts/Wrong.ttf",
            },
        ],
    )
    second = await create_master(
        pool,
        project_id=tmp_project["id"],
        name="first",
        manifest=_manifest(),
        source_sha256=sha,
        fonts_assets=[
            {
                "filename": "Right.ttf",
                "family": "Right",
                "weight": 400,
                "style": "normal",
                "source": "uploaded",
                "blob_url": "http://blob/fonts/Right.ttf",
            },
        ],
    )
    assert second.id == first.id
    assert [f["filename"] for f in second.fonts_assets] == ["Right.ttf"]


async def test_list_orders_by_created_desc(pool, tmp_project):
    a = await create_master(
        pool,
        project_id=tmp_project["id"],
        name="oldest",
        manifest=_manifest(),
    )
    b = await create_master(
        pool,
        project_id=tmp_project["id"],
        name="middle",
        manifest=_manifest(),
    )
    c = await create_master(
        pool,
        project_id=tmp_project["id"],
        name="newest",
        manifest=_manifest(),
    )
    rows = await list_masters_by_project(pool, tmp_project["id"])
    ids = [r.id for r in rows]
    # newest first
    assert ids == [c.id, b.id, a.id]


async def test_set_active_master(pool, tmp_project):
    m1 = await create_master(pool, project_id=tmp_project["id"], name="m1", manifest=_manifest())
    m2 = await create_master(pool, project_id=tmp_project["id"], name="m2", manifest=_manifest())

    await set_active_master(pool, tmp_project["id"], m1.id)
    active = await pool.fetchval(
        "SELECT active_master_id FROM projects WHERE id = $1",
        tmp_project["id"],
    )
    assert active == m1.id

    # Switching is a plain replace.
    await set_active_master(pool, tmp_project["id"], m2.id)
    active = await pool.fetchval(
        "SELECT active_master_id FROM projects WHERE id = $1",
        tmp_project["id"],
    )
    assert active == m2.id

    # ``None`` clears the pointer (project goes back to no-master mode).
    await set_active_master(pool, tmp_project["id"], None)
    active = await pool.fetchval(
        "SELECT active_master_id FROM projects WHERE id = $1",
        tmp_project["id"],
    )
    assert active is None


async def test_delete_master_clears_active_pointer(pool, tmp_project):
    """ON DELETE SET NULL on projects.active_master_id should fire
    when its target master is deleted, so the project doesn't dangle
    pointing at a ghost id."""
    m = await create_master(pool, project_id=tmp_project["id"], name="going", manifest=_manifest())
    await set_active_master(pool, tmp_project["id"], m.id)

    await delete_master(pool, m.id)

    assert await get_master(pool, m.id) is None
    active = await pool.fetchval(
        "SELECT active_master_id FROM projects WHERE id = $1",
        tmp_project["id"],
    )
    assert active is None
