"""Pydantic models for the Slide IR.

Geometry is stored in CSS pixels at the master's canvas size (not EMU).
EMU conversion happens once at PPTX export time; everything upstream
reasons in px because LLMs and humans do.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

ChromeRole = Literal[
    "title",
    "subtitle",
    "body",
    "footer",
    "page_number",
    "date",
    "logo",
    "other",
]

TextAlign = Literal["left", "center", "right", "justify"]


class MasterCanvas(BaseModel):
    """Slide canvas in CSS pixels. Standard PPTX 16:9 is 1280×720."""

    w: int
    h: int


class MasterTheme(BaseModel):
    """Fonts + semantic palette extracted from the PPTX theme.

    ``fonts``: ``{"major": "Georgia", "minor": "Arial"}``. Major = titles
    (theme ``majorFont``), minor = body (theme ``minorFont``).

    ``colors``: semantic keys, not theme-role keys. Downstream code should
    look up ``primary`` / ``text`` / ``bg`` and not care about the PPTX
    ``accent1``/``dk1`` names.
    """

    fonts: dict[str, str]
    colors: dict[str, object]


class MasterChromeElement(BaseModel):
    """A single placeholder or locked text box inherited from the master.

    Geometry is what we extract from the PPTX; we do not editorialize.
    ``text`` is populated only when the master carries a literal string
    (e.g. the "Strategy&" footer). Prompt/hint text is stripped.
    """

    role: ChromeRole
    x: float
    y: float
    w: float
    h: float
    font: str | None = None
    size: float | None = None  # pt
    weight: int | None = None  # 400 | 700
    color: str | None = None  # "#RRGGBB"
    align: TextAlign | None = None
    text: str | None = None


class MasterSafeArea(BaseModel):
    x: float
    y: float
    w: float
    h: float


LayoutKind = Literal[
    "title",
    "section_header",
    "agenda",
    "content",
    "two_column",
    "kpi",
    "comparison",
    "quote",
    "blank",
    "other",
]


class LayoutDescriptor(BaseModel):
    """One slide-master layout, classified for LLM slot-filling.

    Phase 2.1: layouts now carry their parent master's index so a
    multi-master template can be navigated end-to-end. The PPTX layout
    name is human-friendly but not unique across masters in templates
    like stc, where multiple masters share the layout name
    ``"12_Content slide _ VCS_to use"``. The ``(master_index,
    layout_index)`` pair is the stable identity.
    """

    name: str
    kind: LayoutKind = "other"
    safe_area: MasterSafeArea | None = None
    placeholders: list[MasterChromeElement] = Field(default_factory=list)
    description: str = ""
    # Phase 2.1: stable identity in a multi-master world
    master_index: int = 0
    layout_index: int = 0


class MasterEntry(BaseModel):
    """One slide_master from the .pptx, with everything it owns.

    The legacy single-master fields on ``MasterManifest`` are derived
    from ``masters[0]`` for back-compat; new code reads ``masters``
    directly.
    """

    index: int
    name: str = ""
    theme_index: int = 1  # which themeN.xml backs this master
    palette: dict[str, object] = Field(default_factory=dict)
    fonts: dict[str, str] = Field(default_factory=dict)
    layouts: list[LayoutDescriptor] = Field(default_factory=list)


class ThemeEntry(BaseModel):
    """A unique theme palette, deduplicated by raw-XML hash.

    Strategy& has 3 byte-identical theme files; surfacing 3 themes
    would mislead the curation UI. Hash-dedup collapses them, keeping
    the original-index list so callers can still match a master's
    ``theme_index`` to one of these entries.
    """

    indices: list[int]  # all themeN.xml files that hash to this entry
    palette: dict[str, object]
    fonts: dict[str, str]


class MasterManifest(BaseModel):
    """Everything a slide generator needs to inherit from, and nothing more.

    Persisted as ``masters.manifest`` JSONB. ``source_sha256`` is the hash
    of the original PPTX bytes so we can detect re-uploads of the same
    file and so PPTX export can retrieve the blob for true master
    inheritance at export time.

    ``layouts`` carries the slide-master's layout menu — see
    ``LayoutDescriptor``. Older manifests stored ``list[str]``; we accept
    both shapes (validator below) and migrate to descriptors at read time.
    """

    name: str = "Imported master"
    source_sha256: str | None = None
    canvas: MasterCanvas
    theme: MasterTheme  # legacy: theme of masters[0]
    safe_area: MasterSafeArea  # legacy: safe_area of masters[0]
    chrome: list[MasterChromeElement] = Field(default_factory=list)  # legacy: chrome of masters[0]
    layouts: list[LayoutDescriptor] = Field(default_factory=list)  # legacy: layouts of masters[0]
    # Phase 2.1: multi-master surface
    masters: list[MasterEntry] = Field(default_factory=list)
    themes: list[ThemeEntry] = Field(default_factory=list)
    fonts_referenced: list[str] = Field(
        default_factory=list
    )  # union of font families across masters

    @field_validator("layouts", mode="before")
    @classmethod
    def _coerce_legacy_layouts(cls, value):
        # Older manifests stored layouts as ``list[str]`` of layout names.
        # Promote each to a minimal LayoutDescriptor so persisted data
        # keeps loading after the schema upgrade.
        if not isinstance(value, list):
            return value
        return [
            {"name": item, "kind": "other"} if isinstance(item, str) else item for item in value
        ]
