"""Parse PowerPoint masters into structured slide-IR manifests.

Concepts
--------

A **template** in this codebase = master + theme + (optionally) bundled
fonts. This library covers extraction of the master + theme half.

A **master** is the inheritance contract extracted from a ``.pptx``:
canvas, theme tokens (font names + palette), safe area, locked chrome
(title/subtitle/footer/page-number geometry), and a flat list of
``LayoutDescriptor`` rows. A deck has one or more masters (PowerPoint
allows nested ``SlideMaster`` parts; multi-theme decks like stc carry
11+ masters); slides inherit from one and never duplicate its rules.

A **layout** is exactly one PowerPoint ``SlideLayout`` XML part,
augmented with:

* ``placeholders`` — typed, geometry-resolved placeholder list (role +
  x/y/w/h + per-placeholder typography + locked text)
* ``kind`` — heuristic archetype (title / agenda / content / two_column /
  comparison / kpi / quote / section_header / blank / other)
* ``safe_area`` — per-layout content region when it differs from the
  master's safe area; ``None`` falls through to the master's

The ``kind`` is a hint, not a contract. The classifier checks the
layout's name first (strong vendor signals like "Quote - White" or
"Two Columns" win), then falls back to placeholder count + GEOMETRY:
2 BODY placeholders side-by-side is ``two_column``; 2 BODY stacked
(main content + source line) is ``content``. Curation lets the user
override ``kind`` per layout.

Loose spots (acknowledged, not fixed in this iteration):

* Cross-master deduplication — stc reuses the same layout shape across
  11 themes, so the manifest carries 11 near-duplicate layouts. They
  group cleanly by ``(name, placeholder-role-signature)`` if a future
  consumer wants to surface them as one logical layout × N theme variants.
* Semantic slot annotation beyond OOXML roles — every BODY placeholder
  has the same role label whether it carries bullets, a chart caption,
  a quote attribution, or a stat. Distinguishing them needs richer
  per-placeholder semantics than the OOXML schema gives us.
* The classifier vocabulary is small (10 kinds). Real-world templates
  have more archetypes (matrix_2x2, process, roadmap, scorecard); we
  collapse them into ``other`` for now.

A **scene** is the per-slide object an authoring agent composes inside
the master's safe area. A flat list of absolutely-positioned text /
shape / line / image elements with colors and fonts expressed either as
theme-token references or literal values.

Font *bytes* (the displayable .ttf / .otf files) are not part of this
library — they're persisted separately by the upload pipeline as
``fonts_assets`` on the master DB row, and only the file name is needed
to resolve them at consumption time.
"""

from .master_extractor import extract_master_from_pptx
from .schemas import (
    LayoutDescriptor,
    LayoutKind,
    MasterCanvas,
    MasterChromeElement,
    MasterEntry,
    MasterManifest,
    MasterSafeArea,
    MasterTheme,
    ThemeEntry,
)
from .scene import (
    BulletElement,
    ImageElement,
    LineElement,
    LiteralColor,
    Scene,
    SceneElement,
    ShapeElement,
    SlideType,
    TextElement,
    ThemeColor,
    ThemeFont,
)

# Phase 0: extractor + types only. Renderers (renderer_html,
# renderer_pptx) land in Phase 3 with their own test coverage.

__all__ = [
    "BulletElement",
    "ImageElement",
    "LayoutDescriptor",
    "LayoutKind",
    "LineElement",
    "LiteralColor",
    "MasterCanvas",
    "MasterChromeElement",
    "MasterEntry",
    "MasterManifest",
    "MasterSafeArea",
    "MasterTheme",
    "ThemeEntry",
    "Scene",
    "SceneElement",
    "ShapeElement",
    "SlideType",
    "TextElement",
    "ThemeColor",
    "ThemeFont",
    "extract_master_from_pptx",
]
