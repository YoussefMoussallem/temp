LIST_PROJECT_MEMORIES_TOOL_NAME = "ListProjectMemories"

DESCRIPTION = (
    "Return the index of long-term memories saved about THIS PROJECT — "
    "audience, deadline, key message, decisions, stakeholders, "
    "references. Index only (slug, type, name, one-line description). "
    'Bodies via `ReadMemory(scope="project", slug=...)`.\n\n'
    "## ALWAYS call before\n\n"
    '  - `SaveMemory(scope="project", ...)` — to find any existing '
    "slug on the same topic so you reuse it instead of creating a "
    "sibling.\n"
    '  - `DeleteMemory(scope="project", ...)` — to confirm the slug '
    "exists.\n\n"
    "## Call at the START of a turn when\n\n"
    "  - First substantive turn after opening a project — audience / "
    "deadline / key-message likely shape the answer.\n"
    "  - Request mentions scope, audience, deadline, brand, "
    'stakeholders, or references prior decisions ("we agreed to…", '
    '"the deck angle is…").\n'
    "  - After a project switch — your in-context facts may be stale "
    "from the previous project.\n"
    "  - Any non-trivial new slide creation (audience shapes content).\n\n"
    "## Skip only when\n\n"
    '  - Purely mechanical edit on a single slide ("swap 2 and 4", '
    '"delete slide 3") AND no SaveMemory is planned.\n'
    "  - You already called it earlier in the same turn.\n\n"
    "Requires an active project — fails otherwise. Cheap to call; "
    "skipping when relevant means re-asking the user the same setup "
    "questions later. **Default to calling**; skip is the exception."
)
