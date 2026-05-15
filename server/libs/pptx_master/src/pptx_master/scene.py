"""Scene graph — the editable, LLM-authored per-slide object.

A ``Scene`` is a flat list of absolutely-positioned elements over the
master's canvas. Geometry is CSS px at the master's canvas size
(typically 1280×720). Colors and fonts may reference the master's theme
tokens by name (``{"token": "primary"}``, ``{"token": "major"}``) OR
carry literal values (``{"hex": "#A32020"}``, ``"Georgia"``). The renderer
resolves tokens against the master at render time, so a re-brand (swap
the master) re-themes every scene without editing them.

No templates, no archetypes. The only constraints on composition are:
  * elements must fit inside the master's ``safe_area`` (enforced at
    render/validate time, not here);
  * colors/fonts should prefer theme tokens so the deck stays coherent
    if the master changes.

Everything else — hierarchy, alignment, rhythm — is up to the LLM.
"""

from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, Field

TextAlign = Literal["left", "center", "right", "justify"]
VAlign = Literal["top", "middle", "bottom"]


class ThemeColor(BaseModel):
    """Reference to a master palette key, e.g. ``primary``, ``secondary``,
    ``text``, ``bg``. Resolved at render time against the master's
    ``theme.colors``. Unknown tokens fall back to black.
    """

    token: str


class LiteralColor(BaseModel):
    """Literal ``#RRGGBB`` color — use sparingly; prefer theme tokens."""

    hex: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")


Color = Union[ThemeColor, LiteralColor]


class ThemeFont(BaseModel):
    """Reference to a master font role: ``major`` (titles) or ``minor``
    (body). Resolved at render time against ``theme.fonts``.
    """

    token: Literal["major", "minor"]


Font = Union[ThemeFont, str]


class _ElementBase(BaseModel):
    """Shared geometry. All coords are CSS px against the master canvas."""

    x: float
    y: float
    w: float
    h: float
    z: int = 0


class TextElement(_ElementBase):
    """A single block of text. Multiple lines? Emit multiple TextElements,
    one per line — keeps measurement and PPTX export simple.
    """

    type: Literal["text"] = "text"
    text: str
    font: Font | None = None
    size: float = 18.0  # pt
    weight: int = 400
    color: Color | None = None
    align: TextAlign = "left"
    valign: VAlign = "top"
    italic: bool = False


class ShapeElement(_ElementBase):
    """A colored rectangle — background cards, accent bars, dividers.
    Never contains text; pair with a TextElement on top when you need
    both.
    """

    type: Literal["shape"] = "shape"
    fill: Color | None = None
    border_color: Color | None = None
    border_width: float = 0.0
    border_radius: float = 0.0


class LineElement(_ElementBase):
    """Horizontal or vertical rule. Keep ``h`` small for a horizontal
    line; keep ``w`` small for a vertical one. Not truly a shape because
    PPTX export renders it as a connector, not a rectangle.
    """

    type: Literal["line"] = "line"
    color: Color | None = None
    thickness: float = 1.0


class ImageElement(_ElementBase):
    """Bitmap image by HTTP(S) URL or data URI. No SVG — PPTX support is
    inconsistent.
    """

    type: Literal["image"] = "image"
    src: str
    alt: str | None = None


class BulletElement(_ElementBase):
    """A single text frame containing a vertical bulleted list.

    One ``BulletElement`` becomes one PPTX shape with N ``<a:p>``
    paragraphs (one per item) at export time — keeps bullet metrics and
    indent semantics intact, which a list of N TextElements cannot. Use
    this for any vertical list of short lines; use TextElements when the
    items are visually distinct blocks (different sizes/positions).

    ``levels`` is parallel to ``items``: 0 = top-level bullet, 1 = first
    indent, etc. Either supply a list of the same length, or omit and
    every item is treated as level 0.
    """

    type: Literal["bullets"] = "bullets"
    items: list[str]
    levels: list[int] | None = None
    font: Font | None = None
    size: float = 14.0
    weight: int = 400
    color: Color | None = None
    line_height: float = 1.25  # multiplier on size; 1.0 = tight, 1.4 = airy


SceneElement = Union[TextElement, ShapeElement, LineElement, ImageElement, BulletElement]


SlideType = Literal[
    "title",
    "section_header",
    "content",
    "two_column",
    "kpi",
    "comparison",
    "quote",
    "blank",
]


class Scene(BaseModel):
    """A complete slide scene.

    ``master_id`` pins inheritance: the renderer looks up that master's
    theme, chrome, and canvas. Omitted means "render without chrome, on
    a bare canvas" — useful for tests but not for real decks.

    ``canvas`` snapshots the master's canvas size into the scene so a
    stale render still knows its native dimensions even if the master
    is swapped later. If omitted, falls back to the master's canvas.

    ``slide_type`` and ``layout_hint`` are the slot-filling signals:
    ``slide_type`` is the LLM's semantic intent (title, kpi, two_column,
    …) and ``layout_hint`` references one of the master's
    ``LayoutDescriptor.name`` values. When ``layout_hint`` is set, the
    renderer and bounds-checker prefer that layout's ``safe_area`` over
    the master-level one.
    """

    master_id: str | None = None
    canvas: dict[str, int] | None = None  # {"w": 1280, "h": 720}
    slide_type: SlideType | None = None
    layout_hint: str | None = None
    elements: list[SceneElement] = Field(default_factory=list)
    notes: str | None = None  # speaker notes, preserved for PPTX export
