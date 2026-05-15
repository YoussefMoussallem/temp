LIST_USER_MEMORIES_TOOL_NAME = "ListUserMemories"

# Strong "when to call" framing — the failure mode for tool-gated
# memory is "model never calls List, never learns existing slugs,
# saves duplicates / contradictions." Counter that with imperative
# voice and explicit "always before SaveMemory" trigger.
DESCRIPTION = (
    "Return the index of long-term memories saved about THIS USER "
    "across all conversations — role, preferences, brand defaults, "
    "feedback patterns. The result is the index only (slug, type, name, "
    "one-line description). Bodies via "
    '`ReadMemory(scope="user", slug=...)`.\n\n'
    "## ALWAYS call before\n\n"
    '  - `SaveMemory(scope="user", ...)` — to find any existing slug '
    "on the same topic so you reuse it instead of creating a sibling.\n"
    '  - `DeleteMemory(scope="user", ...)` — to confirm the slug '
    "exists.\n\n"
    "## Call at the START of a turn when\n\n"
    '  - The request is open-ended ("build me a deck about X", '
    '"what should we do here").\n'
    "  - A stylistic decision is involved (tone, format, length, emoji, "
    "default brand, hedging vs. directness).\n"
    '  - The user references their own past behaviour ("usually I…", '
    '"like last time", "remember when…").\n'
    "  - It's the first turn of a fresh conversation and the request "
    "isn't purely mechanical.\n\n"
    "## Skip only when\n\n"
    '  - The turn is purely mechanical ("delete slide 3", "swap 2 '
    'and 4") AND no SaveMemory is planned.\n'
    "  - You already called it earlier in the same turn — once per turn "
    "is enough.\n\n"
    "Cheap to call (single query, index only). The cost of skipping when "
    "you shouldn't is duplicate / contradictory memory entries that "
    "confuse future turns. **Default to calling**; skip is the exception."
)
