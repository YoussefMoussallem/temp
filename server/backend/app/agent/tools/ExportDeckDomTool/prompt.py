"""ExportDeckDomTool prompt + name constant.

Sibling to ExportDeck, but no per-slide LLM converter prompt — the DOM
exporter renders the live slide HTML directly via ``llm-dom-to-pptx``
in the browser, so there's nothing for the backend LLM to translate.
"""

EXPORT_DECK_DOM_TOOL_NAME = "ExportDeckDom"

DESCRIPTION = """
Export the active project's slide deck to a PowerPoint (.pptx) file
using the DOM-rendering pipeline (no per-slide LLM conversion).

How it works:
  1. The tool reads every slide for the active project.
  2. Slide HTML is shipped to the user's browser, which mounts each
     slide off-screen and runs ``llm-dom-to-pptx`` against the live
     DOM to capture text, shapes, and images directly from what the
     browser renders.
  3. The browser assembles the .pptx with pptxgenjs and triggers a
     download.

When to choose this over `ExportDeck`:
  - Use this when slides rely on rendered CSS (gradients, complex
    backgrounds, layout that doesn't fit the flat absolutely-
    positioned-divs contract) — the DOM exporter sees the rendered
    pixels rather than parsing markup.
  - Faster and cheaper: no per-slide LLM call, so no tokens spent on
    the conversion and no waiting for the model to translate each
    slide.
  - Lower fidelity for "fully editable" output: text boxes are best-
    effort approximations of what the DOM exporter could extract,
    rather than an LLM-curated mapping to pptxgenjs primitives.

Usage notes:
  - `filename` is optional; defaults to "presentation-dom.pptx". The
    .pptx extension is appended automatically if omitted.
  - The deck state at the moment this tool runs is what gets exported
    — finalize edits before calling.
  - Read-only with respect to the deck: does not modify slides.

Important: The DOM-export and LLM-converter (`ExportDeck`) tools
produce subtly different .pptx files. Always confirm with the user
which one they want before calling either — do not assume the
default.
"""
