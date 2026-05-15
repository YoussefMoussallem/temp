READ_SLIDE_TOOL_NAME = "ReadSlide"

DESCRIPTION = (
    "Fetch the full content of ONE slide by its `slide_id`. Returns "
    "`id`, `position`, `title`, and the slide's `html`. Use this when "
    "you need to read a specific slide's markup to edit it precisely "
    "(price change, copy edit, layout tweak) — call `ReadSlide` with "
    "the id rather than `ListSlides(include_html=true)` so the response "
    "stays small enough to keep in context. Read-only — does not change "
    "the deck.\n"
    "\n"
    "Typical flow: call `ListSlides` (no html) to get the index → pick "
    "the target id from the position/title → `ReadSlide(slide_id=...)` "
    "for the full HTML → `UpdateSlide` with the edited HTML."
)
