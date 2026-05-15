"""Slide repository — all slides DB operations.

A DEFERRABLE UNIQUE constraint on ``(project_id, position)`` guarantees
no two slides share a position within a project:

  * Default IMMEDIATE check — two parallel ``CreateSlide`` calls with the
    same explicit ``position`` collide at INSERT time. One wins, the
    other raises ``asyncpg.UniqueViolationError`` which the agent loop
    surfaces as an is_error tool_result. The model retries with a
    different position.
  * Deferred inside the legacy shift paths (``create_slide(after_slide_id)``,
    ``delete_slide``, ``reorder_slide``) — these produce transient
    duplicates mid-transaction while shifting/renumbering positions.
    Each path explicitly ``SET CONSTRAINTS … DEFERRED`` so the check
    moves to COMMIT, by which time positions are tidy again.

Migration ``0013_slide_position_unique`` adds the constraint.
"""

from __future__ import annotations

from uuid import UUID

import asyncpg

from app.db import Pool
from app.db.slides import queries
from app.db.slides.models import Slide

# Name of the deferrable unique constraint (matches migration 0013).
# Kept as a module constant so the SET CONSTRAINTS statements below
# point at the same string the migration creates — a typo here would
# silently leave the constraint in IMMEDIATE mode and break the shift
# paths at the first interim UPDATE.
_POSITION_UNIQUE_CONSTRAINT = "slides_project_position_unique"


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
    position: int | None = None,
) -> Slide:
    """Insert a slide, either at an explicit `position` or relative to
    `after_slide_id`.

    Two modes:

      * `position` supplied — single INSERT at the given position, NO
        shift transaction. The caller is responsible for picking a
        position that won't collide with an existing slide (typically:
        N..N+k-1 for k new slides on a deck of length N). This is the
        fast path that lets the agent loop run many CreateSlide calls
        in parallel within one turn.

      * `position=None` — relative insert. `after_slide_id=None` lands
        at position 0; otherwise at `after.position + 1`. Rows at or
        beyond that position shift down by one inside the same
        transaction. Slower (serial), but the only safe mode when the
        caller doesn't know the deck's current layout.

    `position < 0` is rejected. Either `position` or `after_slide_id`
    can be supplied — the router validates they're not both set.
    """
    if position is not None:
        if position < 0:
            raise ValueError("position must be >= 0")
        # Explicit-position INSERT runs against the IMMEDIATE constraint:
        # if another concurrent create just took this slot, asyncpg
        # raises UniqueViolationError and we translate it into a clean
        # 400 the agent loop can retry on. NO transaction here — the
        # constraint is the only gate, so we don't want to swallow the
        # violation inside an `async with conn.transaction()` block.
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(queries.INSERT, project_id, position, title, html)
        except asyncpg.UniqueViolationError as e:
            raise ValueError(
                f"position {position} is already taken in this project. "
                f"Pick another position (typically one >= the current "
                f"deck length) and retry."
            ) from e
        except asyncpg.CheckViolationError as e:
            raise ValueError(
                "html failed the DB content check — empty or near-empty "
                "slide payloads are rejected. Re-emit the create with "
                "the actual slide content."
            ) from e
        return Slide.from_record(row)

    async with pool.acquire() as conn:
        async with conn.transaction():
            # The legacy after_slide_id path shifts every later slide
            # down by one, which produces transient duplicates during
            # the UPDATE. Defer the unique check until COMMIT so those
            # mid-transaction states are tolerated.
            await conn.execute(f"SET CONSTRAINTS {_POSITION_UNIQUE_CONSTRAINT} DEFERRED")
            if after_slide_id is None:
                new_pos = 0
            else:
                after_row = await conn.fetchrow(queries.GET, after_slide_id)
                if after_row is None or after_row["project_id"] != project_id:
                    raise ValueError("after_slide_id does not belong to the target project")
                new_pos = after_row["position"] + 1

            await conn.execute(queries.SHIFT_DOWN_FROM, project_id, new_pos)
            try:
                row = await conn.fetchrow(queries.INSERT, project_id, new_pos, title, html)
            except asyncpg.CheckViolationError as e:
                raise ValueError(
                    "html failed the DB content check — empty or "
                    "near-empty slide payloads are rejected. Re-emit "
                    "the create with the actual slide content."
                ) from e
    return Slide.from_record(row)


async def update_slide(
    pool: Pool,
    slide_id: UUID,
    *,
    html: str | None = None,
    title: str | None = None,
) -> Slide | None:
    try:
        row = await pool.fetchrow(queries.UPDATE, slide_id, html, title)
    except asyncpg.CheckViolationError as e:
        # ``slides_html_not_empty`` failed — the caller passed an
        # empty / near-empty html. Surface as a 400 the agent can
        # retry on, same shape as the create-side check.
        raise ValueError(
            "html failed the DB content check — empty or near-empty "
            "slide payloads are rejected. Re-send the update with the "
            "actual slide content."
        ) from e
    return Slide.from_record(row) if row else None


async def delete_slide(pool: Pool, slide_id: UUID) -> list[Slide]:
    """Delete a slide and close the resulting position gap.

    Returns the full ordered list of remaining slides so callers can emit
    a `slides_replaced` event covering the renumbering, not just a
    `slide_deleted` for the removed row. (Reorder takes the same approach
    for the same reason — both operations affect the whole deck's
    position invariant.)

    Empty list if the slide didn't exist; caller decides whether that's
    a soft no-op or surfaced as an error.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            # SHIFT_UP_FROM moves every later slide one slot down; mid-
            # transaction state has duplicates. Defer the unique check
            # so we evaluate only the final post-shift state.
            await conn.execute(f"SET CONSTRAINTS {_POSITION_UNIQUE_CONSTRAINT} DEFERRED")
            slide = await conn.fetchrow(queries.GET, slide_id)
            if slide is None:
                return []
            await conn.execute(queries.DELETE, slide_id)
            await conn.execute(
                queries.SHIFT_UP_FROM,
                slide["project_id"],
                slide["position"],
            )
            rows = await conn.fetch(
                queries.LIST_BY_PROJECT,
                slide["project_id"],
            )
    return [Slide.from_record(r) for r in rows]


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
            # The renumber loop below sets positions one-by-one;
            # midway through, two slides may transiently share the
            # same position. Defer the unique check so only the
            # tidy post-loop state is validated at COMMIT.
            await conn.execute(f"SET CONSTRAINTS {_POSITION_UNIQUE_CONSTRAINT} DEFERRED")
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
                    raise ValueError("after_slide_id does not belong to the target project")
                insert_at = idx + 1

            final_order = remaining[:insert_at] + [moving] + remaining[insert_at:]

            # Rewrite every position. Contiguous 0..n-1, keeps the invariant
            # tidy. n is small for realistic decks.
            for new_pos, r in enumerate(final_order):
                if r["position"] != new_pos:
                    await conn.execute(queries.SET_POSITION, r["id"], new_pos)

            updated = await conn.fetch(queries.LIST_BY_PROJECT, project_id)

    return [Slide.from_record(r) for r in updated]
