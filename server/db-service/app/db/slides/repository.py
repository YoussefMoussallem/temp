"""Slide repository — all slides DB operations.

`create_slide` and `reorder_slide` open/close position gaps inside a single
transaction. No unique constraint on (project_id, position) — transient
duplicates during a shift are acceptable because the tx commits atomically.
"""

from __future__ import annotations

from uuid import UUID

from app.db import Pool
from app.db.slides import queries
from app.db.slides.models import Slide


async def get_slide(pool: Pool, slide_id: UUID) -> Slide | None:
    row = await pool.fetchrow(queries.GET, slide_id)
    return Slide.from_record(row) if row else None


async def list_slides_by_project(pool: Pool, project_id: UUID) -> list[Slide]:
    rows = await pool.fetch(queries.LIST_BY_PROJECT, project_id)
    return [Slide.from_record(r) for r in rows]


async def create_slide(
    pool: Pool,
    *,
    project_id: UUID,
    html: str,
    title: str | None = None,
    after_slide_id: UUID | None = None,
) -> Slide:
    """Insert a slide, optionally after `after_slide_id`.

    `after_slide_id=None` inserts at the top (position 0). Otherwise the new
    slide lands at `after.position + 1`; rows at or beyond that position
    shift down by one inside the same transaction.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            if after_slide_id is None:
                new_pos = 0
            else:
                after_row = await conn.fetchrow(queries.GET, after_slide_id)
                if after_row is None or after_row["project_id"] != project_id:
                    raise ValueError(
                        "after_slide_id does not belong to the target project"
                    )
                new_pos = after_row["position"] + 1

            await conn.execute(queries.SHIFT_DOWN_FROM, project_id, new_pos)
            row = await conn.fetchrow(
                queries.INSERT, project_id, new_pos, title, html
            )
    return Slide.from_record(row)


async def update_slide(
    pool: Pool,
    slide_id: UUID,
    *,
    html: str | None = None,
    title: str | None = None,
) -> Slide | None:
    row = await pool.fetchrow(queries.UPDATE, slide_id, html, title)
    return Slide.from_record(row) if row else None


async def delete_slide(pool: Pool, slide_id: UUID) -> None:
    # No renumber on delete — frontend reads ORDER BY position, so gaps
    # are harmless. Avoids an O(n) rewrite of every subsequent slide.
    await pool.execute(queries.DELETE, slide_id)


async def reorder_slide(
    pool: Pool,
    slide_id: UUID,
    *,
    after_slide_id: UUID | None = None,
) -> list[Slide]:
    """Move `slide_id` to a new position in its project.

    Returns the full ordered list afterwards so the caller can emit a single
    `slides_replaced` event instead of computing the delta.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            moving = await conn.fetchrow(queries.GET, slide_id)
            if moving is None:
                raise ValueError("slide not found")
            project_id = moving["project_id"]

            if after_slide_id == slide_id:
                raise ValueError("cannot place slide after itself")

            # Build the current order without the moving slide.
            rows = await conn.fetch(queries.LIST_BY_PROJECT, project_id)
            remaining = [r for r in rows if r["id"] != slide_id]

            # Decide the insertion index within `remaining`.
            if after_slide_id is None:
                insert_at = 0
            else:
                idx = next(
                    (i for i, r in enumerate(remaining) if r["id"] == after_slide_id),
                    None,
                )
                if idx is None:
                    raise ValueError(
                        "after_slide_id does not belong to the target project"
                    )
                insert_at = idx + 1

            final_order = remaining[:insert_at] + [moving] + remaining[insert_at:]

            # Rewrite every position. Contiguous 0..n-1, keeps the invariant
            # tidy. n is small for realistic decks.
            for new_pos, r in enumerate(final_order):
                if r["position"] != new_pos:
                    await conn.execute(queries.SET_POSITION, r["id"], new_pos)

            updated = await conn.fetch(queries.LIST_BY_PROJECT, project_id)

    return [Slide.from_record(r) for r in updated]
