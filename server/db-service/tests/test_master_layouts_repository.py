"""Phase 2.3b — master_layouts repository.

Same fixture pattern as test_masters_repository: a real Postgres pool
and tmp_project, with master_layouts rows scoped to that project's
master so cleanup cascades cleanly.

Repository surface tested:

* upsert_master_layout (idempotent on (master_id, master_index, layout_index))
* list_layouts_by_master (ordered by position)
* get_layout
* update_layout (kind/enabled/notes/position/is_default)
* set_layout_default (transactional: clears any other default for the
  same kind in this master)
* delete is implicit via FK CASCADE — covered by the masters tests
"""

from __future__ import annotations

import pytest

from app.db.master_layouts.repository import (
    get_layout,
    list_layouts_by_master,
    set_layout_default,
    update_layout,
    upsert_master_layout,
)
from app.db.masters.repository import create_master


pytestmark = pytest.mark.asyncio


def _manifest_min(name: str = "T") -> dict:
    return {
        "name": name,
        "canvas": {"w": 1280, "h": 720},
        "theme": {
            "fonts": {"major": "Georgia", "minor": "Arial"},
            "colors": {
                "text": "#000000",
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


async def _make_master(pool, project_id) -> str:
    m = await create_master(
        pool,
        project_id=project_id,
        name="T",
        manifest=_manifest_min(),
        source_sha256="layouts-test" * 4,
    )
    return m.id


async def test_upsert_inserts_row(pool, tmp_project):
    master_id = await _make_master(pool, tmp_project["id"])
    row = await upsert_master_layout(
        pool,
        master_id=master_id,
        master_index=0,
        layout_index=0,
        name="Title Slide",
        auto_kind="title",
        position=0,
        placeholders=[{"role": "title", "x": 0, "y": 0, "w": 1280, "h": 200}],
        safe_area={"x": 80, "y": 200, "w": 1120, "h": 400},
        theme_index=1,
        font_major="Georgia",
        font_minor="Arial",
        palette={"primary": "#A32020"},
        preview_blob_url=None,
    )
    assert row.master_id == master_id
    assert row.master_index == 0
    assert row.layout_index == 0
    assert row.name == "Title Slide"
    assert row.auto_kind == "title"
    assert row.user_kind is None
    assert row.enabled is True
    assert row.is_default is False
    assert row.position == 0


async def test_upsert_is_idempotent_and_preserves_user_fields(pool, tmp_project):
    """Re-upserting with the same (master_id, master_index, layout_index)
    refreshes extractor-controlled fields but preserves user_kind /
    enabled / is_default / position / notes / preview_blob_url."""
    master_id = await _make_master(pool, tmp_project["id"])

    a = await upsert_master_layout(
        pool,
        master_id=master_id,
        master_index=0,
        layout_index=0,
        name="Old name",
        auto_kind="title",
        position=0,
        placeholders=[],
        safe_area=None,
        theme_index=1,
        font_major=None,
        font_minor=None,
        palette={},
        preview_blob_url="http://blob/old.png",
    )
    # User edits
    await update_layout(
        pool,
        layout_id=a.id,
        user_kind="cover",
        enabled=False,
        position=7,
        notes="executive only",
    )

    # Re-upsert with new extractor data (different name, kind)
    b = await upsert_master_layout(
        pool,
        master_id=master_id,
        master_index=0,
        layout_index=0,
        name="New name",
        auto_kind="content",
        position=99,  # position param ignored on conflict
        placeholders=[{"role": "title", "x": 0, "y": 0, "w": 1, "h": 1}],
        safe_area={"x": 1, "y": 2, "w": 3, "h": 4},
        theme_index=2,
        font_major="Helvetica",
        font_minor="Helvetica",
        palette={"primary": "#000"},
        preview_blob_url=None,  # NULL means keep existing
    )
    assert b.id == a.id  # same row
    # Refreshed fields:
    assert b.name == "New name"
    assert b.auto_kind == "content"
    assert b.theme_index == 2
    assert b.font_major == "Helvetica"
    # Preserved fields:
    assert b.user_kind == "cover"
    assert b.enabled is False
    assert b.position == 7
    assert b.notes == "executive only"
    assert b.preview_blob_url == "http://blob/old.png"


async def test_upsert_with_new_preview_replaces_url(pool, tmp_project):
    """When the upsert *does* carry a fresh preview URL, that wins —
    we can't keep stale blob URLs after a re-render."""
    master_id = await _make_master(pool, tmp_project["id"])

    await upsert_master_layout(
        pool,
        master_id=master_id,
        master_index=0,
        layout_index=0,
        name="x",
        auto_kind="title",
        position=0,
        placeholders=[],
        safe_area=None,
        theme_index=1,
        font_major=None,
        font_minor=None,
        palette={},
        preview_blob_url="http://blob/v1.png",
    )
    b = await upsert_master_layout(
        pool,
        master_id=master_id,
        master_index=0,
        layout_index=0,
        name="x",
        auto_kind="title",
        position=0,
        placeholders=[],
        safe_area=None,
        theme_index=1,
        font_major=None,
        font_minor=None,
        palette={},
        preview_blob_url="http://blob/v2.png",
    )
    assert b.preview_blob_url == "http://blob/v2.png"


async def test_list_orders_by_position(pool, tmp_project):
    master_id = await _make_master(pool, tmp_project["id"])
    for li, pos in [(0, 5), (1, 0), (2, 3)]:
        await upsert_master_layout(
            pool,
            master_id=master_id,
            master_index=0,
            layout_index=li,
            name=f"L{li}",
            auto_kind="other",
            position=pos,
            placeholders=[],
            safe_area=None,
            theme_index=1,
            font_major=None,
            font_minor=None,
            palette={},
            preview_blob_url=None,
        )
    rows = await list_layouts_by_master(pool, master_id)
    assert [r.layout_index for r in rows] == [1, 2, 0]


async def test_get_layout_returns_none_for_unknown(pool):
    import uuid

    assert await get_layout(pool, uuid.uuid4()) is None


async def test_set_layout_default_clears_others_in_same_kind(pool, tmp_project):
    """Marking layout B as default for kind=cover must clear the
    flag on layout A (also kind=cover). The unique partial index
    enforces this; the repository's helper does it transactionally
    so the constraint never fires mid-call.
    """
    master_id = await _make_master(pool, tmp_project["id"])
    a = await upsert_master_layout(
        pool,
        master_id=master_id,
        master_index=0,
        layout_index=0,
        name="A",
        auto_kind="title",
        position=0,
        placeholders=[],
        safe_area=None,
        theme_index=1,
        font_major=None,
        font_minor=None,
        palette={},
        preview_blob_url=None,
    )
    b = await upsert_master_layout(
        pool,
        master_id=master_id,
        master_index=0,
        layout_index=1,
        name="B",
        auto_kind="title",
        position=1,
        placeholders=[],
        safe_area=None,
        theme_index=1,
        font_major=None,
        font_minor=None,
        palette={},
        preview_blob_url=None,
    )

    # Both kinds resolve to "title" via auto_kind. Mark A as default.
    await update_layout(pool, layout_id=a.id, user_kind="title")
    await update_layout(pool, layout_id=b.id, user_kind="title")
    await set_layout_default(pool, layout_id=a.id)
    a2 = await get_layout(pool, a.id)
    b2 = await get_layout(pool, b.id)
    assert a2.is_default is True
    assert b2.is_default is False

    # Switch to B; A clears.
    await set_layout_default(pool, layout_id=b.id)
    a3 = await get_layout(pool, a.id)
    b3 = await get_layout(pool, b.id)
    assert a3.is_default is False
    assert b3.is_default is True


async def test_delete_master_cascades_layouts(pool, tmp_project):
    """ON DELETE CASCADE on master_layouts.master_id: dropping the
    master removes its layouts. Belt-and-braces test against the FK
    declaration."""
    master_id = await _make_master(pool, tmp_project["id"])
    await upsert_master_layout(
        pool,
        master_id=master_id,
        master_index=0,
        layout_index=0,
        name="x",
        auto_kind="title",
        position=0,
        placeholders=[],
        safe_area=None,
        theme_index=1,
        font_major=None,
        font_minor=None,
        palette={},
        preview_blob_url=None,
    )
    rows_before = await list_layouts_by_master(pool, master_id)
    assert len(rows_before) == 1

    from app.db.masters.repository import delete_master

    await delete_master(pool, master_id)
    rows_after = await list_layouts_by_master(pool, master_id)
    assert rows_after == []
