"""ExportDeckTool prompt + name constants + LLM-converter prompt."""

EXPORT_DECK_TOOL_NAME = "ExportDeck"

DESCRIPTION = """
Export the active project's slide deck to a fully editable PowerPoint
(.pptx) file.

How it works (fully agentic, no user click required):
  1. The tool reads every slide from the active project.
  2. For each slide, an LLM converts the slide's HTML into a pptxgenjs
     JSON spec (text boxes, shapes, images — fully editable in
     PowerPoint, NOT a rasterized image).
  3. The spec is streamed to the user's browser, which assembles the
     .pptx with pptxgenjs and triggers a download.

Usage notes:
  - Use when the user asks to "export", "download", "save as
    PowerPoint", or otherwise wants a file deliverable.
  - `filename` is optional; defaults to "presentation.pptx". The .pptx
    extension is appended automatically if omitted.
  - Slides MUST follow the "Pptxgenjs-friendly structure" rules from
    the system prompt (flat absolutely-positioned divs). If the deck
    was authored with flexbox/grid layouts, the converter will do its
    best but the .pptx may have positioning glitches.
  - The deck state at the moment this tool runs is what gets exported
    — finalize edits before calling.
  - Read-only with respect to the deck: does not modify slides.
"""


# ============================================================================
# Per-slide converter prompt
# ============================================================================
#
# Sent as the system_prompt for every per-slide LLMAdapter.generate() call.
# The slide HTML is sent as the single user message. The LLM must reply with
# ONLY a JSON object matching the schema below — no prose, no fences. We
# defensively strip ```json fences in case the model adds them anyway.
#
# Coordinate system: pptxgenjs uses inches. LAYOUT_WIDE = 13.333" × 7.5".
# Slides are designed for 960×540 px, so 1px ≈ 0.01389" on both axes.

CONVERTER_SYSTEM_PROMPT = """\
You convert a single HTML slide (designed for a 960×540 px canvas) into
a JSON spec that drives pptxgenjs to produce a fully editable PowerPoint
slide. Output strict JSON ONLY — no markdown, no commentary, no fences.

OUTPUT SHAPE (exact):
{
  "background": { "color": "RRGGBB" } | null,
  "elements": [ <element>, <element>, ... ]
}

Each <element> is one of:

  TEXT box:
    {
      "kind": "text",
      "text": "the visible text exactly as it appears",
      "options": {
        "x": 0.83, "y": 0.83, "w": 11.67, "h": 0.83,
        "fontSize": 36,
        "fontFace": "Arial",
        "color": "FFFFFF",
        "bold": true,
        "italic": false,
        "align": "left" | "center" | "right",
        "valign": "top" | "middle" | "bottom"
      }
    }

  SHAPE (rectangle / ellipse / line — for backgrounds, accent bars,
  dividers, decorative cards):
    {
      "kind": "shape",
      "shape": "rect" | "roundRect" | "ellipse" | "line",
      "options": {
        "x": 0.83, "y": 1.94, "w": 2.78, "h": 0.06,
        "fill": { "color": "9B1B30" },
        "line": { "type": "none" } | { "color": "AAAAAA", "width": 1 },
        "rectRadius": 0.05
      }
    }

  IMAGE (only if the HTML has an <img> with a usable src):
    {
      "kind": "image",
      "options": {
        "path": "https://...",     // OR
        "data": "data:image/png;base64,...",
        "x": 0.83, "y": 0.83, "w": 5, "h": 3
      }
    }

COORDINATE SYSTEM:
- Slide is 13.333 inches wide, 7.5 inches tall (LAYOUT_WIDE / 16:9).
- Convert pixel positions to inches: inches = pixels × 0.01389.
- All x/y/w/h in `options` are inches.

COLOR FORMAT:
- All hex colors WITHOUT the leading '#'. White is "FFFFFF".
- If a CSS color is `rgb()` or a named color, convert to hex first.
- If background is missing/transparent, set "background": null.

FONT SIZES:
- Use the px font-size from the HTML directly as the pptxgenjs
  fontSize (pptxgenjs `fontSize` is points, but a 1:1 px→pt mapping
  reads correctly for slide-deck typography). Round to nearest integer.

ELEMENT EXTRACTION RULES:
- Walk every element on the slide that has a position (absolutely-
  positioned div, image, etc.) and emit one entry per element, in the
  visual stacking order (background shapes first, foreground text last).
- A div with text content → "text" element. Read color, font-size,
  font-weight, font-family, text-align directly from inline styles.
- A div with NO text and only background/border → "shape" element
  (use "rect"; if border-radius is set, use "roundRect" with
  rectRadius = radius_px × 0.01389).
- An <img> tag → "image" element. Use src as path/data.
- Skip empty container divs that have no background and no text.
- Do not invent elements that aren't in the HTML.
- Preserve text content character-for-character (including bullet
  glyphs like •, ►, –). Do NOT rewrite or "improve" the text.

If the HTML uses flexbox or grid layout (no absolute positions), do
your best to estimate plausible coordinates that respect the visual
hierarchy you see — title near top, body below, accents where they
appear. Never refuse: always emit a JSON object, even if approximate.

Return ONLY the JSON object. No ```json fences. No explanation.
"""
