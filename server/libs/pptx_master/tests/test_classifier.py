"""Layout classifier — geometry vs placeholder-count.

Locks in the rule that solved the stc bug: two BODY placeholders
stacked (main content + source / attribution line) classifies as
``content``, not ``two_column``. The old classifier flattened both
cases to ``two_column`` purely on count, which is why 19/22 stc layouts
came out of extraction as two-column despite being plain content slides.
"""

from __future__ import annotations

from pptx_master.master_extractor import _classify_by_placeholders
from pptx_master.schemas import MasterChromeElement


def _ph(
    role: str, x: float, y: float, w: float, h: float, text: str | None = None
) -> MasterChromeElement:
    return MasterChromeElement(
        role=role,
        x=x,
        y=y,
        w=w,
        h=h,
        text=text,
        font=None,
        size=None,
        weight=None,
        color=None,
        align=None,
    )


def test_two_bodies_side_by_side_is_two_column():
    """Title + 2 bodies at similar y, non-overlapping x → two_column."""
    placeholders = [
        _ph("title", 80, 40, 1120, 80),
        _ph("body", 80, 160, 540, 400),
        _ph("body", 660, 160, 540, 400),
    ]
    assert _classify_by_placeholders(placeholders) == "two_column"


def test_two_bodies_stacked_is_content_not_two_column():
    """The stc bug: 2 bodies stacked (main + footer/source line). Old
    classifier called this ``two_column`` purely on count — the right
    answer is ``content``."""
    placeholders = [
        _ph("title", 20, 38, 1240, 95),
        _ph("body", 88, 191, 1104, 400),  # main content
        _ph("body", 88, 600, 1104, 80),  # secondary line (source / etc)
    ]
    assert _classify_by_placeholders(placeholders) == "content"


def test_three_bodies_side_by_side_is_comparison():
    """Three columns laid out in a row → comparison (the agent treats
    comparison and three_column as the same archetype)."""
    placeholders = [
        _ph("title", 80, 40, 1120, 80),
        _ph("body", 80, 160, 350, 400),
        _ph("body", 460, 160, 350, 400),
        _ph("body", 840, 160, 350, 400),
    ]
    assert _classify_by_placeholders(placeholders) == "comparison"


def test_three_bodies_stacked_is_content():
    """Three stacked text blocks (process steps / TOC items) — not a
    comparison. Old classifier said comparison purely on count."""
    placeholders = [
        _ph("title", 80, 40, 1120, 80),
        _ph("body", 80, 160, 1120, 100),
        _ph("body", 80, 290, 1120, 100),
        _ph("body", 80, 420, 1120, 100),
    ]
    assert _classify_by_placeholders(placeholders) == "content"


def test_blank_when_no_title_or_body():
    placeholders = [
        _ph("page_number", 1240, 690, 30, 16),
        _ph("footer", 20, 690, 200, 16),
    ]
    assert _classify_by_placeholders(placeholders) == "blank"


def test_section_header_when_only_title():
    placeholders = [
        _ph("title", 80, 280, 1120, 160),
    ]
    assert _classify_by_placeholders(placeholders) == "section_header"


def test_one_body_is_content():
    placeholders = [
        _ph("title", 80, 40, 1120, 80),
        _ph("body", 80, 160, 1120, 480),
    ]
    assert _classify_by_placeholders(placeholders) == "content"


def test_overlapping_x_ranges_at_same_y_treated_as_stacked():
    """Edge case: two bodies at the same y but their x-ranges overlap
    significantly. That's a decoration on top of content, not a column
    pair — return ``content``."""
    placeholders = [
        _ph("title", 80, 40, 1120, 80),
        _ph("body", 80, 160, 1100, 400),
        _ph("body", 90, 160, 1080, 400),  # almost full overlap
    ]
    assert _classify_by_placeholders(placeholders) == "content"
