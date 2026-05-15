# pptx_master

Parse PowerPoint masters into structured slide-IR manifests.

A self-contained Python package (`pptx-master`) that is a **member of the repo-root uv workspace** (see the root `pyproject.toml` + `uv.lock`). Install the whole workspace from the repo root with `uv sync` or `uv sync --group dev`; do not rely on ad-hoc `uv pip install -e` for reproducible installs.

## What it does

Given the bytes of a `.pptx` (or a path / file-like), returns a `MasterManifest` with:

- **canvas** — slide dimensions in CSS pixels
- **masters[]** — every `SlideMaster` part, each with its theme tokens (palette, fonts), placeholders, and a flat list of `LayoutDescriptor` rows
- **themes[]** — deduplicated theme entries (raw-XML hash collapses byte-identical themes; resolved-content matching collapses themes that differ only in whitespace)
- **fonts_referenced** — every typeface name the package mentions (theme major/minor + per-placeholder rPr)
- **chrome** — locked text + geometry from masters[0] (legacy single-master fallback)
- **safe_area** — content region from masters[0] (legacy single-master fallback)

Bytes for the original `.pptx` and any bundled brand fonts are NOT inside the manifest — they're stored separately in blob by the upload pipeline.

## Layout definition

A "layout" in this codebase = exactly one PowerPoint `SlideLayout` XML part, augmented with:

- `placeholders` — typed, geometry-resolved placeholder list (role + x/y/w/h + per-placeholder typography + locked text)
- `kind` — heuristic archetype (`title` / `agenda` / `content` / `two_column` / `comparison` / `kpi` / `quote` / `section_header` / `blank` / `other`)
- `safe_area` — per-layout content region when it differs from the master's safe area; `None` falls through to the master's

The classifier checks the layout's name first (strong vendor signals like "Quote - White" or "Two Columns" win), then falls back to placeholder count + GEOMETRY:

- 2 BODY placeholders side-by-side → `two_column`
- 2 BODY placeholders stacked (main content + source line) → `content`
- 3+ BODY placeholders side-by-side → `comparison`
- 3+ BODY placeholders stacked (process steps / TOC items) → `content`

Curation lets the user override `kind` per layout.

## Resilience

A sweep across 145 real-world templates surfaced ~10% with malformed `[Content_Types].xml` — PowerPoint accepts these silently, python-pptx refuses them. `_repair_content_types` runs unconditionally before opening the package: parses the manifest, unions in any missing `Default` entries for known media extensions (png / jpg / gif / svg / wmf / emf / mp4 / wav / etc.), and rewrites the package in-memory. After the repair pass the failure rate against `~/Downloads` is 0%.

## Loose spots (not fixed in current iteration)

- **Cross-master deduplication** — multi-theme decks reuse the same layout *shape* across themes (stc has 7 layouts called "12_Content slide" — same shape × 7 theme variants). The manifest carries them as separate `LayoutDescriptor` rows; the curation UI surfaces this with a `×N` badge and a "distinct shapes" count, but doesn't auto-collapse. Geometry-signature matching could group them properly.
- **Semantic slot annotation beyond OOXML roles** — every BODY placeholder shares the same role label whether it carries bullets, a chart caption, a quote attribution, or a stat. Distinguishing them needs richer per-placeholder semantics than the OOXML schema provides.
- **Classifier vocabulary** — 10 kinds. Real-world templates have more archetypes (`matrix_2x2`, `process`, `roadmap`, `scorecard`); we collapse them into `other` for now.
- **OOXML `embeddedFont` parts** — when a `.pptx` carries embedded font bytes inside the package, we extract the typeface *names* but not the bytes. Bundled fonts come via the upload pipeline's `fonts_assets`. Reading embedded fonts from the OOXML directly is a future extension; the architecture (`source: "embedded"` field on `fonts_assets`) supports it.

## Testing

```bash
# from repository root (after: uv sync --group dev)
uv run --directory server/libs/pptx_master pytest tests/ -v
```

Real-template tests live in `server/backend/tests/test_master_extractor.py` because they depend on backend's synthetic fixture builder + private `~/Downloads` template paths + syrupy snapshots.
