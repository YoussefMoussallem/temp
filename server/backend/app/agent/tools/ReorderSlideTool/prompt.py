REORDER_SLIDE_TOOL_NAME = "ReorderSlide"

DESCRIPTION = (
    "Move a slide to a new position in its project's deck. Pass "
    "`after_slide_id=null` (or omit it) to move the slide to the top of the "
    "deck; otherwise the slide lands immediately after the slide with that "
    "id. The tool emits the full new ordered list so the UI can redraw "
    "without guessing the delta."
)
