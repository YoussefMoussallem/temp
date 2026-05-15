"""Master extraction — golden-output snapshot tests.

The extractor's job is to read a .pptx and produce a typed manifest
(canvas, theme fonts/colors, safe area, chrome, layouts). This file
asserts behaviour by snapshot — when the manifest schema or extraction
heuristics change intentionally, regenerate via
``pytest --snapshot-update``. Unintentional drift fails loudly.

Phase 0 ships ONE test: extract from the synthetic minimal fixture.
That's enough to prove the pipeline is wired. Real-world tests using
private fixtures land alongside the bug fixes they enable.
"""

from __future__ import annotations


from pptx_master import MasterManifest, extract_master_from_pptx


def test_extract_minimal_manifest_shape(minimal_pptx: bytes, snapshot) -> None:
    """Extracting the minimal synthetic fixture produces a stable
    manifest. The test pins the *shape* (which fields are present,
    types, default values) rather than every numeric coordinate, so
    Office's silent default tweaks across releases don't churn the
    snapshot.
    """
    manifest = extract_master_from_pptx(minimal_pptx, name="Minimal")

    assert isinstance(manifest, MasterManifest)
    assert manifest.name == "Minimal"
    assert manifest.canvas.w == 1280
    assert manifest.canvas.h == 720

    # Shape snapshot — keys, types, ranges. Avoid asserting exact
    # color values because python-pptx's default theme is whatever
    # version of Office shipped the embedded base XML; pinning hex
    # would couple us to that.
    summary = {
        "canvas": manifest.canvas.model_dump(),
        "theme_fonts_keys": sorted(manifest.theme.fonts.keys()),
        "theme_colors_keys": sorted(manifest.theme.colors.keys()),
        "safe_area_keys": sorted(manifest.safe_area.model_dump().keys()),
        "chrome_count": len(manifest.chrome),
        "chrome_roles": sorted({c.role for c in manifest.chrome}),
        "layout_count": len(manifest.layouts),
        "source_sha256_len": len(manifest.source_sha256 or ""),
        # Phase 2.1: multi-master fields — synthetic minimal has 1
        # master with the default Office theme.
        "masters_count": len(manifest.masters),
        "themes_count": len(manifest.themes),
    }
    assert summary == snapshot


# ── Phase 2.1 — real-template assertions ──────────────────────────────
#
# Two private fixtures (audited separately): stc Board Affairs
# (multi-master, opaque names) and Strategy& White (single-master,
# descriptive names, OBJECT-heavy). Each test skips cleanly when the
# corresponding .pptx isn't on disk (CI / fresh checkout). When both
# are present, the tests guard against regression on the two
# distinct failure modes the audits revealed.


def _layout_kinds_by_name(manifest: MasterManifest) -> dict[str, str]:
    """Flatten masters[*].layouts into {layout_name: classified_kind}.

    Most layout names are unique within a template. When duplicates
    exist (stc has the same name across multiple masters), the value
    becomes a comma-joined string of distinct kinds — the test asserts
    against the SET of kinds for that name.
    """
    by_name: dict[str, set[str]] = {}
    for m in manifest.masters:
        for lay in m.layouts:
            by_name.setdefault(lay.name, set()).add(lay.kind)
    return {k: ",".join(sorted(v)) for k, v in by_name.items()}


def test_stc_board_affairs_multi_master_walk(private_pptx_path) -> None:
    """stc fixture: 11 masters, 22 layouts, 3 unique palettes,
    fonts include STC Forward.

    Audit confirmed the ground truth. This guards Phase 2.1a (walk
    every master) and 2.1d (theme dedupe by hash). Skipped when the
    private .pptx isn't on disk.
    """
    path = private_pptx_path("stc-board-affairs")
    data = path.read_bytes()
    manifest = extract_master_from_pptx(data, name="stc")

    # Multi-master walk
    assert len(manifest.masters) == 11, f"expected 11 slide_masters, got {len(manifest.masters)}"
    total_layouts = sum(len(m.layouts) for m in manifest.masters)
    assert total_layouts == 22, f"expected 22 total layouts across all masters, got {total_layouts}"

    # Theme dedupe — 12 theme files in the .pptx, but only 2 are
    # actually reachable through a slide_master (themes 1-6, 9-11 →
    # STC palette; themes 7-8 → Custom 8 / STC Forward palette).
    # theme12 (Office default) is attached only to a chart, not to any
    # master, so we don't surface it. Walking just slide_masters is
    # the correct semantic — themes that aren't attached to a master
    # can't influence slide generation.
    assert len(manifest.themes) == 2, (
        f"expected 2 master-reachable unique themes, got {len(manifest.themes)}"
    )
    # The two palettes are STC (yellow primary) and Custom 8 (purple primary)
    primaries = sorted(t.palette["primary"] for t in manifest.themes)
    assert primaries == ["#4F008C", "#FFDD40"]

    # STC Forward is referenced by masters 7-8 (theme7/theme8). Phase 1
    # only ever read theme1 and missed it; Phase 2.1's union must
    # surface it.
    fonts = {f for m in manifest.masters for f in (m.fonts.get("major"), m.fonts.get("minor")) if f}
    assert "STC Forward" in fonts, f"STC Forward not found in fonts; got {sorted(fonts)}"


def test_strategy_and_white_classification(private_pptx_path) -> None:
    """Strategy& fixture: 1 master, 45 layouts, classifier handles
    OBJECT placeholders + name-keyword priority.

    Guards Phase 2.1b (OBJECT/CHART/TABLE in _PH_ROLE) and 2.1c
    (strong name keywords win over placeholder counting). Audit
    revealed 24/45 layouts misclassified pre-fix; this asserts a
    representative subset is correct post-fix.
    """
    path = private_pptx_path("strategy-and-white")
    data = path.read_bytes()
    manifest = extract_master_from_pptx(data, name="Strategy& White")

    assert len(manifest.masters) == 1
    assert len(manifest.masters[0].layouts) == 45

    kinds = _layout_kinds_by_name(manifest)

    # Name-keyword classifier wins for these — placeholder counts alone
    # would route them to 'content' (1 BODY + 1 SUBTITLE).
    assert kinds["Quote - White"] == "quote", kinds["Quote - White"]
    assert kinds["Quote - Black"] == "quote", kinds["Quote - Black"]

    # Section header detection from the name; 3 BODY placeholders
    # would otherwise count to 'comparison'.
    assert kinds["Section Header - Side Image"] == "section_header"
    assert kinds["Section Header - Bottom Image"] == "section_header"

    # OBJECT placeholders are now mapped to 'body' so the column-count
    # classifier sees them. "Two Columns" had 2 OBJECT slots that pre-
    # fix counted as 0 bodies → 'content'; now they count → 'two_column'.
    assert kinds["Two Columns"] == "two_column"

    # Three / four / five columns → comparison via name keyword
    # (3+ columns is comparison territory regardless of placeholder type).
    for name in (
        "Three Columns - Case Study",
        "Four Columns",
        "Five Columns",
    ):
        assert kinds[name] == "comparison", f"{name} -> {kinds.get(name)!r}"

    # Title / cover detection
    assert kinds["Title Slide"] == "title"
    assert kinds["Title Slide - Client"] == "title"

    # KPI detection from "Big Number" keyword (pre-fix: 12 BODY = comparison).
    assert kinds["Four Big Numbers"] == "kpi"

    # Theme dedupe: 3 byte-identical themes collapse to 1 palette.
    assert len(manifest.themes) == 1, f"expected 1 unique theme, got {len(manifest.themes)}"


def test_strategy_and_palette_extracted(private_pptx_path) -> None:
    """Burgundy primary (#A32020) is the brand signal; the audit
    confirmed the palette extracts correctly already, this guards the
    de-dup logic doesn't accidentally drop colors."""
    path = private_pptx_path("strategy-and-white")
    data = path.read_bytes()
    manifest = extract_master_from_pptx(data, name="Strategy& White")

    palette = manifest.themes[0].palette
    assert palette["primary"].upper() == "#A32020"
    assert palette["bg"].upper() == "#FFFFFF"
    assert palette["text"].upper() == "#000000"


# ── Phase 2.5: per-placeholder rPr extraction ─────────────────────────


def _layout_by_name(manifest, name: str):
    for m in manifest.masters:
        for lay in m.layouts:
            if lay.name == name:
                return lay
    return None


def test_strategy_and_title_slide_rpr_extracted(private_pptx_path) -> None:
    """Strategy& 'Title Slide' layout title is 36pt theme-tx1 (black);
    subtitle is 14pt explicit-non-bold theme-tx1.

    These values come from layout XML's
    ``txBody/lstStyle/lvl1pPr/defRPr`` and were silently dropped by the
    old geometry-only extractor. The agent appendix uses these to tell
    the LLM exactly what each placeholder should look like.
    """
    path = private_pptx_path("strategy-and-white")
    manifest = extract_master_from_pptx(path.read_bytes(), name="S&")

    layout = _layout_by_name(manifest, "Title Slide")
    assert layout is not None, "Title Slide layout missing"

    titles = [p for p in layout.placeholders if p.role == "title"]
    subtitles = [p for p in layout.placeholders if p.role == "subtitle"]
    assert titles, "no title placeholder"
    assert subtitles, "no subtitle placeholder"

    title = titles[0]
    assert title.size == 36.0, f"title size={title.size} (want 36)"
    # tx1 → dk1 → #000000 in Strategy&'s clrScheme.
    assert (title.color or "").upper() == "#000000", f"title color={title.color!r}"
    # No explicit ``b`` attribute on the title's defRPr → weight stays None.
    assert title.weight is None, f"title weight={title.weight!r}"

    sub = subtitles[0]
    assert sub.size == 14.0
    # b="0" on the defRPr → explicit not-bold → weight=400.
    assert sub.weight == 400


def test_strategy_and_two_columns_subtitle_is_bold_burgundy(
    private_pptx_path,
) -> None:
    """The user-facing test: Two Columns' subtitle is bold burgundy
    (b=1, schemeClr=tx2 → dk2 → #A32020 in Strategy&'s scheme).

    This is the headline use-case for per-placeholder typography —
    when the LLM picks Two Columns and writes a subtitle, the chat
    preview should render it as bold burgundy without us needing to
    extract the rPr per-slide; the layout-level data is the source of
    truth.
    """
    path = private_pptx_path("strategy-and-white")
    manifest = extract_master_from_pptx(path.read_bytes(), name="S&")

    layout = _layout_by_name(manifest, "Two Columns")
    assert layout is not None

    subs = [p for p in layout.placeholders if p.role == "subtitle"]
    assert subs, "Two Columns has no subtitle placeholder"
    sub = subs[0]
    assert sub.size == 18.0, f"size={sub.size}"
    assert sub.weight == 700, f"weight={sub.weight} (want bold/700)"
    assert (sub.color or "").upper() == "#A32020", f"color={sub.color!r} (want burgundy #A32020)"


def test_strategy_and_four_big_numbers_body_is_huge_bold_burgundy(
    private_pptx_path,
) -> None:
    """The 'Four Big Numbers' layout has 96pt bold body placeholders
    in the brand burgundy. Verifies our extractor handles literal
    srgbClr values (not just scheme references) and ``sz`` values
    above the typical 12-44pt range.
    """
    path = private_pptx_path("strategy-and-white")
    manifest = extract_master_from_pptx(path.read_bytes(), name="S&")

    layout = _layout_by_name(manifest, "Four Big Numbers")
    assert layout is not None
    # Four BODY placeholders at 96pt (sz=9600). Find the first one with
    # explicit burgundy color.
    big_burgundies = [
        p
        for p in layout.placeholders
        if p.role == "body"
        and p.size == 96.0
        and p.weight == 700
        and (p.color or "").upper() == "#A32020"
    ]
    assert big_burgundies, "expected a 96pt bold #A32020 body placeholder; got " + str(
        [(p.role, p.size, p.weight, p.color) for p in layout.placeholders]
    )


def test_strategy_and_section_header_resolves_theme_font(
    private_pptx_path,
) -> None:
    """``<a:latin typeface="+mj-lt"/>`` references the theme's major
    font. The Section Header layouts use this rather than a literal
    typeface; the resolved name should be Georgia (Strategy&'s
    fontScheme/majorFont/latin)."""
    path = private_pptx_path("strategy-and-white")
    manifest = extract_master_from_pptx(path.read_bytes(), name="S&")

    layout = _layout_by_name(manifest, "Section Header - Side Image")
    assert layout is not None

    titles = [p for p in layout.placeholders if p.role == "title"]
    assert titles
    assert titles[0].font == "Georgia", (
        f"got font={titles[0].font!r}; expected Georgia (theme major-font resolution from +mj-lt)"
    )


def test_strategy_and_quote_white_subtitle_bold_attribution(
    private_pptx_path,
) -> None:
    """Quote - White's subtitle (the attribution byline below the
    quote) is 14pt bold theme-tx1 (#000000). Title placeholder is
    36pt with a literal #7D7D7D fill — verifies srgbClr literal
    extraction works alongside scheme references.
    """
    path = private_pptx_path("strategy-and-white")
    manifest = extract_master_from_pptx(path.read_bytes(), name="S&")
    layout = _layout_by_name(manifest, "Quote - White")
    assert layout is not None

    subs = [p for p in layout.placeholders if p.role == "subtitle"]
    assert subs
    assert subs[0].size == 14.0
    assert subs[0].weight == 700
    assert (subs[0].color or "").upper() == "#000000"

    titles = [p for p in layout.placeholders if p.role == "title"]
    assert titles
    assert titles[0].size == 36.0
    # Literal srgbClr 7D7D7D — Strategy& uses it for muted quote
    # placeholder text.
    assert (titles[0].color or "").upper() == "#7D7D7D"
