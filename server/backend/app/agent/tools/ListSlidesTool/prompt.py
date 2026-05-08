LIST_SLIDES_TOOL_NAME = "ListSlides"

DESCRIPTION = (
    "List the slides currently in the active project's deck, in order. Use "
    "this whenever you need to know what slides exist before editing, "
    "reordering, or deleting — the id of a slide is required for those "
    "tools. Returns each slide's `id`, `position`, and `title`. Pass "
    "`include_html=true` to also return the full `html` for each slide "
    "(only needed when you must read a slide's content to edit it; skip "
    "otherwise to keep the response compact). Read-only — does not change "
    "the deck."
)
